"""StyleCode normalization and vote dict key lookup (no dashboard imports)."""

from typing import Any

__all__ = [
    "normalize_stylecode",
    "get_row_votes",
]


def normalize_stylecode(value: Any) -> str:
    """Canonical StyleCode string for vote keys and display."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        head = text[:-2]
        if head.isdigit() or (head.startswith("-") and head[1:].isdigit()):
            return head
    try:
        as_float = float(text)
        if as_float == int(as_float):
            return str(int(as_float))
    except ValueError:
        pass
    return text


def get_row_votes(
    votes: dict[str, dict[str, dict[str, str]]],
    stylecode: str,
) -> dict[str, dict[str, str]]:
    """Return votes for a stylecode, matching normalized or legacy keys."""
    key = normalize_stylecode(stylecode)
    if key in votes:
        return votes[key]
    for raw_key, row_votes in votes.items():
        if normalize_stylecode(raw_key) == key:
            return row_votes
    return {}
