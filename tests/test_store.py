"""Store 的行為測試：同一組測試跑兩種實作（記憶體、資料庫），行為必須一致。

資料庫那組標 db：沒設 DATABASE_URL 就略過。每個測試用新的 user_id／case_id，資料庫不必清空。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.catalog_source import CsvCatalogSource
from app.schemas.assessment import Assessment
from app.schemas.case import AccountProfile, CaseProfile
from app.schemas.common import ExclusiveSelection
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import ConditionCode, Sex
from app.schemas.label import ExtractionDraft, LabelCorrection, VerifiedProduct
from app.schemas.report import Report
from app.store import TAIPEI_TZ, TEST_USER_ID, InMemoryStore

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"
DATA_VERSION = CsvCatalogSource().load_reference().version  # 資料庫的 assessments 外鍵指向 data_versions


def _example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture(params=["memory", pytest.param("pg", marks=pytest.mark.db)])
def store(request):
    if request.param == "memory":
        yield InMemoryStore()
        return
    from psycopg_pool import ConnectionPool

    from app.db.store import PgStore

    url = request.getfixturevalue("test_database_url")
    with ConnectionPool(url, min_size=1, max_size=4) as pool:
        yield PgStore(pool)


@pytest.fixture
def user(store) -> UUID:
    return store.find_or_create_google_user(f"sub-{uuid4()}", "a@example.com", "甲")


def _profile(**changes) -> AccountProfile:
    base = AccountProfile(
        birth_year=1950,
        birth_month=6,
        sex=Sex.FEMALE,
        conditions=ExclusiveSelection[ConditionCode](
            selected=[ConditionCode.HYPERTENSION, ConditionCode.T2DM], none_selected=False
        ),
    )
    return base.model_copy(update=changes)


def _product(**changes) -> VerifiedProduct:
    base = CaseProfile.model_validate(_example("case_profile.json")).supplements[0]
    return base.model_copy(update={"product_id": uuid4(), **changes})


def _case(user_id: UUID, products: list[VerifiedProduct]) -> tuple[CaseProfile, Assessment]:
    case = CaseProfile.model_validate(_example("case_profile.json")).model_copy(
        update={
            "case_id": uuid4(),
            "user_id": user_id,
            "decision_data_version": DATA_VERSION,
            "supplements": products,
            "created_at": datetime.now(UTC),
        }
    )
    assessment = Assessment.model_validate(_example("06_assessment.json")).model_copy(
        update={"case_id": case.case_id, "decision_data_version": DATA_VERSION}
    )
    return case, assessment


def _report(case_id: UUID, generated_at: datetime | None = None) -> Report:
    base = Report.model_validate(_example("08_report.json"))
    return base.model_copy(
        update={"report_id": uuid4(), "case_id": case_id, "generated_at": generated_at or datetime.now(UTC)}
    )


def _saved_case(store, user_id: UUID) -> tuple[CaseProfile, Assessment]:
    product = _product()
    store.save_product(user_id, product)
    case, assessment = _case(user_id, [product])
    store.save_assessment(case, assessment)
    return case, assessment


# ── 帳號與基本資料 ──────────────────────────────────────────


def test_同一個Google帳號永遠回同一個user_id並更新姓名(store):
    sub = f"sub-{uuid4()}"
    first = store.find_or_create_google_user(sub, "a@example.com", "甲")
    second = store.find_or_create_google_user(sub, "b@example.com", "乙")
    assert first == second
    user = store.get_user(first)
    assert (user.email, user.name) == ("b@example.com", "乙")


def test_不存在的使用者回None(store):
    assert store.get_user(uuid4()) is None
    assert store.get_profile(uuid4()) is None


def test_還沒填基本資料回None填了之後讀得回來(store, user):
    assert store.get_profile(user) is None
    profile = _profile()
    store.save_profile(user, profile)
    assert store.get_profile(user) == profile


def test_基本資料可以改成以上皆無(store, user):
    store.save_profile(user, _profile())
    none = _profile(conditions=ExclusiveSelection[ConditionCode](selected=[], none_selected=True))
    store.save_profile(user, none)
    assert store.get_profile(user) == none


# ── 使用者隔離 ──────────────────────────────────────────────


def test_使用者拿不到別人的產品(store, user):
    other = store.find_or_create_google_user(f"sub-{uuid4()}", None, "乙")
    mine, theirs = _product(), _product()
    store.save_product(user, mine)
    store.save_product(other, theirs)
    ids = [mine.product_id, theirs.product_id]
    assert store.get_products(user, ids) == [mine]
    assert store.get_products(other, ids) == [theirs]


def test_產品依傳入順序回傳並略過找不到的編號(store, user):
    a, b = _product(), _product()
    store.save_product(user, a)
    store.save_product(user, b)
    assert store.get_products(user, [b.product_id, uuid4(), a.product_id]) == [b, a]


def test_產品名稱為空也存得進去(store, user):
    product = _product(product_name=None)
    store.save_product(user, product)
    assert store.get_products(user, [product.product_id]) == [product]


def test_使用者拿不到別人的草稿(store, user):
    other = store.find_or_create_google_user(f"sub-{uuid4()}", None, "乙")
    supplement = ExtractionDraft.model_validate(_example("04_supplement_draft.json")).model_copy(
        update={"product_id": uuid4()}
    )
    drug = DrugDraft.model_validate(_example("04_drug_draft.json")).model_copy(update={"draft_id": uuid4()})
    store.save_supplement_draft(user, supplement)
    store.save_drug_draft(user, drug)
    assert store.get_supplement_draft(user, supplement.product_id) == supplement
    assert store.get_drug_draft(user, drug.draft_id) == drug
    assert store.get_supplement_draft(other, supplement.product_id) is None
    assert store.get_drug_draft(other, drug.draft_id) is None


def test_使用者拿不到別人的評估與報告(store, user):
    other = store.find_or_create_google_user(f"sub-{uuid4()}", None, "乙")
    case, assessment = _saved_case(store, user)
    report = _report(case.case_id)
    store.save_report(user, report)

    assert store.get_case(user, case.case_id) == (case, assessment)
    assert store.get_case(other, case.case_id) is None
    assert store.get_report(user, report.report_id) == report
    assert store.get_report(other, report.report_id) is None
    assert store.get_report_by_case(other, case.case_id) is None
    assert store.list_reports(other, None, None) == []


# ── 報告 ────────────────────────────────────────────────────


def test_同一個評估重複產報告時讀回既有那份(store, user):
    case, _ = _saved_case(store, user)
    first, second = _report(case.case_id), _report(case.case_id)
    assert store.save_report(user, first) == first
    # 同時送兩次「產生報告」：第二份沒存進去，要拿回第一份，不然前端拿到的 report_id 查不到
    assert store.save_report(user, second) == first
    assert store.get_report_by_case(user, case.case_id) == first
    assert store.get_report(user, second.report_id) is None


def test_報告歷史依產生時間新到舊(store, user):
    now = datetime.now(UTC)
    reports = []
    for age_hours in (3, 1, 2):
        case, _ = _saved_case(store, user)
        report = _report(case.case_id, now - timedelta(hours=age_hours))
        store.save_report(user, report)
        reports.append(report)
    old, newest, middle = reports[0], reports[1], reports[2]
    assert store.list_reports(user, None, None) == [newest, middle, old]


def test_報告日期以台灣時間判斷是哪一天(store, user):
    case, _ = _saved_case(store, user)
    # UTC 2026-03-10 17:00 ＝ 台灣 2026-03-11 01:00
    report = _report(case.case_id, datetime(2026, 3, 10, 17, 0, tzinfo=UTC))
    store.save_report(user, report)
    assert report.generated_at.astimezone(TAIPEI_TZ).date().isoformat() == "2026-03-11"
    from datetime import date

    assert store.list_reports(user, date(2026, 3, 11), date(2026, 3, 11)) == [report]
    assert store.list_reports(user, date(2026, 3, 10), date(2026, 3, 10)) == []
    assert store.list_reports(user, date(2026, 3, 12), None) == []
    assert store.list_reports(user, None, date(2026, 3, 10)) == []


# ── 修正紀錄 ────────────────────────────────────────────────


def test_修正紀錄寫得進去(store, user):
    case, _ = _saved_case(store, user)
    label = [LabelCorrection.model_validate(c) for c in _example("05b_label_corrections.json")]
    drug = [
        DrugCorrection.model_validate(c).model_copy(update={"case_id": case.case_id})
        for c in _example("05c_drug_corrections.json")
    ]
    store.save_label_corrections(user, label)
    store.save_drug_corrections(user, drug)
    store.save_label_corrections(user, [])
    store.save_drug_corrections(user, [])


def test_測試帳號預設有基本資料(store):
    if isinstance(store, InMemoryStore):
        assert store.get_profile(TEST_USER_ID) is not None
    else:
        store.ensure_test_user()
        store.ensure_test_user()  # 重複呼叫不出錯、不覆蓋
        assert store.get_profile(TEST_USER_ID) is not None
        assert store.get_user(TEST_USER_ID).name == "測試帳號"
