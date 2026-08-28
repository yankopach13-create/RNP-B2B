from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List

from features.category_order import (
    COL_TURNOVER,
    _razrez_match_key,
    build_known_razrez_keys,
    collect_known_category_names,
    load_category_order_list,
    match_turnover_label_mask,
    normalize_razrez_value,
)
from features.data_prep import (
    FALLBACK_SUBCATEGORY,
    _build_categories_map,
    _normalise_product_columns,
    _normalise_category_name,
    _rename_product_level_columns,
    merge_product_categories,
)


def _collect_turnover_razrez_keys(
    categories_df: pd.DataFrame,
    order: list[str],
) -> set[str]:
    """Ключи разрезов из справочника categories и строк «в т.ч. …» в category_order."""
    keys = build_known_razrez_keys(categories_df)
    slice_prefix = "в т.ч."
    for label in order:
        cleaned = str(label).strip()
        if not cleaned or not cleaned.lower().startswith(slice_prefix):
            continue
        razrez_key = _razrez_match_key(normalize_razrez_value(cleaned))
        if not razrez_key:
            continue
        keys.add(razrez_key)
        if "/" in razrez_key:
            keys.update(part.strip() for part in razrez_key.split("/") if part.strip())
    return keys


_GENERIC_PRODUCT_ALIASES = frozenset(
    {
        "товар",
        "номенклатура",
        "товар ур4",
        "товар.ур.4",
    }
)


def _prepare_turnover_product_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализует уровни товара; одиночный столбец «Товар» трактует как ур.4."""
    prepared = _rename_product_level_columns(df)
    if "Товар ур.4" in prepared.columns:
        return prepared

    for col in prepared.columns:
        key = str(col).strip().casefold()
        if key in _GENERIC_PRODUCT_ALIASES:
            return prepared.rename(columns={col: "Товар ур.4"})
    return prepared


def calculate_turnover_by_category(
    turnover_df: pd.DataFrame | None,
    categories_df: pd.DataFrame,
    clients_filter: List[str] | None = None,
    period_days: int = 90,
    category_order_df: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    """Считает оборачиваемость по категориям: сопоставление по ур.4, затем агрегация."""
    if turnover_df is None or turnover_df.empty:
        return None

    df = turnover_df.copy()
    df = _prepare_turnover_product_columns(df)

    has_level4 = "Товар ур.4" in df.columns
    has_level23 = "Товар ур.2" in df.columns or "Товар ур.3" in df.columns
    if not has_level4 and not has_level23:
        return None

    if "Клиент" in df.columns and clients_filter:
        df = df[df["Клиент"].astype(str).isin(clients_filter)]
        if df.empty:
            return None

    df = _normalise_product_columns(df)

    known_categories = collect_known_category_names(
        categories_df, category_order_df
    )
    categories_map = _build_categories_map(categories_df)
    categories_map["Категория агрег."] = categories_map["Категория raw"].apply(
        lambda name: _normalise_category_name(name, known_categories)
    )

    df = merge_product_categories(
        df,
        categories_map,
        value_cols=("Категория агрег.", "Разрез"),
    )
    df["Категория агрег."] = (
        df["Категория агрег."]
        .fillna(FALLBACK_SUBCATEGORY)
        .apply(lambda name: _normalise_category_name(name, known_categories))
    )
    df["Разрез"] = df["Разрез"].fillna("").astype(str).map(normalize_razrez_value)

    if (
        "Остаток сред.дн. (Q)" not in df.columns
        or "Продажи (Q)" not in df.columns
    ):
        return None

    df["Остаток сред.дн. (Q)"] = pd.to_numeric(
        df["Остаток сред.дн. (Q)"]
        .astype(str)
        .str.strip()
        .replace({"-": np.nan, "": np.nan})
        .str.replace("\u2212", "-", regex=False)
        .str.replace(" ", ""),
        errors="coerce",
    ).fillna(0.0)

    df["Продажи (Q)"] = pd.to_numeric(
        df["Продажи (Q)"]
        .astype(str)
        .str.strip()
        .replace({"-": np.nan, "": np.nan})
        .str.replace("\u2212", "-", regex=False)
        .str.replace(" ", ""),
        errors="coerce",
    ).fillna(0.0)

    order = load_category_order_list(category_order_df, COL_TURNOVER)
    known_razrez_keys = _collect_turnover_razrez_keys(categories_df, order)

    rows = []
    for label in order:
        cleaned_label = str(label).strip()
        if not cleaned_label:
            continue
        stock, sales = _sum_turnover_metrics(
            df,
            cleaned_label,
            known_categories,
            known_razrez_keys,
        )
        turnover_value = _calc_turnover(stock, sales, period_days)
        rows.append({"Категория": cleaned_label, "Оборачиваемость": turnover_value})

    return pd.DataFrame(rows)


def _sum_turnover_metrics(
    df: pd.DataFrame,
    label: str,
    known_categories: set[str],
    known_razrez_keys: set[str],
) -> tuple[float, float]:
    if df.empty:
        return 0.0, 0.0

    stock_series = pd.to_numeric(df["Остаток сред.дн. (Q)"], errors="coerce").fillna(0.0)
    sales_series = pd.to_numeric(df["Продажи (Q)"], errors="coerce").fillna(0.0)
    mask = match_turnover_label_mask(df, label, known_categories, known_razrez_keys)
    return float(stock_series.loc[mask].sum()), float(sales_series.loc[mask].sum())


def _calc_turnover(avg_stock: float, total_sales: float, period_days: int) -> float | None:
    if period_days <= 0:
        return np.nan
    if total_sales <= 0:
        return np.nan
    return (avg_stock * period_days) / total_sales

def has_turnover_data(table: pd.DataFrame | None) -> bool:
    return table is not None and not table.empty

def format_turnover_value(value: float | int | None) -> str:
    if value is None or np.isnan(value):
        return "-"
    return str(int(round(float(value))))
