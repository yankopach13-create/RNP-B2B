# src/features/data_prep.py
from __future__ import annotations
from typing import Iterable, List, Tuple
import numpy as np
import pandas as pd

from config.constants import CATEGORY_DISPLAY_ORDER, CATEGORY_FIXES

PRODUCT_COLUMNS = ["Товар ур.1", "Товар ур.2", "Товар ур.3"]
SALES_COLUMNS_EXPECTED = {
    "Продажи с НДС": "revenue",
    "Маржа": "margin",
    "Количество": "quantity",
}
CATEGORY_FALLBACK = "Прочие товары, шт.:"
FALLBACK_SUBCATEGORY = "Неопределенная категория"

def prepare_dataset(
    sales_df: pd.DataFrame,
    contractors_df: pd.DataFrame,
    categories_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str], List[Tuple[str, str, str]]]:
    """Соединяет продажи со справочниками контрагентов и категорий.
    
    Returns:
        Tuple containing:
        - merged DataFrame
        - list of new clients (without subdivision)
        - list of unmatched products (Товар ур.1, Товар ур.2, Товар ур.3)
    """
    columns_needed = ["Контрагент", "Подразделение"]
    if "Сегмент" in contractors_df.columns:
        columns_needed.append("Сегмент")
    contractors = (
        contractors_df[columns_needed].dropna(subset=["Контрагент"]).copy()
    )
    contractors["Контрагент"] = contractors["Контрагент"].astype(str).str.strip()
    contractors["Подразделение"] = (
        contractors["Подразделение"].astype(str).str.strip().replace("", np.nan)
    )
    if "Сегмент" in contractors.columns:
        contractors["Сегмент"] = contractors["Сегмент"].astype(str).str.strip()
    else:
        contractors["Сегмент"] = ""
    contractors = contractors.dropna(subset=["Подразделение"])

    contractors_map = (
        contractors.groupby("Контрагент")["Подразделение"].first().to_dict()
    )
    segment_map = (
        contractors.groupby("Контрагент")["Сегмент"].first().to_dict()
    )

    categories_map = (
        categories_df[PRODUCT_COLUMNS + ["Категория:", "Разрез 1", "Разрез 2"]]
        .drop_duplicates()
        .rename(columns={"Категория:": "Категория агрег."})
    )
    categories_map = _normalise_product_columns(categories_map)
    categories_map["Категория агрег."] = (
        categories_map["Категория агрег."].fillna(FALLBACK_SUBCATEGORY).apply(
            _normalise_category_name
        )
    )
    categories_map["Разрез 1"] = categories_map["Разрез 1"].fillna("")
    categories_map["Разрез 2"] = categories_map["Разрез 2"].fillna("")

    sales = sales_df.copy()
    sales = _normalise_product_columns(sales)
    _ensure_numeric_columns(sales, SALES_COLUMNS_EXPECTED.keys())
    sales["Клиент"] = sales["Клиент"].astype(str).str.strip()
    if "Группа контрагентов" in sales.columns:
        sales["Группа контрагентов"] = (
            sales["Группа контрагентов"].fillna("").astype(str).str.strip()
        )
    else:
        sales["Группа контрагентов"] = ""

    merged = sales.merge(
        contractors.rename(columns={"Контрагент": "Клиент"}),
        how="left",
        on="Клиент",
    )

    missing_mask = merged["Подразделение"].isna() & merged["Группа контрагентов"].astype(bool)
    if missing_mask.any():
        merged.loc[missing_mask, "Подразделение"] = (
            merged.loc[missing_mask, "Группа контрагентов"]
            .map(contractors_map)
            .fillna(merged.loc[missing_mask, "Подразделение"])
        )
        merged.loc[missing_mask, "Сегмент"] = (
            merged.loc[missing_mask, "Группа контрагентов"]
            .map(segment_map)
            .fillna(merged.loc[missing_mask, "Сегмент"])
        )

    merged = merged.merge(categories_map, how="left", on=PRODUCT_COLUMNS)
    merged["Категория агрег."] = (
        merged["Категория агрег."].fillna(FALLBACK_SUBCATEGORY).apply(
            _normalise_category_name
        )
    )
    merged["Разрез 1"] = merged["Разрез 1"].fillna("")
    merged["Разрез 2"] = merged["Разрез 2"].fillna("")
    merged.loc[
        merged["Категория агрег."].eq(FALLBACK_SUBCATEGORY) & merged["Разрез 1"].eq(""),
        "Разрез 1",
    ] = FALLBACK_SUBCATEGORY
    merged["Подразделение"] = merged["Подразделение"].replace("", np.nan).astype("string")
    merged["Сегмент"] = merged["Сегмент"].fillna("").astype("string")

    # Special case for hookah coal to include in "в т.ч. Прочее"
    mask_hookah_coal = merged[PRODUCT_COLUMNS].astype(str).apply(lambda x: x.str.contains("Уголь", case=False, na=False)).any(axis=1)
    merged.loc[mask_hookah_coal, "Разрез 1"] = "в т.ч. Прочее"

    new_clients = (
        merged.loc[merged["Подразделение"].isna(), "Клиент"].dropna().astype("string").unique().tolist()
    )
    
    # Find products not found in categories (those with FALLBACK_SUBCATEGORY)
    # Check before filtering by Подразделение to capture all unmatched products
    unmatched_products_mask = merged["Категория агрег."].eq(FALLBACK_SUBCATEGORY)
    unmatched_products = merged.loc[unmatched_products_mask, PRODUCT_COLUMNS].drop_duplicates()
    unmatched_products_list = [
        (str(row["Товар ур.1"]), str(row["Товар ур.2"]), str(row["Товар ур.3"]))
        for _, row in unmatched_products.iterrows()
        if not (str(row["Товар ур.1"]) == "__NONE__" and str(row["Товар ур.2"]) == "__NONE__" and str(row["Товар ур.3"]) == "__NONE__")
    ]
    # Remove duplicates and sort
    unmatched_products_list = sorted(set(unmatched_products_list))
    
    merged = merged.dropna(subset=["Подразделение"]).reset_index(drop=True)
    return merged, sorted(new_clients), unmatched_products_list

def _normalise_product_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in PRODUCT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna("__NONE__").astype(str).str.strip()
        else:
            df[col] = "__NONE__"
    return df

def _ensure_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    for col in columns:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

def _normalise_category_name(name: str) -> str:
    """Приводит название категории к стандартному виду."""
    if not isinstance(name, str):
        return CATEGORY_FALLBACK
    cleaned = name.strip()
    if cleaned in CATEGORY_FIXES:
        return CATEGORY_FIXES[cleaned]
    if cleaned.endswith("."):
        return cleaned
    candidate = f"{cleaned}."
    if candidate in CATEGORY_DISPLAY_ORDER:
        return candidate
    return cleaned