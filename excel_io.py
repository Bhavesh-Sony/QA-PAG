"""Read uploaded Excel workbooks."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from config_dashboard import STYLECODE_COLUMN
from stylecode_utils import normalize_stylecode


@st.cache_data(show_spinner=False)
def read_excel_bytes(file_digest: str, file_bytes: bytes) -> pd.DataFrame:
    """Parse an uploaded workbook; file_digest is used only for cache invalidation."""
    df = pd.read_excel(BytesIO(file_bytes))

    if STYLECODE_COLUMN not in df.columns:
        raise ValueError(f"Expected column '{STYLECODE_COLUMN}' in Excel file.")

    df[STYLECODE_COLUMN] = df[STYLECODE_COLUMN].map(normalize_stylecode)
    return df
