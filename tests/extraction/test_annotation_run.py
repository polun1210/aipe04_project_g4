"""雙盲標註的執行：用假的 runner 取代 claude／codex，不真的執行它們。"""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.annotate.compare import compare, load_annotations
from scripts.annotate.run import AnnotationError, annotate_all, annotate_image
from scripts.annotate.schema import JSON_SCHEMA, AnnotatedRow, AnnotatedServing, Annotation

ANSWER = {
    "serving": {"serving_size": 2, "dose_unit": "capsule"},
    "rows": [
        {
            "raw_name": "維生素D",
            "per_serving": 10,
            "unit": "ug",
            "percent_dv": 100,
            "stated_elemental_amount": None,
            "label_section": "nutrition_table",
        }
    ],
}


class FakeRunner:
    """記下每次呼叫的指令、工作目錄內容與 stdin，並模擬兩個工具的輸出方式。"""

    def __init__(self, answer: dict | None = None, returncode: int = 0, claude_envelope: dict | None = None):
        self.answer = answer if answer is not None else ANSWER
        self.returncode = returncode
        self.claude_envelope = claude_envelope
        self.calls: list[dict] = []

    def __call__(self, cmd: list[str], cwd: Path, stdin: str) -> subprocess.CompletedProcess:
        self.calls.append({"cmd": cmd, "cwd": cwd, "files": sorted(p.name for p in cwd.iterdir()), "stdin": stdin})
        stdout = ""
        if cmd[0] == "claude":
            envelope = self.claude_envelope or {
                "type": "result",
                "is_error": False,
                "result": "",
                "structured_output": self.answer,
                "modelUsage": {"claude-test-model": {"inputTokens": 1}},
            }
            stdout = json.dumps(envelope, ensure_ascii=False)
        elif self.returncode == 0:
            output = Path(cmd[cmd.index("--output-last-message") + 1])
            output.write_text(json.dumps(self.answer, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=stdout, stderr="boom")


@pytest.fixture
def photo(tmp_path) -> Path:
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "p01-img01.jpg").write_bytes(b"fake-jpeg")  # 標註工具只複製檔案，不解碼影像
    (folder / "gold-answer.json").write_text("{}", encoding="utf-8")  # 同資料夾的其他檔案不可被帶進去
    return folder / "p01-img01.jpg"


# ── 隔離 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_工作目錄裡只有這一張照片(photo, annotator):
    runner = FakeRunner()
    annotate_image(photo, annotator, "m", runner)
    assert runner.calls[0]["files"] == ["p01-img01.jpg"]


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_工作目錄不在照片原本的資料夾裡(photo, annotator):
    runner = FakeRunner()
    annotate_image(photo, annotator, "m", runner)
    assert photo.parent not in runner.calls[0]["cwd"].parents
    assert runner.calls[0]["cwd"] != photo.parent


def test_兩個標註者各自使用不同的工作目錄(photo):
    runner = FakeRunner()
    annotate_image(photo, "claude", "m", runner)
    annotate_image(photo, "codex", "m", runner)
    assert runner.calls[0]["cwd"] != runner.calls[1]["cwd"]


def test_claude只開放讀檔工具且不載入MCP(photo):
    runner = FakeRunner()
    annotate_image(photo, "claude", "m", runner)
    cmd = runner.calls[0]["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert "--strict-mcp-config" in cmd
    assert "--restricted" in cmd  # 讀檔範圍鎖在工作目錄內


def test_codex使用唯讀沙盒並附上照片(photo):
    runner = FakeRunner()
    annotate_image(photo, "codex", "m", runner)
    cmd = runner.calls[0]["cmd"]
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert Path(cmd[cmd.index("--image") + 1]).name == "p01-img01.jpg"


def test_codex的結構檔不放在工作目錄裡(photo):
    runner = FakeRunner()
    annotate_image(photo, "codex", "m", runner)
    cmd = runner.calls[0]["cmd"]
    assert Path(cmd[cmd.index("--output-schema") + 1]).parent != runner.calls[0]["cwd"]


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_指定的模型傳給工具(photo, annotator):
    runner = FakeRunner()
    annotate_image(photo, annotator, "model-x", runner)
    cmd = runner.calls[0]["cmd"]
    assert cmd[cmd.index("--model") + 1] == "model-x"


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_提示詞由stdin傳入並指名照片檔(photo, annotator):
    runner = FakeRunner()
    annotate_image(photo, annotator, "m", runner)
    assert "p01-img01.jpg" in runner.calls[0]["stdin"]


# ── 輸出 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_標註結果通過結構驗證並記錄照片與模型(photo, annotator):
    record = annotate_image(photo, annotator, "model-x", FakeRunner())
    assert (record.image_id, record.annotator, record.model) == ("p01-img01", annotator, "model-x")
    assert record.annotation.rows[0].raw_name == "維生素D"


def test_記錄claude回報實際使用的模型(photo):
    assert annotate_image(photo, "claude", "m", FakeRunner()).models_reported == ["claude-test-model"]


def test_claude沒有structured_output時改讀result文字(photo):
    envelope = {"is_error": False, "result": json.dumps(ANSWER, ensure_ascii=False)}
    record = annotate_image(photo, "claude", "m", FakeRunner(claude_envelope=envelope))
    assert record.annotation.serving.serving_size == 2


def test_claude回報錯誤時拋出標註錯誤(photo):
    with pytest.raises(AnnotationError, match="回報錯誤"):
        annotate_image(photo, "claude", "m", FakeRunner(claude_envelope={"is_error": True, "result": "額度用完"}))


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_結束碼非零時拋出標註錯誤(photo, annotator):
    with pytest.raises(AnnotationError, match="結束碼"):
        annotate_image(photo, annotator, "m", FakeRunner(returncode=1))


@pytest.mark.parametrize("annotator", ["claude", "codex"])
def test_輸出不符結構時拋出標註錯誤(photo, annotator):
    with pytest.raises(AnnotationError, match="不符結構"):
        annotate_image(photo, annotator, "m", FakeRunner(answer={"rows": "沒有"}))


def test_結構檔的欄位與標註模型一致():
    def check(schema: dict, model) -> None:
        assert set(schema["properties"]) == set(model.model_fields)
        assert set(schema["required"]) == set(model.model_fields)  # 結構化輸出要求每欄都必填
        assert schema["additionalProperties"] is False

    check(JSON_SCHEMA, Annotation)
    check(JSON_SCHEMA["properties"]["serving"], AnnotatedServing)
    check(JSON_SCHEMA["properties"]["rows"]["items"], AnnotatedRow)


# ── 批次 ───────────────────────────────────────────────────────────


def test_批次標註寫出兩份標註且可直接比對(photo, tmp_path):
    out = tmp_path / "annotations"
    failed = annotate_all([photo], out, {"claude": "m1", "codex": "m2"}, runner=FakeRunner())
    assert failed == []
    a, models_a = load_annotations(out / "claude", "claude")
    b, _ = load_annotations(out / "codex", "codex")
    assert models_a == {"m1"}
    assert compare(a, b).disagreements == []


def test_已標註的照片預設跳過(photo, tmp_path):
    out = tmp_path / "annotations"
    annotate_all([photo], out, {"claude": "m"}, runner=FakeRunner())
    runner = FakeRunner()
    annotate_all([photo], out, {"claude": "m"}, runner=runner)
    assert runner.calls == []


def test_一項失敗不影響其他項(photo, tmp_path):
    out = tmp_path / "annotations"
    failed = annotate_all([photo], out, {"claude": "m", "codex": "m"}, runner=FakeRunner(returncode=1))
    assert failed == ["claude:p01-img01", "codex:p01-img01"]


def test_標註放錯資料夾時讀取直接報錯(photo, tmp_path):
    out = tmp_path / "annotations"
    annotate_all([photo], out, {"claude": "m"}, runner=FakeRunner())
    (out / "codex").mkdir()
    (out / "claude" / "p01-img01.json").rename(out / "codex" / "p01-img01.json")
    with pytest.raises(ValueError, match="不應放在 codex"):
        load_annotations(out / "codex", "codex")

