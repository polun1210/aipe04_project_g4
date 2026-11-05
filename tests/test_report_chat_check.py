"""對話回答的檢查：每條規則一個「必須擋」、一個「不可誤擋」。"""

import pytest

from app.narration_check import text_violations

ALLOWED = {35.0, 62.0, 62.5}


def _kinds(text: str) -> set[str]:
    return {v.split("：")[0] for v in text_violations(text, ALLOWED)}


# 數字
def test_number_not_in_report_is_blocked():
    assert "數字" in _kinds("你每天吃 500 顆")


def test_number_in_report_is_allowed():
    assert text_violations("鎂的上限是 35，目前約 62.5%", ALLOWED) == []


@pytest.mark.parametrize("text", ["維生素 B6 與維生素 D3", "Omega-3 與 COX-2", "維生素 B12"])
def test_digits_inside_names_are_not_numbers(text):
    assert text_violations(text, ALLOWED) == []


# 劑量
def test_dose_not_in_report_is_blocked():
    assert "劑量" in _kinds("可以吃 500 mg")
    assert "劑量" in _kinds("可以吃 7 毫克")


def test_dose_in_report_is_allowed():
    assert text_violations("上限 35 mg，也就是 35 毫克", ALLOWED) == []


@pytest.mark.parametrize("text", ["看第 7 圖", "7 克服", "7 gold", "7 mgx"])
def test_unit_lookalikes_are_not_doses(text):
    assert "劑量" not in _kinds(text)


# 建議
@pytest.mark.parametrize("word", ["停藥", "停用", "減量", "改吃", "換成"])
def test_stop_or_switch_advice_is_blocked(word):
    assert "建議" in _kinds(f"你可以{word}這個產品")


def test_referral_sentence_is_allowed():
    assert text_violations("這個問題請詢問醫師或藥師。", ALLOWED) == []


# 禁用詞
@pytest.mark.parametrize("phrase", ["安全", "可放心", "沒有交互作用"])
def test_banned_phrases_are_blocked(phrase):
    assert "禁用詞" in _kinds(f"這樣{phrase}")


def test_unrelated_words_do_not_trigger_banned_phrases():
    assert text_violations("魚油超過上限，建議問藥師。", ALLOWED) == []


# 強烈字眼
@pytest.mark.parametrize("word", ["立即", "緊急", "危險", "嚴重"])
def test_strong_words_are_blocked(word):
    assert "強烈字眼" in _kinds(f"{word}處理")


def test_calm_wording_is_allowed():
    assert text_violations("這項需要請你詢問醫師或藥師。", ALLOWED) == []
