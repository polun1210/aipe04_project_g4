import json
from pathlib import Path

import scripts.compare_narrators as cmp
from app.schemas.assessment import Assessment

EXAMPLE = Path(__file__).parent.parent / "docs" / "schemas" / "examples" / "06_assessment.json"


def _fake_http_transport(good: bool):
    assessment = Assessment.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    summary = "請先看紅麴這一條。" if good else "這樣很安全。"
    items = [{"kind": "summary", "ingredient_code": None, "text": summary}]
    items += [{"kind": "interaction", "ingredient_code": f.ingredient_code, "text": "請留意。"} for f in assessment.interactions]
    content = json.dumps({"items": items}, ensure_ascii=False)

    def factory(api_key):
        def send(body, timeout):
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.001}}

        return send

    return factory


def test_compare_writes_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(cmp, "load_dotenv", lambda: None)
    monkeypatch.setattr(cmp, "http_transport", _fake_http_transport(good=True))
    assert cmp.main(["--model", "vendor/a@p", "--model", "vendor/b@p", "--runs", "2", "--out", str(tmp_path)]) == 0

    stats = (tmp_path / "stats.md").read_text(encoding="utf-8")
    assert "| vendor/a | 2 | 100% | 0% |" in stats
    assert "| vendor/b | 2 | 100% | 0% |" in stats
    assert len((tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_compare_counts_fallback_when_check_never_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(cmp, "load_dotenv", lambda: None)
    monkeypatch.setattr(cmp, "http_transport", _fake_http_transport(good=False))
    assert cmp.main(["--model", "vendor/a@p", "--runs", "1", "--out", str(tmp_path)]) == 0
    assert "| vendor/a | 1 | 0% | 100% |" in (tmp_path / "stats.md").read_text(encoding="utf-8")
