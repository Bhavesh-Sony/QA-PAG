"""Accuracy metrics and analytics visualizations."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from data_loader import get_stylecode, load_attribute_groups
from review_store import count_reviewed_for_attributes, default_reviews_path, save_reviews


def compute_attribute_accuracy(
    votes_df: pd.DataFrame,
    df: pd.DataFrame,
    groups_config: dict[str, dict[str, list[str]]] | None = None,
    stylecode_col: str = "StyleCode",
) -> pd.DataFrame:
    if votes_df.empty:
        return pd.DataFrame(
            columns=["attribute", "likes", "dislikes", "total_votes", "accuracy_pct", "coverage_rows"]
        )

    rows: list[dict[str, Any]] = []
    attributes = sorted(votes_df["attribute"].unique())

    for attr in attributes:
        attr_votes = votes_df[votes_df["attribute"] == attr]
        likes = int((attr_votes["vote"] == "like").sum())
        dislikes = int((attr_votes["vote"] == "dislike").sum())
        total = likes + dislikes
        accuracy = round(100.0 * likes / total, 1) if total else None

        coverage = 0
        if groups_config and attr in groups_config:
            brand_cols = [
                c for c in groups_config[attr].get("brand_columns", []) if c in df.columns
            ]
            if brand_cols:
                coverage = int(
                    df[brand_cols]
                    .apply(
                        lambda row: any(
                            v is not None and str(v).strip() not in ("", "nan", "—")
                            for v in row
                        ),
                        axis=1,
                    )
                    .sum()
                )
        elif attr in df.columns:
            coverage = int(
                df[attr].apply(lambda v: v is not None and str(v).strip() not in ("", "nan", "—")).sum()
            )

        rows.append(
            {
                "attribute": attr,
                "likes": likes,
                "dislikes": dislikes,
                "total_votes": total,
                "accuracy_pct": accuracy,
                "coverage_rows": coverage,
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("accuracy_pct", ascending=True, na_position="first")
    return result


def compute_overall_accuracy(votes_df: pd.DataFrame) -> dict[str, Any]:
    if votes_df.empty:
        return {"likes": 0, "dislikes": 0, "total_votes": 0, "accuracy_pct": None}

    likes = int((votes_df["vote"] == "like").sum())
    dislikes = int((votes_df["vote"] == "dislike").sum())
    total = likes + dislikes
    accuracy = round(100.0 * likes / total, 1) if total else None
    return {
        "likes": likes,
        "dislikes": dislikes,
        "total_votes": total,
        "accuracy_pct": accuracy,
    }


def compute_row_completion(
    votes: dict[str, dict[str, dict[str, str]]],
    df: pd.DataFrame,
    attributes: list[str],
) -> dict[str, int]:
    if not attributes:
        return {"total_rows": len(df), "fully_reviewed": 0, "unreviewed": len(df)}
    all_stylecodes = [get_stylecode(df.iloc[i]) for i in range(len(df))]
    fully_reviewed = count_reviewed_for_attributes(votes, all_stylecodes, attributes)
    return {
        "total_rows": len(df),
        "fully_reviewed": fully_reviewed,
        "unreviewed": len(df) - fully_reviewed,
    }


def render_analytics_tab(
    votes: dict[str, dict[str, dict[str, str]]],
    df: pd.DataFrame,
    votes_to_dataframe_fn,
) -> None:
    votes_df = votes_to_dataframe_fn(votes)
    overall = compute_overall_accuracy(votes_df)
    groups_config = load_attribute_groups()
    all_group_keys = list(groups_config.keys())
    completion = compute_row_completion(votes, df, all_group_keys)
    attr_df = compute_attribute_accuracy(votes_df, df, groups_config=groups_config)

    st.subheader("Review completion")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total rows", completion["total_rows"])
    c2.metric("Fully reviewed (all groups)", completion["fully_reviewed"])
    c3.metric("Unreviewed", completion["unreviewed"])

    st.subheader("Overall accuracy")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total votes", overall["total_votes"])
    m2.metric("Likes", overall["likes"])
    m3.metric("Dislikes", overall["dislikes"])
    acc_label = f"{overall['accuracy_pct']}%" if overall["accuracy_pct"] is not None else "—"
    m4.metric("Approval rate", acc_label)

    st.subheader("Attribute-wise accuracy")
    if attr_df.empty:
        st.info("No reviews recorded yet. Vote on attributes in the Review tab.")
        return

    st.dataframe(attr_df, use_container_width=True, hide_index=True)

    chart_df = attr_df.dropna(subset=["accuracy_pct"])
    if not chart_df.empty:
        fig = px.bar(
            chart_df,
            x="accuracy_pct",
            y="attribute",
            orientation="h",
            title="Approval rate by attribute",
            labels={"accuracy_pct": "Approval %", "attribute": "Attribute"},
            color="accuracy_pct",
            color_continuous_scale=["#ef4444", "#fbbf24", "#22c55e"],
            range_color=[0, 100],
        )
        fig.update_layout(height=max(320, len(chart_df) * 28), margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Export")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download reviews (CSV)",
            data=votes_df.to_csv(index=False),
            file_name="reviews.csv",
            mime="text/csv",
        )
    with c2:
        st.download_button(
            "Download accuracy report (CSV)",
            data=attr_df.to_csv(index=False),
            file_name="accuracy_report.csv",
            mime="text/csv",
        )
    with c3:
        if st.button("Reset all votes", type="secondary"):
            st.session_state.confirm_reset = True
        if st.session_state.get("confirm_reset"):
            st.warning("This will permanently clear all votes in the current session.")
            if st.button("Confirm reset", type="primary"):
                st.session_state.votes = {}
                path = default_reviews_path(st.session_state.session_id)
                save_reviews(
                    path,
                    st.session_state.votes,
                    {
                        "reviewer_name": st.session_state.get("reviewer_name", ""),
                        "session_id": st.session_state.session_id,
                    },
                )
                st.session_state.confirm_reset = False
                st.rerun()
            if st.button("Cancel reset"):
                st.session_state.confirm_reset = False
                st.rerun()
