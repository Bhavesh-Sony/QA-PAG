"""Dashboard configuration constants."""

from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
DATA_DIR = DASHBOARD_DIR / "data"
ATTRIBUTE_GROUPS_PATH = DASHBOARD_DIR / "attribute_groups.yaml"
STYLES_PATH = DASHBOARD_DIR / "styles.css"

STYLECODE_COLUMN = "StyleCode"

IMAGE_OPTIONS = {
    "Front": "front_image",
    "Collar": "collar",
    "Cuff": "cuff_image",
}

DEFAULT_SELECTED_IMAGES = ["Front"]
DEFAULT_SELECTED_GROUPS: list[str] = []

PREFETCH_WINDOW = 2
IMAGE_CACHE_MAX_SIZE = 50
IMAGE_DOWNLOAD_TIMEOUT = 10

GROUP_DISPLAY_NAMES: dict[str, str] = {}
