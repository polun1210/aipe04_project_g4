"""比對文字前的正規化（D07 的前兩步）。只用來「比對」，不可拿來改寫標示原文。"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PARENTHETICAL = re.compile(r"\([^()]*\)")


def compact(text: str) -> str:
    """全形轉半形（NFKC）並去掉所有空白。「維生素 Ｄ３」→「維生素D3」，「µg」→「μg」。"""
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", text))


def strip_parenthetical(text: str) -> str:
    """compact 後再去掉括號與括號內的字。「檸檬酸鈣（含純鈣50mg）」→「檸檬酸鈣」。"""
    stripped = compact(text)
    while True:  # 由內而外處理巢狀括號
        reduced = _PARENTHETICAL.sub("", stripped)
        if reduced == stripped:
            return reduced
        stripped = reduced
