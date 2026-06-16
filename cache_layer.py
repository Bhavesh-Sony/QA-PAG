"""Centralized Streamlit cache helpers for dashboard performance."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pandas as pd
import streamlit as st
import yaml

from config_dashboard import ATTRIBUTE_GROUPS_PATH, IMAGE_COLUMN_CANDIDATES, STYLES_PATH, STYLECODE_COLUMN
from data_loader import filter_by_attribute_values, format_cell_value, resolve_group_columns, resolve_image_url

PROFILE_ENABLED = os.environ.get("DASHBOARD_PROFILE", "").strip() in ("1", "true", "yes")


@contextmanager
def timed(label: str) -> Iterator[None]:
    """Log elapsed milliseconds when DASHBOARD_PROFILE=1."""
    if not PROFILE_ENABLED:
        yield
        return
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    log = st.session_state.setdefault("_profile_log", [])
    log.append(f"{label}: {elapsed_ms:.2f}ms")
    if len(log) > 50:
        st.session_state._profile_log = log[-50:]


def render_profile_sidebar() -> None:
    if not PROFILE_ENABLED:
        return
    log = st.session_state.get("_profile_log", [])
    if log:
        st.sidebar.caption("**Profile (last runs)**")
        for entry in reversed(log[-8:]):
            st.sidebar.caption(entry)


@st.cache_data(show_spinner=False)
def load_attribute_groups_cached() -> dict[str, dict[str, list[str]]]:
    with open(ATTRIBUTE_GROUPS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("groups", {})


@st.cache_data(show_spinner=False)
def load_css_cached() -> str:
    if STYLES_PATH.exists():
        return STYLES_PATH.read_text(encoding="utf-8")
    return ""


@st.cache_data(show_spinner=False)
def file_digest_cached(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


@st.cache_data(show_spinner=False)
def stylecodes_for_df(digest: str, df: pd.DataFrame) -> tuple[str, ...]:
    return tuple(df[STYLECODE_COLUMN].tolist())


@st.cache_data(show_spinner=False)
def unique_brand_values_cached(digest: str, df: pd.DataFrame, col: str) -> tuple[str, ...]:
    if col not in df.columns:
        return ()
    values = df[col].map(format_cell_value)
    return tuple(sorted({v for v in values if v != "—"}, key=str.lower))


@st.cache_data(show_spinner=False)
def nav_indices_cached(
    digest: str,
    df: pd.DataFrame,
    filter_sig: str,
    resolved_sig: str,
) -> tuple[int, ...]:
    filters = json.loads(filter_sig) if filter_sig else {}
    resolved = json.loads(resolved_sig) if resolved_sig else {}
    indices = filter_by_attribute_values(
        df,
        list(range(len(df))),
        resolved,
        filters,
    )
    return tuple(indices)


@st.cache_data(show_spinner=False)
def image_urls_for_rows(
    digest: str,
    df: pd.DataFrame,
    row_indices: tuple[int, ...],
    image_labels: tuple[str, ...],
) -> dict[int, dict[str, str | None]]:
    result: dict[int, dict[str, str | None]] = {}
    for idx in row_indices:
        if idx < 0 or idx >= len(df):
            continue
        row = df.iloc[idx]
        result[idx] = {}
        for label in image_labels:
            candidates = IMAGE_COLUMN_CANDIDATES.get(label, [])
            result[idx][label] = resolve_image_url(row, candidates)
    return result


def resolved_groups_signature(
    groups_config: dict[str, dict[str, list[str]]],
    selected_groups: list[str],
    df_columns: list[str],
) -> str:
    resolved = resolve_group_columns(groups_config, selected_groups, df_columns)
    return json.dumps(resolved, sort_keys=True)


def build_nav_bundle(
    df: pd.DataFrame,
    digest: str,
    nav_indices: list[int],
    group_keys: list[str],
    image_labels: list[str],
    votes: dict,
) -> dict[str, Any]:
    """Precompute navigation lookups and review counts."""
    from review_checks import all_attributes_reviewed
    from review_store import count_reviewed_for_attributes

    all_stylecodes = stylecodes_for_df(digest, df)
    nav_stylecodes = [all_stylecodes[i] for i in nav_indices]

    image_labels_tuple = tuple(image_labels)
    image_urls = image_urls_for_rows(digest, df, tuple(nav_indices), image_labels_tuple)

    reviewed_count = (
        count_reviewed_for_attributes(votes, nav_stylecodes, group_keys) if group_keys else 0
    )
    unreviewed_count = (
        sum(
            1
            for sc in nav_stylecodes
            if not all_attributes_reviewed(votes, sc, group_keys)
        )
        if group_keys
        else len(nav_indices)
    )

    return {
        "indices": nav_indices,
        "stylecodes": nav_stylecodes,
        "reviewed_count": reviewed_count,
        "unreviewed_count": unreviewed_count,
        "image_urls": image_urls,
        "all_stylecodes": all_stylecodes,
        "digest": digest,
        "group_keys": list(group_keys),
        "image_labels": list(image_labels),
    }


def nav_bundle_signature(
    digest: str,
    filter_sig: str,
    resolved_sig: str,
    group_keys: list[str],
    image_labels: list[str],
) -> str:
    return json.dumps(
        {
            "digest": digest,
            "filter_sig": filter_sig,
            "resolved_sig": resolved_sig,
            "group_keys": group_keys,
            "image_labels": image_labels,
        },
        sort_keys=True,
    )
