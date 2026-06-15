"""Excel loading and attribute group resolution."""

from __future__ import annotations

from typing import Any

import pandas as pd
import yaml

from config_dashboard import ATTRIBUTE_GROUPS_PATH, GROUP_DISPLAY_NAMES, STYLECODE_COLUMN
from brand_filter import filter_brand_column
from stylecode_utils import get_row_votes, normalize_stylecode
from review_checks import all_attributes_reviewed, is_attribute_reviewed

__all__ = [
    "all_group_keys",
    "count_unreviewed_rows",
    "filter_by_attribute_values",
    "filter_row_indices",
    "find_next_unreviewed_index",
    "format_cell_value",
    "get_row_by_index",
    "get_stylecode",
    "group_display_name",
    "is_empty_value",
    "jump_label",
    "load_attribute_groups",
    "primary_brand_column",
    "resolve_group_columns",
    "resolve_jump_query",
    "scorable_attributes",
    "unique_brand_values",
]


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
    return normalize_stylecode(row[STYLECODE_COLUMN])


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
        row_votes = get_row_votes(votes, stylecode)
        has_unreviewed = any(
            not is_attribute_reviewed(row_votes, attr) for attr in attributes
        )
        if has_unreviewed:
            filtered.append(idx)
    return filtered


def count_unreviewed_rows(
    df: pd.DataFrame,
    votes: dict,
    attributes: list[str],
) -> int:
    if not attributes:
        return len(df)
    count = 0
    for idx in range(len(df)):
        stylecode = get_stylecode(df.iloc[idx])
        if not all_attributes_reviewed(votes, stylecode, attributes):
            count += 1
    return count


def find_next_unreviewed_index(
    df: pd.DataFrame,
    start_idx: int,
    votes: dict,
    attributes: list[str],
) -> int | None:
    if not attributes:
        return None
    for idx in range(max(0, start_idx), len(df)):
        stylecode = get_stylecode(df.iloc[idx])
        if not all_attributes_reviewed(votes, stylecode, attributes):
            return idx
    return None


def resolve_jump_query(df: pd.DataFrame, query: str) -> list[int]:
    """Return dataframe row indices matching a row number or StyleCode substring."""
    text = query.strip()
    if not text:
        return []

    if text.startswith("#"):
        text = text[1:].strip()

    if text.isdigit():
        row_num = int(text)
        if 1 <= row_num <= len(df):
            return [row_num - 1]
        return []

    needle = text.lower()
    return [i for i in range(len(df)) if needle in get_stylecode(df.iloc[i]).lower()]


def jump_label(df: pd.DataFrame, row_idx: int) -> str:
    return f"{row_idx + 1:04d} — {get_stylecode(df.iloc[row_idx])}"


def primary_brand_column(resolved_group: dict[str, list[str]]) -> str | None:
    brand_cols = resolved_group.get("brand_columns", [])
    return brand_cols[0] if brand_cols else None


def unique_brand_values(df: pd.DataFrame, brand_col: str) -> list[str]:
    if brand_col not in df.columns:
        return []
    values = df[brand_col].map(format_cell_value)
    return sorted({v for v in values if v != "—"}, key=str.lower)


def filter_by_attribute_values(
    df: pd.DataFrame,
    row_indices: list[int],
    resolved_groups: dict[str, dict[str, list[str]]],
    filters: dict[str, list[str]],
) -> list[int]:
    """Keep rows whose primary brand column value is in the selected filter values (AND across groups)."""
    active = {k: v for k, v in filters.items() if v}
    if not active:
        return row_indices

    filtered: list[int] = []
    for idx in row_indices:
        row = df.iloc[idx]
        matches = True
        for group_key, selected_values in active.items():
            group = resolved_groups.get(group_key, {})
            brand_col = filter_brand_column(group_key, group.get("brand_columns", []))
            if not brand_col:
                matches = False
                break
            cell_val = format_cell_value(row.get(brand_col))
            if cell_val not in selected_values:
                matches = False
                break
        if matches:
            filtered.append(idx)
    return filtered
