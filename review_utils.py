"""Pure helpers for review completion checks (no dashboard imports)."""


def is_attribute_reviewed(row_votes: dict[str, dict[str, str]], attribute: str) -> bool:
    entry = row_votes.get(attribute)
    if not entry:
        return False
    return bool(entry.get("vote")) or bool(str(entry.get("note", "")).strip())


def all_attributes_reviewed(
    votes: dict[str, dict[str, dict[str, str]]],
    stylecode: str,
    attributes: list[str],
) -> bool:
    if not attributes:
        return False
    row_votes = votes.get(stylecode, {})
    return all(is_attribute_reviewed(row_votes, attr) for attr in attributes)
