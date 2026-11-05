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


def test_list_numbering_at_line_start_is_not_a_number():
    assert text_violations("1. 鎂超過上限\n2、鈣未超過\n3) 請詢問藥師", ALLOWED) == []


def test_real_number_inside_a_list_item_is_still_blocked():
    assert "數字" in _kinds("1. 你每天吃 500 顆")
    assert "數字" in _kinds("共有 3 項需要注意")  # 不在行首，不是編號


def test_second_number_of_a_range_is_checked():
    assert "劑量" in _kinds("每天可吃 35-1000 mg")  # 35 在報告裡，1000 不在
    assert "劑量" in _kinds("每天 35～1000 mg")


def test_hyphen_in_names_still_not_a_number():
    assert text_violations("COX-2 與 Omega-3", ALLOWED) == []


@pytest.mark.parametrize("word", ["暫停服用", "不要吃魚油", "別吃", "不建議服用", "避免服用", "調整劑量", "增加劑量"])
def test_other_stop_or_dose_wording_is_blocked(word):
    assert "建議" in _kinds(f"你可以{word}")


def test_unrelated_not_wording_is_allowed():
    assert text_violations("不要擔心，請詢問醫師或藥師", ALLOWED) == []


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


def test_decimal_at_line_start_is_not_a_list_marker():
    # 報告允許 35，但 1.35 不在報告裡；行首小數不能被當成編號而把 1. 吃掉
    assert "劑量" in _kinds("1.35 mg 可以服用")
    assert "數字" in _kinds("1.35 可以服用")


@pytest.mark.parametrize("word", ["停止用藥", "停止服藥", "暫停用藥", "暫停服藥", "不要服藥", "不要用藥", "不要吃藥", "停吃", "不要再服用", "調整用量"])
def test_more_stop_medication_wording_is_blocked(word):
    assert "建議" in _kinds(f"請{word}並詢問醫師")


def test_near_miss_wording_is_allowed():
    # 含「用量」「服用」但不是停藥／改量建議
    assert text_violations("報告列出各產品的每日用量與服用時間，請詢問醫師或藥師", ALLOWED) == []
