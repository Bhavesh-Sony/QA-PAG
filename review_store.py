"""Persist and export human review votes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config_dashboard import DATA_DIR
from stylecode_utils import get_row_votes, normalize_stylecode
from review_checks import all_attributes_reviewed, is_attribute_reviewed


def normalize_votes_keys(votes: dict[str, dict[str, dict[str, str]]]) -> dict[str, dict[str, dict[str, str]]]:
    """Merge vote entries under canonical StyleCode keys."""
    normalized: dict[str, dict[str, dict[str, str]]] = {}
    for stylecode, attr_votes in votes.items():
        key = normalize_stylecode(stylecode)
        if not key:
            continue
        if key not in normalized:
            normalized[key] = {}
        normalized[key].update(attr_votes)
    return normalized


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def default_reviews_path(session_id: str) -> Path:
    return ensure_data_dir() / f"reviews_{session_id}.json"


def load_reviews(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"votes": {}, "metadata": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "votes" not in data:
        data["votes"] = {}
    if "metadata" not in data:
        data["metadata"] = {}
    data["votes"] = normalize_votes_keys(data.get("votes", {}))
    return data


def save_reviews(path: Path, votes: dict[str, dict[str, dict[str, str]]], metadata: dict[str, Any]) -> None:
    ensure_data_dir()
    payload = {
        "votes": votes,
        "metadata": metadata,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def record_vote(
    votes: dict[str, dict[str, dict[str, str]]],
    stylecode: str,
    attribute: str,
    vote: str,
    note: str = "",
) -> None:
    key = normalize_stylecode(stylecode)
    if key not in votes:
        votes[key] = {}
    votes[key][attribute] = {
        "vote": vote,
        "note": note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_vote(votes: dict[str, dict[str, dict[str, str]]], stylecode: str, attribute: str) -> str | None:
    entry = get_row_votes(votes, stylecode).get(attribute)
    if not entry:
        return None
    return entry.get("vote")


def get_note(votes: dict[str, dict[str, dict[str, str]]], stylecode: str, attribute: str) -> str:
    entry = get_row_votes(votes, stylecode).get(attribute)
    if not entry:
        return ""
    return entry.get("note", "") or ""


def count_reviewed_for_attributes(
    votes: dict[str, dict[str, dict[str, str]]],
    stylecodes: list[str],
    attributes: list[str],
) -> int:
    if not attributes:
        return 0
    count = 0
    for stylecode in stylecodes:
        row_votes = get_row_votes(votes, stylecode)
        if all(is_attribute_reviewed(row_votes, attr) for attr in attributes):
            count += 1
    return count


def votes_to_dataframe(votes: dict[str, dict[str, dict[str, str]]]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for stylecode, attr_votes in votes.items():
        for attribute, entry in attr_votes.items():
            rows.append(
                {
                    "stylecode": stylecode,
                    "attribute": attribute,
                    "vote": entry.get("vote", ""),
                    "note": entry.get("note", ""),
                    "timestamp": entry.get("timestamp", ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["stylecode", "attribute", "vote", "note", "timestamp"])
    return pd.DataFrame(rows)
