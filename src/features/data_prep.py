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

PRODUCT_COLUMNS = ["Товар ур.2", "Товар ур.3", "Товар ур.4"]
SALES_COLUMNS_EXPECTED = {
    "Продажи с НДС": "revenue",
    "Маржа": "margin",
    "Количество": "quantity",
}
CATEGORY_FALLBACK = "Прочие товары, шт.:"
FALLBACK_SUBCATEGORY = "Неопределенная категория"
LEVEL4_EMPTY_MARKERS = frozenset({"-", "—", "–", "―", "‑", "__NONE__", "nan"})


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
        - list of unmatched products (Товар ур.2, Товар ур.3, Товар ур.4)
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

    merged = merge_product_categories(
        merged,
        categories_map,
        value_cols=("Категория агрег.", "Разрез"),
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

    new_clients = (
        merged.loc[merged["Подразделение"].isna(), "Клиент"].dropna().astype("string").unique().tolist()
    )

    unmatched_products_mask = merged["Категория агрег."].eq(FALLBACK_SUBCATEGORY)
    unmatched_products = merged.loc[unmatched_products_mask, PRODUCT_COLUMNS].drop_duplicates()
    unmatched_products_list = [
        (str(row["Товар ур.2"]), str(row["Товар ур.3"]), str(row["Товар ур.4"]))
        for _, row in unmatched_products.iterrows()
        if not _is_blank_product_row(row)
    ]
    unmatched_products_list = sorted(set(unmatched_products_list))

    merged = merged.dropna(subset=["Подразделение"]).reset_index(drop=True)
    return merged, sorted(new_clients), unmatched_products_list


def _is_blank_product_row(row: pd.Series) -> bool:
    """True, если все уровни товара пустые."""
    values = [
        str(row["Товар ур.2"]).strip(),
        str(row["Товар ур.3"]).strip(),
        str(row["Товар ур.4"]).strip(),
    ]
    return all(value in {"", "__NONE__"} for value in values)


def _normalize_level4_value(value: object) -> str:
    """Пустые значения и прочерки в ур.4 → пустая строка (ключ = ур.2 + ур.3)."""
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()
    if not text or text.casefold() in {m.casefold() for m in LEVEL4_EMPTY_MARKERS}:
        return ""
    return text


def merge_product_categories(
    df: pd.DataFrame,
    categories_map: pd.DataFrame,
    value_cols: tuple[str, ...] = ("Категория агрег.", "Разрез"),
) -> pd.DataFrame:
    """Присоединяет категорию/разрез по ур.2 + ур.3 + ур.4.

    1) Точное совпадение по трём уровням (включая заполненный ур.4).
    2) Для несматченных с пустым ур.4 — по ур.2 + ур.3 к строкам
       справочника с пустым ур.4.
    """
    if df.empty:
        result = df.copy()
        for col in value_cols:
            if col not in result.columns:
                result[col] = pd.NA
        return result

    missing_keys = [col for col in PRODUCT_COLUMNS if col not in df.columns]
    if missing_keys:
        raise ValueError(
            f"Для сопоставления с категориями нужны столбцы: {', '.join(PRODUCT_COLUMNS)}. "
            f"Нет: {', '.join(missing_keys)}."
        )

    present_values = [col for col in value_cols if col in categories_map.columns]
    if not present_values:
        raise ValueError(
            f"В карте категорий нет столбцов для присоединения: {', '.join(value_cols)}."
        )

    lookup = (
        categories_map[list(PRODUCT_COLUMNS) + present_values]
        .drop_duplicates(subset=PRODUCT_COLUMNS, keep="first")
    )

    # Убираем старые value_cols, если они уже есть в df (повторный вызов).
    base = df.drop(columns=[c for c in present_values if c in df.columns], errors="ignore")
    result = base.merge(lookup, on=PRODUCT_COLUMNS, how="left")

    primary = present_values[0]
    unmatched = result[primary].isna()
    empty_level4 = result["Товар ур.4"].eq("")
    fallback_mask = unmatched & empty_level4
    if not fallback_mask.any():
        return result

    lookup_23 = (
        lookup.loc[lookup["Товар ур.4"].eq(""), ["Товар ур.2", "Товар ур.3", *present_values]]
        .drop_duplicates(subset=["Товар ур.2", "Товар ур.3"], keep="first")
    )
    if lookup_23.empty:
        return result

    fallback = (
        result.loc[fallback_mask, ["Товар ур.2", "Товар ур.3"]]
        .merge(lookup_23, on=["Товар ур.2", "Товар ур.3"], how="left")
    )
    for col in present_values:
        result.loc[fallback_mask, col] = fallback[col].to_numpy()
    return result


def _build_categories_map(categories_df: pd.DataFrame) -> pd.DataFrame:
    cat_col = get_category_source_column(categories_df)
    if cat_col is None:
        raise ValueError("В справочнике категорий нет столбца «Категория».")

    razrez_col = get_razrez_source_column(categories_df)
    mapping = categories_df.copy()
    mapping = _rename_product_level_columns(mapping)
    mapping = _normalise_product_columns(mapping)
    mapping["Категория raw"] = mapping[cat_col].fillna("").astype(str).str.strip()

    if razrez_col:
        razrez_raw = mapping[razrez_col].fillna("").astype(str).str.strip()
    else:
        razrez_raw = pd.Series([""] * len(mapping), index=mapping.index, dtype="string")

    mapping["Разрез"] = razrez_raw.map(normalize_razrez_value)
    return mapping[PRODUCT_COLUMNS + ["Категория raw", "Разрез"]].drop_duplicates()


def _rename_product_level_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализует имена столбцов уровней товара (с учётом пробелов в заголовках)."""
    rename_map = {
        "товар2": "Товар ур.2",
        "товар 2": "Товар ур.2",
        "товар ур.2": "Товар ур.2",
        "товар ур. 2": "Товар ур.2",
        "товар3": "Товар ур.3",
        "товар 3": "Товар ур.3",
        "товар ур.3": "Товар ур.3",
        "товар ур. 3": "Товар ур.3",
        "товар4": "Товар ур.4",
        "товар 4": "Товар ур.4",
        "товар ур.4": "Товар ур.4",
        "товар ур. 4": "Товар ур.4",
    }
    stripped = {col: str(col).strip() for col in df.columns}
    df = df.rename(columns=stripped)
    resolved: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().casefold()
        target = rename_map.get(key)
        if target and target not in df.columns and target not in resolved.values():
            resolved[col] = target
    return df.rename(columns=resolved)


def _normalise_product_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("Товар ур.2", "Товар ур.3"):
        if col in df.columns:
            df[col] = df[col].fillna("__NONE__").astype(str).str.strip()
            df[col] = df[col].replace(
                {"": "__NONE__", "nan": "__NONE__", "None": "__NONE__"}
            )
        else:
            df[col] = "__NONE__"
    if "Товар ур.4" in df.columns:
        df["Товар ур.4"] = df["Товар ур.4"].map(_normalize_level4_value)
    else:
        df["Товар ур.4"] = ""
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
