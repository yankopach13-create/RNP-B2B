# src/features/data_prep.py
from __future__ import annotations
from typing import Iterable, List, Tuple
import numpy as np
import pandas as pd

from config.constants import CATEGORY_FIXES
from features.category_order import (
    collect_known_category_names,
    get_category_source_column,
    get_razrez_source_column,
    normalize_razrez_value,
    _label_key,
)

PRODUCT_COLUMNS = ["Товар ур.1", "Товар ур.2", "Товар ур.3"]
OPTIONAL_PRODUCT_COLUMNS = ["Товар ур.4"]
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
    category_order_df: pd.DataFrame | None = None,
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

    known_categories = collect_known_category_names(
        categories_df, category_order_df
    )
    categories_map = _build_categories_map(categories_df)
    categories_map["Категория агрег."] = (
        categories_map["Категория raw"]
        .fillna(FALLBACK_SUBCATEGORY)
        .apply(lambda name: _normalise_category_name(name, known_categories))
    )

    sales = sales_df.copy()
    sales = _rename_product_level_columns(sales)
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

    merge_cols = PRODUCT_COLUMNS + ["Категория агрег.", "Разрез"]
    merged = merged.merge(
        categories_map[merge_cols].drop_duplicates(),
        how="left",
        on=PRODUCT_COLUMNS,
    )
    merged["Категория агрег."] = (
        merged["Категория агрег."]
        .fillna(FALLBACK_SUBCATEGORY)
        .apply(lambda name: _normalise_category_name(name, known_categories))
    )
    merged["Разрез"] = merged["Разрез"].fillna("").astype(str).map(normalize_razrez_value)
    merged.loc[
        merged["Категория агрег."].eq(FALLBACK_SUBCATEGORY) & merged["Разрез"].eq(""),
        "Разрез",
    ] = FALLBACK_SUBCATEGORY
    merged["Подразделение"] = merged["Подразделение"].replace("", np.nan).astype("string")
    merged["Сегмент"] = merged["Сегмент"].fillna("").astype("string")

    # Уголь для кальянов: если в справочнике разрез не задан — помечаем как «уголь»
    mask_hookah_coal = merged[PRODUCT_COLUMNS].astype(str).apply(
        lambda x: x.str.contains("Уголь", case=False, na=False)
    ).any(axis=1)
    merged.loc[mask_hookah_coal & merged["Разрез"].eq(""), "Разрез"] = "уголь"

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


def _build_categories_map(categories_df: pd.DataFrame) -> pd.DataFrame:
    cat_col = get_category_source_column(categories_df)
    if cat_col is None:
        raise ValueError("В справочнике категорий нет столбца «Категория».")

    razrez_col = get_razrez_source_column(categories_df)
    mapping = categories_df.copy()
    mapping = _normalise_product_columns(mapping)
    mapping["Категория raw"] = mapping[cat_col].fillna("").astype(str).str.strip()

    if razrez_col:
        razrez_raw = mapping[razrez_col].fillna("").astype(str).str.strip()
    else:
        razrez_raw = pd.Series([""] * len(mapping), index=mapping.index, dtype="string")

    if "Разрез 2" in mapping.columns:
        slice2 = mapping["Разрез 2"].fillna("").astype(str).str.strip()
        razrez_raw = razrez_raw.where(razrez_raw.ne(""), slice2)

    mapping["Разрез"] = razrez_raw.map(normalize_razrez_value)
    return mapping[PRODUCT_COLUMNS + ["Категория raw", "Разрез"]].drop_duplicates()

def _rename_product_level_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "Товар1": "Товар ур.1",
        "Товар 1": "Товар ур.1",
        "Товар2": "Товар ур.2",
        "Товар 2": "Товар ур.2",
        "Товар3": "Товар ур.3",
        "Товар 3": "Товар ур.3",
        "Товар4": "Товар ур.4",
        "Товар 4": "Товар ур.4",
        "Товар ур. 4": "Товар ур.4",
    }
    return df.rename(columns={src: dst for src, dst in rename_map.items() if src in df.columns})


def _normalise_product_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in PRODUCT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna("__NONE__").astype(str).str.strip()
        else:
            df[col] = "__NONE__"
    for col in OPTIONAL_PRODUCT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
            df[col] = df[col].replace("__NONE__", "")
        else:
            df[col] = ""
    return df

def _ensure_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    for col in columns:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

def _normalise_category_name(
    name: str,
    known_categories: set[str] | None = None,
) -> str:
    """Приводит название категории к стандартному виду."""
    if not isinstance(name, str):
        return CATEGORY_FALLBACK
    cleaned = name.strip()
    if cleaned in CATEGORY_FIXES:
        return CATEGORY_FIXES[cleaned]
    if known_categories:
        name_key = _label_key(cleaned)
        for known in known_categories:
            if _label_key(known) == name_key:
                return known
        if cleaned in known_categories:
            return cleaned
        candidate = f"{cleaned}."
        if candidate in known_categories:
            return candidate
        if cleaned.endswith(".") and cleaned[:-1] in known_categories:
            return cleaned[:-1]
    if cleaned.endswith("."):
        return cleaned
    return cleaned
