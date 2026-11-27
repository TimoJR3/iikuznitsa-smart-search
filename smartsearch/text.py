"""Нормализация текста: регистр, ё, раскладка, транслитерация, токены и простой стемминг."""

from __future__ import annotations

import re

_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
_RU = "йцукенгшщзхъфывапролджэячсмитьбюё"
EN2RU = str.maketrans(_EN, _RU)
RU2EN = str.maketrans(_RU, _EN)

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}

_TOKEN = re.compile(r"[a-zа-я0-9]+(?:[.\-+][a-zа-я0-9]+)*")
_CYR = re.compile(r"[а-я]")
_LAT = re.compile(r"[a-z]")

# Окончания русских слов, отрезаемые при стемминге (от длинных к коротким).
_ENDINGS = sorted(
    "ами ями ого его ому ему ыми ими ой ей ий ый ая яя ое ее ые ие ую юю ов ев ам ям ах ях ом ем "
    "ия ию ии ья ье ьи а я о е и ы у ю ь".split(),
    key=len, reverse=True,
)

STOP = {"и", "в", "на", "для", "с", "по", "к", "от", "до", "из", "или", "the", "for", "and", "of", "шт", "лицензия",
        "лицензии", "лицензий", "система", "системы", "систем"}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е").replace("&amp;", "&").replace("®", " ").replace("™", " ")
    text = re.sub(r"[«»\"'“”„()\[\]{}:;!?/\\|,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def stem(tok: str) -> str:
    if _CYR.search(tok) and len(tok) > 4:
        for end in _ENDINGS:
            if tok.endswith(end) and len(tok) - len(end) >= 4:
                return tok[: -len(end)]
    return tok


def stems(text: str, drop_stop: bool = True) -> list[str]:
    return [stem(t) for t in tokens(text) if not (drop_stop and t in STOP)]


def switch_layout(text: str) -> str:
    """Исправляет ввод в неверной раскладке: 'fcnhf' -> 'астра', 'щаашсу' -> 'office'."""
    low = text.lower()
    if _LAT.search(low) and not _CYR.search(low):
        return low.translate(EN2RU)
    if _CYR.search(low) and not _LAT.search(low):
        return low.translate(RU2EN)
    return low


def translit(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def has_cyr(text: str) -> bool:
    return bool(_CYR.search(text.lower()))
