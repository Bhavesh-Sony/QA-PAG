"""Streamlit Attribute Review Dashboard."""

from __future__ import annotations

import hashlib
import uuid

import streamlit as st
import streamlit.components.v1 as components

from config_dashboard import (
    DEFAULT_SELECTED_GROUPS,
    DEFAULT_SELECTED_IMAGES,
    IMAGE_OPTIONS,
    PREFETCH_WINDOW,
    STYLES_PATH,
)
from review_utils import all_attributes_reviewed, is_attribute_reviewed
from review_store import (
    count_reviewed_for_attributes,
    default_reviews_path,
    get_note,
    get_vote,
    load_reviews,
    record_vote,
    save_reviews,
    votes_to_dataframe,
)
from data_loader import (
    all_group_keys,
    filter_row_indices,
    format_cell_value,
    get_row_by_index,
    get_stylecode,
    group_display_name,
    load_attribute_groups,
    resolve_group_columns,
)
from excel_io import read_excel_bytes
from image_cache import get_image_cache, prefetch_window, render_image_panel
from analytics import render_analytics_tab


def load_css() -> None:
    if STYLES_PATH.exists():
        st.markdown(f"<style>{STYLES_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def init_session_state() -> None:
    defaults = {
        "session_id": str(uuid.uuid4())[:8],
        "row_idx": 0,
        "selected_images": list(DEFAULT_SELECTED_IMAGES),
        "selected_groups": list(DEFAULT_SELECTED_GROUPS),
        "votes": {},
        "reviewer_name": "",
        "only_unreviewed": False,
        "uploaded_bytes": None,
        "reviews_loaded": False,
        "confirm_reset": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "group_multiselect" not in st.session_state:
        st.session_state.group_multiselect = []
    if not st.session_state.get("_empty_groups_default"):
        st.session_state.selected_groups = []
        st.session_state.group_multiselect = []
        st.session_state._empty_groups_default = True


def load_persisted_reviews() -> None:
    if st.session_state.reviews_loaded:
        return
    path = default_reviews_path(st.session_state.session_id)
    data = load_reviews(path)
    st.session_state.votes = data.get("votes", {})
    reviewer = data.get("metadata", {}).get("reviewer_name")
    if reviewer and not st.session_state.reviewer_name:
        st.session_state.reviewer_name = reviewer
    st.session_state.reviews_loaded = True


def persist_reviews() -> None:
    path = default_reviews_path(st.session_state.session_id)
    metadata = {
        "reviewer_name": st.session_state.reviewer_name,
        "session_id": st.session_state.session_id,
    }
    save_reviews(path, st.session_state.votes, metadata)


def load_dataframe():
    file_bytes = st.session_state.uploaded_bytes
    if file_bytes is None:
        raise FileNotFoundError("No Excel file loaded. Upload a file in the sidebar.")
    digest = hashlib.sha256(file_bytes).hexdigest()
    return read_excel_bytes(digest, file_bytes)


def reviewable_group_keys(
    selected_groups: list[str],
    resolved_groups: dict[str, dict[str, list[str]]],
) -> list[str]:
    return [g for g in selected_groups if g in resolved_groups]


def count_groups_reviewed_on_row(
    votes: dict,
    stylecode: str,
    group_keys: list[str],
) -> int:
    row_votes = votes.get(stylecode, {})
    return sum(1 for g in group_keys if is_attribute_reviewed(row_votes, g))


def note_input_key(stylecode: str, group_key: str) -> str:
    return f"note_{stylecode}_{group_key}"


def on_prev(stylecodes: list[str]) -> None:
    st.session_state.row_idx = max(0, st.session_state.row_idx - 1)
    sync_stylecode_selector(stylecodes)


def on_next(max_idx: int, stylecodes: list[str]) -> None:
    st.session_state.row_idx = min(max_idx, st.session_state.row_idx + 1)
    sync_stylecode_selector(stylecodes)


def advance_row(max_idx: int, only_unreviewed: bool = False) -> None:
    if max_idx < 0:
        return
    if only_unreviewed:
        st.session_state.row_idx = min(st.session_state.row_idx, max_idx)
    else:
        st.session_state.row_idx = min(max_idx, st.session_state.row_idx + 1)


def sync_stylecode_selector(stylecodes: list[str]) -> None:
    """Keep jump selectbox aligned with row_idx after programmatic navigation."""
    if not stylecodes:
        return
    idx = min(max(st.session_state.row_idx, 0), len(stylecodes) - 1)
    st.session_state._jump_sync_programmatic = True
    st.session_state.jump_stylecode = stylecodes[idx]


def ensure_stylecode_selector(stylecodes: list[str]) -> None:
    """Initialize jump selectbox when missing or out of sync with row_idx."""
    if not stylecodes:
        return
    idx = min(max(st.session_state.row_idx, 0), len(stylecodes) - 1)
    expected = stylecodes[idx]
    current = st.session_state.get("jump_stylecode")
    if current not in stylecodes or current != expected:
        sync_stylecode_selector(stylecodes)


def on_note_saved(
    stylecode: str,
    group_key: str,
    df,
    group_keys: list[str],
) -> None:
    key = note_input_key(stylecode, group_key)
    note_val = str(st.session_state.get(key, "")).strip()
    if not note_val:
        return
    vote = get_vote(st.session_state.votes, stylecode, group_key) or ""
    record_vote(
        st.session_state.votes,
        stylecode,
        group_key,
        vote,
        note=note_val,
    )
    persist_reviews()
    _advance_after_review(df, group_keys, stylecode)


def on_vote_click(
    stylecode: str,
    group_key: str,
    vote: str,
    df,
    group_keys: list[str],
) -> None:
    key = note_input_key(stylecode, group_key)
    note = str(st.session_state.get(key, get_note(st.session_state.votes, stylecode, group_key)))
    record_vote(st.session_state.votes, stylecode, group_key, vote, note=note)
    persist_reviews()
    _advance_after_review(df, group_keys, stylecode)


def _advance_after_review(df, group_keys: list[str], stylecode: str) -> bool:
    if not all_attributes_reviewed(st.session_state.votes, stylecode, group_keys):
        return False

    only_unreviewed = st.session_state.only_unreviewed
    all_indices = list(range(len(df)))
    row_indices = filter_row_indices(
        df,
        all_indices,
        st.session_state.votes,
        group_keys,
        only_unreviewed,
    )
    max_idx = len(row_indices) - 1
    advance_row(max_idx, only_unreviewed=only_unreviewed)
    if row_indices:
        stylecodes = [get_stylecode(df.iloc[i]) for i in row_indices]
        sync_stylecode_selector(stylecodes)
    return True


def inject_keyboard_nav() -> None:
    """Bind left/right arrow keys to Previous/Next navigation buttons."""
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            if (doc._attrQaKeyNavBound) return;
            doc._attrQaKeyNavBound = true;
            doc.addEventListener("keydown", function (e) {
                if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
                const buttons = [...doc.querySelectorAll("button")];
                if (e.key === "ArrowLeft") {
                    const btn = buttons.find((b) => b.innerText.includes("Previous"));
                    if (btn && !btn.disabled) btn.click();
                }
                if (e.key === "ArrowRight") {
                    const btn = buttons.find((b) => b.innerText.includes("Next"));
                    if (btn && !btn.disabled) btn.click();
                }
            });
        })();
        </script>
        """,
        height=0,
    )


def render_sidebar() -> None:
    st.sidebar.header("Data source")
    uploaded = st.sidebar.file_uploader(
        "Upload Excel",
        type=["xlsx", "xls"],
        key="excel_uploader",
    )
    if uploaded is not None:
        st.session_state.uploaded_bytes = uploaded.getvalue()
    else:
        st.session_state.uploaded_bytes = None

    st.sidebar.header("Reviewer")
    st.session_state.reviewer_name = st.sidebar.text_input(
        "Your name (optional)",
        value=st.session_state.reviewer_name,
    )
    st.sidebar.caption(f"Session ID: `{st.session_state.session_id}`")

    if st.sidebar.button("New session (clear votes)", type="secondary"):
        st.session_state.session_id = str(uuid.uuid4())[:8]
        st.session_state.votes = {}
        st.session_state.reviews_loaded = False
        st.session_state.row_idx = 0
        st.rerun()


def render_review_tab(df, groups_config) -> None:
    cache = get_image_cache()

    st.markdown('<div class="sticky-controls-marker"></div>', unsafe_allow_html=True)
    c_img, c_attr, c_prog = st.columns([2, 3, 2])
    with c_img:
        st.session_state.selected_images = st.multiselect(
            "Images (up to 2)",
            options=list(IMAGE_OPTIONS.keys()),
            default=st.session_state.selected_images[:2],
            max_selections=2,
            key="image_multiselect",
        )
    with c_attr:
        group_labels = {group_display_name(k): k for k in all_group_keys()}
        label_to_key = {v: k for k, v in group_labels.items()}
        selected_labels = st.multiselect(
            "Attribute groups",
            options=list(group_labels.keys()),
            key="group_multiselect",
        )
        st.session_state.selected_groups = [label_to_key[l] for l in selected_labels if l in label_to_key]
        st.session_state.only_unreviewed = st.checkbox(
            "Show only unreviewed rows",
            value=st.session_state.only_unreviewed,
            key="only_unreviewed_checkbox",
        )

    resolved_groups = resolve_group_columns(
        groups_config,
        st.session_state.selected_groups,
        list(df.columns),
    )
    group_keys = reviewable_group_keys(st.session_state.selected_groups, resolved_groups)

    row_indices = list(range(len(df)))
    row_indices = filter_row_indices(
        df,
        row_indices,
        st.session_state.votes,
        group_keys,
        st.session_state.only_unreviewed,
    )

    if st.session_state.row_idx >= len(row_indices):
        st.session_state.row_idx = max(0, len(row_indices) - 1)

    current_list_idx = st.session_state.row_idx
    data_idx = row_indices[current_list_idx]
    row = get_row_by_index(df, data_idx)
    stylecode = get_stylecode(row)

    prefetch_window(
        df,
        data_idx,
        PREFETCH_WINDOW,
        IMAGE_OPTIONS,
        st.session_state.selected_images,
        cache,
    )

    with c_prog:
        reviewed = count_reviewed_for_attributes(
            st.session_state.votes,
            [get_stylecode(df.iloc[i]) for i in row_indices],
            group_keys,
        )
        groups_done = count_groups_reviewed_on_row(st.session_state.votes, stylecode, group_keys)
        groups_hint = ""
        if group_keys:
            groups_hint = (
                f'<br>Groups reviewed on this StyleCode: {groups_done} / {len(group_keys)}'
            )
        st.markdown(
            f'<p class="progress-text">Row {current_list_idx + 1} / {len(row_indices)}<br>'
            f"StyleCode: <strong>{stylecode}</strong><br>"
            f"Fully reviewed: {reviewed} / {len(row_indices)}{groups_hint}</p>",
            unsafe_allow_html=True,
        )
    st.markdown('<div class="sticky-controls-end"></div>', unsafe_allow_html=True)

    left_col, right_col = st.columns([7, 3])

    with left_col:
        st.markdown('<div class="image-panel-marker"></div>', unsafe_allow_html=True)
        urls_by_label: list[tuple[str, str | None]] = []
        for label in st.session_state.selected_images[:2]:
            col_name = IMAGE_OPTIONS.get(label)
            url = None
            if col_name and col_name in row.index:
                raw = row[col_name]
                if raw is not None and str(raw).strip().lower() not in ("", "nan"):
                    url = str(raw).strip()
            urls_by_label.append((label, url))

        def placeholder(msg: str) -> None:
            st.markdown(f'<div class="image-placeholder">{msg}</div>', unsafe_allow_html=True)

        def show_image(data: bytes) -> None:
            st.image(data, use_container_width=True)

        render_image_panel(urls_by_label, cache, placeholder, show_image)

    with right_col:
        st.markdown('<div class="attribute-panel-marker"></div>', unsafe_allow_html=True)
        if not group_keys:
            st.warning("Select at least one attribute group to review.")
        else:
            st.markdown(
                f'<p class="groups-reviewed-hint">'
                f"Groups reviewed: {count_groups_reviewed_on_row(st.session_state.votes, stylecode, group_keys)}"
                f" / {len(group_keys)}</p>",
                unsafe_allow_html=True,
            )
            for group_key in group_keys:
                group = resolved_groups[group_key]
                title = group_display_name(group_key)
                vote = get_vote(st.session_state.votes, stylecode, group_key)
                existing_note = get_note(st.session_state.votes, stylecode, group_key)

                card_class = "attr-card"
                if vote == "like":
                    card_class += " voted-like"
                elif vote == "dislike":
                    card_class += " voted-dislike"

                brand_lines = []
                for brand_col in group.get("brand_columns", []):
                    brand_val = format_cell_value(row.get(brand_col))
                    brand_lines.append(f"<div class='brand-value'>{brand_col}: {brand_val}</div>")

                mp_lines = []
                for mp_col in group.get("marketplace_columns", []):
                    mp_val = format_cell_value(row.get(mp_col))
                    mp_lines.append(f"<div class='marketplace-value'>{mp_col}: {mp_val}</div>")

                st.markdown(
                    f"<div class='{card_class}'>"
                    f"<h4>{title}</h4>"
                    f"{''.join(brand_lines)}"
                    f"{''.join(mp_lines)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                btn_like, btn_dislike = st.columns(2)
                with btn_like:
                    st.button(
                        "👍 Like",
                        key=f"like_{stylecode}_{group_key}",
                        use_container_width=True,
                        on_click=on_vote_click,
                        args=(stylecode, group_key, "like", df, group_keys),
                    )
                with btn_dislike:
                    st.button(
                        "👎 Dislike",
                        key=f"dislike_{stylecode}_{group_key}",
                        use_container_width=True,
                        on_click=on_vote_click,
                        args=(stylecode, group_key, "dislike", df, group_keys),
                    )

                st.text_input(
                    "Note",
                    value=existing_note,
                    key=note_input_key(stylecode, group_key),
                    label_visibility="collapsed",
                    placeholder="Optional note…",
                    on_change=on_note_saved,
                    args=(stylecode, group_key, df, group_keys),
                )

        stylecodes = [get_stylecode(df.iloc[i]) for i in row_indices]
        ensure_stylecode_selector(stylecodes)

        def _on_jump() -> None:
            if st.session_state.pop("_jump_sync_programmatic", False):
                return
            selected = st.session_state.jump_stylecode
            if selected in stylecodes:
                st.session_state.row_idx = stylecodes.index(selected)

        st.markdown('<div class="review-nav-divider"></div>', unsafe_allow_html=True)
        nav_prev, nav_next = st.columns(2)
        max_row_idx = len(row_indices) - 1
        with nav_prev:
            st.markdown('<div class="review-nav-marker"></div>', unsafe_allow_html=True)
            st.button(
                "← Previous",
                on_click=on_prev,
                args=(stylecodes,),
                disabled=current_list_idx <= 0,
                use_container_width=True,
            )
        with nav_next:
            st.button(
                "Next →",
                on_click=on_next,
                args=(max_row_idx, stylecodes),
                disabled=current_list_idx >= max_row_idx,
                use_container_width=True,
            )
        st.selectbox(
            "Jump to StyleCode",
            options=stylecodes,
            key="jump_stylecode",
            on_change=_on_jump,
        )
        st.caption("Use ← → keys to navigate")

    inject_keyboard_nav()


def main() -> None:
    st.set_page_config(page_title="Attribute QA", layout="wide", initial_sidebar_state="expanded")
    load_css()
    init_session_state()
    load_persisted_reviews()
    render_sidebar()

    try:
        df = load_dataframe()
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.info("Upload an Excel file in the sidebar.")
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Could not read the Excel file: {exc}")
        return

    if df.empty:
        st.warning("The uploaded Excel file has no data rows.")
        return

    try:
        groups_config = load_attribute_groups()
    except Exception as exc:
        st.error(f"Could not load attribute configuration: {exc}")
        return

    tab_review, tab_analytics = st.tabs(["Review", "Analytics"])

    with tab_review:
        st.markdown(
            '<div class="dashboard-header-compact">'
            '<span class="dashboard-title">Attribute Review Dashboard</span>'
            '<span class="dashboard-subtitle">Review pipeline-generated attributes against product images.</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        render_review_tab(df, groups_config)

    with tab_analytics:
        render_analytics_tab(st.session_state.votes, df, votes_to_dataframe)


if __name__ == "__main__":
    main()
