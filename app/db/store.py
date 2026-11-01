"""STORE=pg 的資料存放：使用者資料寫進 app schema（欄位對照見 docs/database.md）。

評估個案、判定結果、報告、草稿是凍結的快照，存 jsonb（model_dump(mode="json")），讀出時 model_validate；
要查詢的東西（user_id、case_id、report_date、decision_data_version、成分列）拆成一般欄位。
每個方法一個交易（離開 pool.connection() 時 commit，例外則 rollback）。
"""

from datetime import date
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from app.schemas.assessment import Assessment
from app.schemas.case import AccountProfile, CaseProfile
from app.schemas.common import ExclusiveSelection
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import ConditionCode, Sex
from app.schemas.label import ExtractionDraft, LabelCorrection, VerifiedProduct
from app.schemas.report import Report
from app.store import TAIPEI_TZ, TEST_PROFILE, TEST_USER_ID, TEST_USER_NAME, AccountUser


def _json(model: BaseModel) -> Jsonb:
    return Jsonb(model.model_dump(mode="json"))


class PgStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def has_data_version(self, version: str) -> bool:
        """這版參考資料匯入過了嗎（assessments.decision_data_version 的外鍵目標）。"""
        with self._pool.connection() as conn:
            return conn.execute("SELECT 1 FROM catalog.data_versions WHERE version = %s", [version]).fetchone() is not None

    # ── 帳號與基本資料 ──────────────────────────────────────

    def ensure_test_user(self) -> None:
        """AUTH=test：測試帳號與預設基本資料不存在就建立（已存在不動）。"""
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO app.users (user_id, google_sub, name) VALUES (%s, NULL, %s) ON CONFLICT DO NOTHING",
                [TEST_USER_ID, TEST_USER_NAME],
            )
            exists = conn.execute("SELECT 1 FROM app.health_profiles WHERE user_id = %s", [TEST_USER_ID]).fetchone()
            if not exists:
                self._write_profile(conn, TEST_USER_ID, TEST_PROFILE)

    def find_or_create_google_user(self, sub: str, email: str | None, name: str | None) -> UUID:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO app.users (user_id, google_sub, email, name) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name "
                "RETURNING user_id",
                [uuid4(), sub, email, name],
            ).fetchone()
        return row[0]

    def get_user(self, user_id: UUID) -> AccountUser | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT user_id, email, name FROM app.users WHERE user_id = %s", [user_id]).fetchone()
        return AccountUser(*row) if row else None

    def get_profile(self, user_id: UUID) -> AccountProfile | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT birth_year, birth_month, sex, conditions_none FROM app.health_profiles WHERE user_id = %s",
                [user_id],
            ).fetchone()
            if row is None:
                return None
            codes = conn.execute(
                "SELECT c.condition_code FROM app.health_profile_conditions c "
                "JOIN catalog.known_conditions k USING (condition_code) WHERE c.user_id = %s ORDER BY k.ord",
                [user_id],
            ).fetchall()
        return AccountProfile(
            birth_year=row[0],
            birth_month=row[1],
            sex=Sex(row[2]),
            conditions=ExclusiveSelection[ConditionCode](
                selected=[ConditionCode(c[0]) for c in codes], none_selected=row[3]
            ),
        )

    def save_profile(self, user_id: UUID, profile: AccountProfile) -> None:
        with self._pool.connection() as conn:
            self._write_profile(conn, user_id, profile)

    @staticmethod
    def _write_profile(conn: Connection, user_id: UUID, profile: AccountProfile) -> None:
        conn.execute(
            "INSERT INTO app.health_profiles (user_id, birth_year, birth_month, sex, conditions_none, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT (user_id) DO UPDATE SET "
            "birth_year = EXCLUDED.birth_year, birth_month = EXCLUDED.birth_month, sex = EXCLUDED.sex, "
            "conditions_none = EXCLUDED.conditions_none, updated_at = now()",
            [user_id, profile.birth_year, profile.birth_month, profile.sex.value, profile.conditions.none_selected],
        )
        conn.execute("DELETE FROM app.health_profile_conditions WHERE user_id = %s", [user_id])
        conn.cursor().executemany(
            "INSERT INTO app.health_profile_conditions (user_id, condition_code) VALUES (%s, %s)",
            [(user_id, c.value) for c in profile.conditions.selected],
        )

    # ── 保健食品與藥包草稿 ──────────────────────────────────

    def save_supplement_draft(self, user_id: UUID, draft: ExtractionDraft) -> None:
        self._save_draft("supplement_drafts", "product_id", user_id, draft.product_id, draft)

    def get_supplement_draft(self, user_id: UUID, product_id: UUID) -> ExtractionDraft | None:
        data = self._get_draft("supplement_drafts", "product_id", user_id, product_id)
        return ExtractionDraft.model_validate(data) if data else None

    def save_drug_draft(self, user_id: UUID, draft: DrugDraft) -> None:
        self._save_draft("drug_drafts", "draft_id", user_id, draft.draft_id, draft)

    def get_drug_draft(self, user_id: UUID, draft_id: UUID) -> DrugDraft | None:
        data = self._get_draft("drug_drafts", "draft_id", user_id, draft_id)
        return DrugDraft.model_validate(data) if data else None

    def _save_draft(self, table: str, key: str, user_id: UUID, draft_id: UUID, draft: BaseModel) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                f"INSERT INTO app.{table} ({key}, user_id, draft) VALUES (%s, %s, %s) "
                f"ON CONFLICT ({key}) DO UPDATE SET draft = EXCLUDED.draft WHERE {table}.user_id = EXCLUDED.user_id",
                [draft_id, user_id, _json(draft)],
            )

    def _get_draft(self, table: str, key: str, user_id: UUID, draft_id: UUID) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT draft FROM app.{table} WHERE {key} = %s AND user_id = %s", [draft_id, user_id]
            ).fetchone()
        return row[0] if row else None

    # ── 核對完的產品 ────────────────────────────────────────

    def save_product(self, user_id: UUID, product: VerifiedProduct) -> None:
        with self._pool.connection() as conn:
            saved = conn.execute(
                "INSERT INTO app.products (product_id, user_id, product_name, snapshot, verified_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (product_id) DO UPDATE SET "
                "product_name = EXCLUDED.product_name, snapshot = EXCLUDED.snapshot, "
                "verified_at = EXCLUDED.verified_at WHERE products.user_id = EXCLUDED.user_id",
                [product.product_id, user_id, product.product_name, _json(product), product.verified_at],
            )
            if saved.rowcount == 0:
                raise PermissionError(f"產品 {product.product_id} 屬於其他使用者")
            conn.execute("DELETE FROM app.product_nutrients WHERE product_id = %s", [product.product_id])
            conn.cursor().executemany(
                "INSERT INTO app.product_nutrients (product_id, row_id, ingredient_code, scope_status, per_serving, "
                "unit, elemental_basis, peak_daily_amount, average_daily_amount) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        product.product_id,
                        n.row_id or f"idx{i}",
                        n.standard_code.value if n.standard_code else None,
                        n.scope_status.value,
                        n.per_serving,
                        n.unit.value if n.unit else None,
                        n.elemental_basis.value,
                        n.peak_daily_amount,
                        n.average_daily_amount,
                    )
                    for i, n in enumerate(product.nutrients)
                ],
            )

    def get_products(self, user_id: UUID, product_ids: list[UUID]) -> list[VerifiedProduct]:
        if not product_ids:
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT product_id, snapshot FROM app.products WHERE user_id = %s AND product_id = ANY(%s)",
                [user_id, product_ids],
            ).fetchall()
        mine = {pid: VerifiedProduct.model_validate(snap) for pid, snap in rows}
        return [mine[pid] for pid in product_ids if pid in mine]

    # ── 評估與修正紀錄 ──────────────────────────────────────

    def save_assessment(self, case: CaseProfile, assessment: Assessment) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO app.assessments "
                "(case_id, user_id, created_at, decision_data_version, case_profile, assessment) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [case.case_id, case.user_id, case.created_at, case.decision_data_version, _json(case), _json(assessment)],
            )
            conn.cursor().executemany(
                "INSERT INTO app.assessment_products (case_id, product_id) VALUES (%s, %s)",
                [(case.case_id, pid) for pid in dict.fromkeys(p.product_id for p in case.supplements)],
            )

    def get_case(self, user_id: UUID, case_id: UUID) -> tuple[CaseProfile, Assessment] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT case_profile, assessment FROM app.assessments WHERE case_id = %s AND user_id = %s",
                [case_id, user_id],
            ).fetchone()
        return (CaseProfile.model_validate(row[0]), Assessment.model_validate(row[1])) if row else None

    def save_label_corrections(self, user_id: UUID, corrections: list[LabelCorrection]) -> None:
        with self._pool.connection() as conn:
            conn.cursor().executemany(
                "INSERT INTO app.label_corrections (user_id, product_id, correction) VALUES (%s, %s, %s)",
                [(user_id, c.product_id, _json(c)) for c in corrections],
            )

    def save_drug_corrections(self, user_id: UUID, corrections: list[DrugCorrection]) -> None:
        with self._pool.connection() as conn:
            conn.cursor().executemany(
                "INSERT INTO app.drug_corrections (user_id, case_id, correction) VALUES (%s, %s, %s)",
                [(user_id, c.case_id, _json(c)) for c in corrections],
            )

    # ── 報告 ────────────────────────────────────────────────

    def save_report(self, user_id: UUID, report: Report) -> None:
        """一個評估只有一份報告（case_id UNIQUE）：已經有就不覆蓋，呼叫端用 get_report_by_case 取既有那份。"""
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO app.reports (report_id, case_id, user_id, generated_at, report_date, report) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (case_id) DO NOTHING",
                [
                    report.report_id,
                    report.case_id,
                    user_id,
                    report.generated_at,
                    report.generated_at.astimezone(TAIPEI_TZ).date(),
                    _json(report),
                ],
            )

    def get_report_by_case(self, user_id: UUID, case_id: UUID) -> Report | None:
        return self._one_report("case_id = %s AND user_id = %s", [case_id, user_id])

    def get_report(self, user_id: UUID, report_id: UUID) -> Report | None:
        return self._one_report("report_id = %s AND user_id = %s", [report_id, user_id])

    def _one_report(self, where: str, params: list) -> Report | None:
        with self._pool.connection() as conn:
            row = conn.execute(f"SELECT report FROM app.reports WHERE {where}", params).fetchone()
        return Report.model_validate(row[0]) if row else None

    def list_reports(self, user_id: UUID, date_from: date | None, date_to: date | None) -> list[Report]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT report FROM app.reports WHERE user_id = %s "
                "AND (%s::date IS NULL OR report_date >= %s::date) "
                "AND (%s::date IS NULL OR report_date <= %s::date) "
                "ORDER BY generated_at DESC",
                [user_id, date_from, date_from, date_to, date_to],
            ).fetchall()
        return [Report.model_validate(r[0]) for r in rows]
