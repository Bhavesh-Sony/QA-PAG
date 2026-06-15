"""Brand column selection for attribute value filters."""


def filter_brand_column(group_key: str, brand_columns: list[str]) -> str | None:
    """Column used for attribute value filters (Placket uses Brand Placket, not length)."""
    if group_key == "Placket" and "Brand Placket" in brand_columns:
        return "Brand Placket"
    return brand_columns[0] if brand_columns else None
