"""Streamlit Attribute Review Dashboard."""

from __future__ import annotations

import hashlib
import uuid

import streamlit as st
import streamlit.components.v1 as components

from config_dashboard import (
    DEFAULT_SELECTED_GROUPS,
    DEFAULT_SELECTED_IMAGES,
    IMAGE_COLUMN_CANDIDATES,
    PREFETCH_WINDOW,
    STYLES_PATH,
)
from brand_filter import filter_brand_column
from stylecode_utils import get_row_votes, normalize_stylecode
from review_checks import all_attributes_reviewed, is_attribute_reviewed
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
    filter_by_attribute_values,
    format_cell_value,
    get_row_by_index,
    get_stylecode,
    group_display_name,
    jump_label,
    load_attribute_groups,
    resolve_group_columns,
    resolve_jump_query,
    unique_brand_values,
)
from excel_io import read_excel_bytes
from image_cache import (
    get_image_cache,
    prefetch_window,
    render_image_panel,
    resolve_image_url,
)
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
        "jump_message": "",
        "attribute_filters": {},
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
    row_votes = get_row_votes(votes, stylecode)
    return sum(1 for g in group_keys if is_attribute_reviewed(row_votes, g))


def note_input_key(stylecode: str, group_key: str) -> str:
    return f"note_{stylecode}_{group_key}"


def on_prev(max_idx: int) -> None:
    st.session_state.row_idx = max(0, st.session_state.row_idx - 1)


def on_next(max_idx: int) -> None:
    st.session_state.row_idx = min(max_idx, st.session_state.row_idx + 1)


def find_next_unreviewed_nav_pos(
    df,
    nav_indices: list[int],
    start_pos: int,
    votes: dict,
    group_keys: list[str],
) -> int | None:
    for pos in range(max(0, start_pos), len(nav_indices)):
        idx = nav_indices[pos]
        stylecode = get_stylecode(df.iloc[idx])
        if not all_attributes_reviewed(votes, stylecode, group_keys):
            return pos
    return None


def on_jump_go(df, nav_indices: list[int]) -> None:
    query = str(st.session_state.get("jump_search", "")).strip()
    st.session_state.jump_message = ""
    if not query:
        return
    matches = resolve_jump_query(df, query)
    matches = [i for i in matches if i in nav_indices]
    if len(matches) == 1:
        st.session_state.row_idx = nav_indices.index(matches[0])
    elif not matches:
        st.session_state.jump_message = "No matching row found."
    else:
        st.session_state.jump_match_options = matches
        st.session_state.jump_message = f"Found {len(matches)} matches — pick one below."


def on_jump_select() -> None:
    nav_indices = st.session_state.get("_nav_indices", [])
    selected_data_idx = st.session_state.jump_row_select
    if selected_data_idx in nav_indices:
        st.session_state.row_idx = nav_indices.index(selected_data_idx)
    st.session_state.jump_match_options = None
    st.session_state.jump_message = ""


def _advance_after_review(df, nav_indices: list[int], group_keys: list[str], stylecode: str) -> bool:
    """Advance to the next row once every selected group has a vote or note."""
    if not group_keys:
        return False
    if not all_attributes_reviewed(st.session_state.votes, stylecode, group_keys):
        return False

    max_pos = len(nav_indices) - 1
    if max_pos < 0:
        return False

    if st.session_state.only_unreviewed:
        next_pos = find_next_unreviewed_nav_pos(
            df,
            nav_indices,
            st.session_state.row_idx + 1,
            st.session_state.votes,
            group_keys,
        )
        if next_pos is not None:
            st.session_state.row_idx = next_pos
            return True
        if st.session_state.row_idx < max_pos:
            st.session_state.row_idx += 1
            return True
        return False

    if st.session_state.row_idx < max_pos:
        st.session_state.row_idx += 1
        return True
    return False


def on_note_saved(
    stylecode: str,
    group_key: str,
    df,
    nav_indices: list[int],
    group_keys: list[str],
) -> None:
    nav_indices = st.session_state.get("_nav_indices") or nav_indices
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
    _advance_after_review(df, nav_indices, group_keys, stylecode)


def on_vote_click(
    stylecode: str,
    group_key: str,
    vote: str,
    df,
    nav_indices: list[int],
    group_keys: list[str],
) -> None:
    nav_indices = st.session_state.get("_nav_indices") or nav_indices
    key = note_input_key(stylecode, group_key)
    note = str(st.session_state.get(key, get_note(st.session_state.votes, stylecode, group_key)))
    record_vote(st.session_state.votes, stylecode, group_key, vote, note=note)
    persist_reviews()
    _advance_after_review(df, nav_indices, group_keys, stylecode)


def render_attribute_vote_panel(
    df,
    nav_indices: list[int],
    resolved_groups: dict,
    group_keys: list[str],
    stylecode: str,
    row,
) -> None:
    """Render attribute cards and vote controls for the current row."""
    if not group_keys:
        st.warning("Select at least one attribute group to review.")
        return

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
                args=(stylecode, group_key, "like", df, nav_indices, group_keys),
            )
        with btn_dislike:
            st.button(
                "👎 Dislike",
                key=f"dislike_{stylecode}_{group_key}",
                use_container_width=True,
                on_click=on_vote_click,
                args=(stylecode, group_key, "dislike", df, nav_indices, group_keys),
            )

        st.text_input(
            "Note",
            value=existing_note,
            key=note_input_key(stylecode, group_key),
            label_visibility="collapsed",
            placeholder="Optional note…",
            on_change=on_note_saved,
            args=(stylecode, group_key, df, nav_indices, group_keys),
        )


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
            options=list(IMAGE_COLUMN_CANDIDATES.keys()),
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

    filter_sig = str({k: st.session_state.get(f"attr_filter_{k}", []) for k in group_keys})
    if st.session_state.get("_attr_filter_sig") != filter_sig:
        st.session_state._attr_filter_sig = filter_sig
        st.session_state.row_idx = 0

    if group_keys:
        with st.expander("Filter by attribute values", expanded=False):
            filter_cols = st.columns(min(len(group_keys), 3) or 1)
            for i, group_key in enumerate(group_keys):
                brand_col = filter_brand_column(
                    group_key, resolved_groups[group_key].get("brand_columns", [])
                )
                if not brand_col:
                    continue
                options = unique_brand_values(df, brand_col)
                if not options:
                    continue
                with filter_cols[i % len(filter_cols)]:
                    st.multiselect(
                        group_display_name(group_key),
                        options=options,
                        key=f"attr_filter_{group_key}",
                    )

    attribute_filters = {
        group_key: st.session_state.get(f"attr_filter_{group_key}", [])
        for group_key in group_keys
    }
    st.session_state.attribute_filters = attribute_filters

    nav_indices = filter_by_attribute_values(
        df,
        list(range(len(df))),
        resolved_groups,
        attribute_filters,
    )

    if not nav_indices:
        st.warning("No rows match the selected attribute filters.")
        return

    st.session_state._nav_indices = nav_indices

    max_row_pos = len(nav_indices) - 1
    st.session_state.row_idx = max(0, min(st.session_state.row_idx, max_row_pos))
    data_idx = nav_indices[st.session_state.row_idx]
    row = get_row_by_index(df, data_idx)
    stylecode = get_stylecode(row)

    nav_stylecodes = [get_stylecode(df.iloc[i]) for i in nav_indices]

    prefetch_window(
        df,
        data_idx,
        PREFETCH_WINDOW,
        IMAGE_COLUMN_CANDIDATES,
        st.session_state.selected_images,
        cache,
    )

    with c_prog:
        reviewed = count_reviewed_for_attributes(
            st.session_state.votes,
            nav_stylecodes,
            group_keys,
        )
        unreviewed = (
            sum(
                1
                for i in nav_indices
                if not all_attributes_reviewed(
                    st.session_state.votes,
                    get_stylecode(df.iloc[i]),
                    group_keys,
                )
            )
            if group_keys
            else len(nav_indices)
        )
        groups_done = count_groups_reviewed_on_row(st.session_state.votes, stylecode, group_keys)
        groups_hint = ""
        if group_keys:
            groups_hint = (
                f'<br>Groups reviewed on this StyleCode: {groups_done} / {len(group_keys)}'
            )
        unreviewed_hint = ""
        if group_keys:
            unreviewed_hint = f"<br>Unreviewed: {unreviewed}"
        total_label = len(nav_indices) if len(nav_indices) != len(df) else len(df)
        st.markdown(
            f'<p class="progress-text">Row {st.session_state.row_idx + 1} / {total_label}'
            f" (dataset row {data_idx + 1})<br>"
            f"StyleCode: <strong>{stylecode}</strong><br>"
            f"Fully reviewed: {reviewed} / {total_label}{unreviewed_hint}{groups_hint}</p>",
            unsafe_allow_html=True,
        )
    st.markdown('<div class="sticky-controls-end"></div>', unsafe_allow_html=True)

    left_col, right_col = st.columns([7, 3])

    with left_col:
        st.markdown('<div class="image-panel-marker"></div>', unsafe_allow_html=True)
        urls_by_label: list[tuple[str, str | None]] = []
        for label in st.session_state.selected_images[:2]:
            url = resolve_image_url(row, IMAGE_COLUMN_CANDIDATES.get(label, []))
            urls_by_label.append((label, url))

        def placeholder(msg: str) -> None:
            st.markdown(f'<div class="image-placeholder">{msg}</div>', unsafe_allow_html=True)

        def show_image(data: bytes) -> None:
            st.image(data, use_container_width=True)

        render_image_panel(urls_by_label, cache, placeholder, show_image)

    with right_col:
        st.markdown('<div class="attribute-panel-marker"></div>', unsafe_allow_html=True)
        render_attribute_vote_panel(df, nav_indices, resolved_groups, group_keys, stylecode, row)

        st.markdown('<div class="review-nav-divider"></div>', unsafe_allow_html=True)
        nav_prev, nav_next = st.columns(2)
        with nav_prev:
            st.markdown('<div class="review-nav-marker"></div>', unsafe_allow_html=True)
            st.button(
                "← Previous",
                on_click=on_prev,
                args=(max_row_pos,),
                disabled=st.session_state.row_idx <= 0,
                use_container_width=True,
            )
        with nav_next:
            st.button(
                "Next →",
                on_click=on_next,
                args=(max_row_pos,),
                disabled=st.session_state.row_idx >= max_row_pos,
                use_container_width=True,
            )

        jump_col1, jump_col2 = st.columns([4, 1])
        with jump_col1:
            st.text_input(
                "Jump by row # or StyleCode",
                key="jump_search",
                placeholder="e.g. 42, #100, or ABC123",
            )
        with jump_col2:
            st.button(
                "Go",
                key="jump_go_btn",
                on_click=on_jump_go,
                args=(df, nav_indices),
                use_container_width=True,
            )

        if st.session_state.get("jump_message"):
            st.caption(st.session_state.jump_message)

        jump_options = st.session_state.get("jump_match_options") or nav_indices
        jump_options = [i for i in jump_options if i in nav_indices]
        if not st.session_state.get("jump_match_options"):
            st.session_state.jump_row_select = data_idx
        elif st.session_state.jump_row_select not in jump_options:
            st.session_state.jump_row_select = jump_options[0]
        st.selectbox(
            "Jump to row",
            options=jump_options,
            format_func=lambda i: jump_label(df, i),
            key="jump_row_select",
            on_change=on_jump_select,
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
