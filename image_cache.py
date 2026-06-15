"""LRU image byte cache with background prefetch."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable

import requests
import streamlit as st

from config_dashboard import IMAGE_CACHE_MAX_SIZE, IMAGE_DOWNLOAD_TIMEOUT, IMAGE_COLUMN_CANDIDATES


class ImageCache:
    def __init__(self, max_size: int = IMAGE_CACHE_MAX_SIZE):
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._inflight: set[str] = set()

    def get(self, url: str) -> bytes | None:
        if not url:
            return None
        with self._lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        return None

    def put(self, url: str, data: bytes) -> None:
        if not url or not data:
            return
        with self._lock:
            self._cache[url] = data
            self._cache.move_to_end(url)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def fetch(self, url: str) -> bytes | None:
        cached = self.get(url)
        if cached is not None:
            return cached
        try:
            response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            response.raise_for_status()
            data = response.content
            self.put(url, data)
            return data
        except requests.RequestException:
            return None

    def prefetch(self, urls: list[str]) -> None:
        unique = [u for u in dict.fromkeys(urls) if u]

        def _worker() -> None:
            for url in unique:
                if self.get(url) is not None:
                    continue
                with self._lock:
                    if url in self._inflight:
                        continue
                    self._inflight.add(url)
                try:
                    self.fetch(url)
                finally:
                    with self._lock:
                        self._inflight.discard(url)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()


@st.cache_resource
def get_image_cache() -> ImageCache:
    return ImageCache()


def resolve_image_url(row, candidates: list[str]) -> str | None:
    """Return the first non-empty image URL from candidate column names."""
    for col in candidates:
        if col not in row.index:
            continue
        raw = row.get(col)
        if raw is not None and str(raw).strip().lower() not in ("", "nan"):
            return str(raw).strip()
    return None


def collect_urls_for_rows(
    df,
    row_indices: list[int],
    image_candidates_map: dict[str, list[str]],
    selected_image_labels: list[str],
) -> list[str]:
    urls: list[str] = []
    for idx in row_indices:
        if idx < 0 or idx >= len(df):
            continue
        row = df.iloc[idx]
        for label in selected_image_labels:
            candidates = image_candidates_map.get(label, [])
            url = resolve_image_url(row, candidates)
            if url:
                urls.append(url)
    return urls


def prefetch_window(
    df,
    center_idx: int,
    window: int,
    image_candidates_map: dict[str, list[str]],
    selected_image_labels: list[str],
    cache: ImageCache | None = None,
) -> None:
    if cache is None:
        cache = get_image_cache()
    indices = list(range(max(0, center_idx - window), min(len(df), center_idx + window + 1)))
    urls = collect_urls_for_rows(df, indices, image_candidates_map, selected_image_labels)
    cache.prefetch(urls)


def render_image_panel(
    urls_by_label: list[tuple[str, str | None]],
    cache: ImageCache,
    placeholder_fn: Callable[[str], None],
    image_fn: Callable[[bytes], None],
) -> None:
    """Render up to 2 images side by side in the main image panel."""
    valid = [(label, url) for label, url in urls_by_label[:2] if url]

    if not valid:
        placeholder_fn("No images selected or available")
        return

    if len(valid) == 1:
        label, url = valid[0]
        data = cache.get(url) or cache.fetch(url)
        if data:
            image_fn(data)
        else:
            placeholder_fn(f"{label} image unavailable")
        return

    cols = st.columns(2, gap="small")
    for col, (label, url) in zip(cols, valid):
        with col:
            data = cache.get(url) or cache.fetch(url)
            if data:
                image_fn(data)
            else:
                placeholder_fn(f"{label} unavailable")
