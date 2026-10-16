"""Unicode 15.1 extended-grapheme counting for provisional text limits."""

from __future__ import annotations

from ._unicode_grapheme_data import (
    _CONTROL_RANGES,
    _EXTEND_RANGES,
    _EXTENDED_PICTOGRAPHIC_RANGES,
    _INCB_CONSONANT_RANGES,
    _INCB_EXTEND_RANGES,
    _INCB_LINKER_RANGES,
    _PREPEND_RANGES,
    _SPACINGMARK_RANGES,
    UNICODE_VERSION,
)


def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    low = 0
    high = len(ranges)
    while low < high:
        middle = (low + high) // 2
        start, end = ranges[middle]
        if codepoint < start:
            high = middle
        elif codepoint > end:
            low = middle + 1
        else:
            return True
    return False


def _hangul_class(codepoint: int) -> str | None:
    if 0x1100 <= codepoint <= 0x115F or 0xA960 <= codepoint <= 0xA97C:
        return "L"
    if 0x1160 <= codepoint <= 0x11A7 or 0xD7B0 <= codepoint <= 0xD7C6:
        return "V"
    if 0x11A8 <= codepoint <= 0x11FF or 0xD7CB <= codepoint <= 0xD7FB:
        return "T"
    if 0xAC00 <= codepoint <= 0xD7A3:
        return "LV" if (codepoint - 0xAC00) % 28 == 0 else "LVT"
    return None


def _grapheme_break_class(codepoint: int) -> str:
    if codepoint == 0x000D:
        return "CR"
    if codepoint == 0x000A:
        return "LF"
    if codepoint == 0x200D:
        return "ZWJ"
    if 0x1F1E6 <= codepoint <= 0x1F1FF:
        return "Regional_Indicator"
    if hangul := _hangul_class(codepoint):
        return hangul
    for name, ranges in (
        ("Prepend", _PREPEND_RANGES),
        ("Control", _CONTROL_RANGES),
        ("Extend", _EXTEND_RANGES),
        ("SpacingMark", _SPACINGMARK_RANGES),
    ):
        if _in_ranges(codepoint, ranges):
            return name
    return "Other"


def _indic_class(codepoint: int) -> str:
    for name, ranges in (
        ("Linker", _INCB_LINKER_RANGES),
        ("Consonant", _INCB_CONSONANT_RANGES),
        ("Extend", _INCB_EXTEND_RANGES),
    ):
        if _in_ranges(codepoint, ranges):
            return name
    return "None"


def _indic_conjunct_joins(
    history: list[tuple[str, str, bool]], current_indic: str
) -> bool:
    if current_indic != "Consonant":
        return False
    saw_linker = False
    for _, indic, _ in reversed(history):
        if indic == "Linker":
            saw_linker = True
        elif indic != "Extend":
            return indic == "Consonant" and saw_linker
    return False


def _emoji_zwj_joins(
    history: list[tuple[str, str, bool]], current_pictographic: bool
) -> bool:
    if not current_pictographic or history[-1][0] != "ZWJ":
        return False
    index = len(history) - 2
    while index >= 0 and history[index][0] == "Extend":
        index -= 1
    return index >= 0 and history[index][2]


def _regional_indicator_joins(history: list[tuple[str, str, bool]]) -> bool:
    run = 0
    for grapheme_class, _, _ in reversed(history):
        if grapheme_class != "Regional_Indicator":
            break
        run += 1
    return run % 2 == 1


def _joins(
    history: list[tuple[str, str, bool]],
    current: tuple[str, str, bool],
) -> bool:
    previous_class = history[-1][0]
    current_class, current_indic, current_pictographic = current
    if previous_class == "CR" and current_class == "LF":
        return True
    if previous_class in {"Control", "CR", "LF"}:
        return False
    if current_class in {"Control", "CR", "LF"}:
        return False
    if previous_class == "L" and current_class in {"L", "V", "LV", "LVT"}:
        return True
    if previous_class in {"LV", "V"} and current_class in {"V", "T"}:
        return True
    if previous_class in {"LVT", "T"} and current_class == "T":
        return True
    if current_class in {"Extend", "ZWJ", "SpacingMark"}:
        return True
    if previous_class == "Prepend":
        return True
    if _indic_conjunct_joins(history, current_indic):
        return True
    if _emoji_zwj_joins(history, current_pictographic):
        return True
    return current_class == "Regional_Indicator" and _regional_indicator_joins(history)


def grapheme_count(value: str) -> int:
    """Count Unicode 15.1 extended grapheme clusters according to UAX #29."""

    if not value:
        return 0
    history: list[tuple[str, str, bool]] = []
    count = 0
    for character in value:
        codepoint = ord(character)
        current = (
            _grapheme_break_class(codepoint),
            _indic_class(codepoint),
            _in_ranges(codepoint, _EXTENDED_PICTOGRAPHIC_RANGES),
        )
        if not history or not _joins(history, current):
            count += 1
            history = [current]
        else:
            history.append(current)
    return count


__all__ = ["UNICODE_VERSION", "grapheme_count"]
