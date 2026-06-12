"""Excel loading and attribute group resolution."""

from __future__ import annotations

from typing import Any

import pandas as pd
import yaml

from config_dashboard import ATTRIBUTE_GROUPS_PATH, GROUP_DISPLAY_NAMES, STYLECODE_COLUMN
from review_utils import is_attribute_reviewed


def load_attribute_groups() -> dict[str, dict[str, list[str]]]:
    with open(ATTRIBUTE_GROUPS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("groups", {})


def group_display_name(group_key: str) -> str:
    return GROUP_DISPLAY_NAMES.get(group_key, group_key.replace("_", " "))


def all_group_keys() -> list[str]:
    return list(load_attribute_groups().keys())


def get_row_by_index(df: pd.DataFrame, row_idx: int) -> pd.Series:
    row_idx = max(0, min(row_idx, len(df) - 1))
    return df.iloc[row_idx]


def get_stylecode(row: pd.Series) -> str:
    return str(row[STYLECODE_COLUMN])


def format_cell_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    text = str(value).strip()
    return text if text and text.lower() != "nan" else "—"


def is_empty_value(value: Any) -> bool:
    return format_cell_value(value) == "—"


def resolve_group_columns(
    groups_config: dict[str, dict[str, list[str]]],
    selected_groups: list[str],
    df_columns: list[str],
) -> dict[str, dict[str, list[str]]]:
    """Filter configured columns to those present in the dataframe."""
    column_set = set(df_columns)
    resolved: dict[str, dict[str, list[str]]] = {}

    for group_key in selected_groups:
        if group_key not in groups_config:
            continue
        cfg = groups_config[group_key]
        resolved[group_key] = {
            "brand_columns": [c for c in cfg.get("brand_columns", []) if c in column_set],
            "marketplace_columns": [
                c for c in cfg.get("marketplace_columns", []) if c in column_set
            ],
        }
    return resolved


def scorable_attributes(resolved_groups: dict[str, dict[str, list[str]]]) -> list[str]:
    """Return group keys — one review widget per attribute group."""
    return list(resolved_groups.keys())


def filter_row_indices(
    df: pd.DataFrame,
    row_indices: list[int],
    votes: dict[str, dict[str, str]],
    attributes: list[str],
    only_unreviewed: bool,
) -> list[int]:
    if not only_unreviewed or not attributes:
        return row_indices

    filtered: list[int] = []
    for idx in row_indices:
        row = df.iloc[idx]
        stylecode = get_stylecode(row)
        row_votes = votes.get(stylecode, {})
        has_unreviewed = any(
            not is_attribute_reviewed(row_votes, attr) for attr in attributes
        )
        if has_unreviewed:
            filtered.append(idx)
    return filtered or row_indices
