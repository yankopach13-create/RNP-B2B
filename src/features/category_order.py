"""Порядок категорий из листа category_order и агрегация по категории/разрезу."""

from __future__ import annotations

from typing import Callable

from dataclasses import dataclass

import pandas as pd

from config.constants import (
    CATEGORY_DISPLAY_ORDER,
    TRADITION_CATEGORY_ORDER,
    TURNOVER_CATEGORY_ORDER,
)

SLICE_PREFIX = "в т.ч."

COL_SPEC_RNP = "Категории РНП Спец розница"
COL_GENERAL_SPEC = "Категории Общий РНП Спец розница"
COL_TURNOVER = "Оборачиваемость"
COL_TRADITION_RNP = "Категории РНП Традиция"
COL_GENERAL_TRADITION = "Категории Общий РНП Традиция"

FALLBACK_ORDERS: dict[str, list[str]] = {
    COL_SPEC_RNP: list(CATEGORY_DISPLAY_ORDER),
    COL_GENERAL_SPEC: [
        "ОЭС 2 мл, шт.",
        "ОЭС 4 мл, шт.",
        "ОЭС 10 мл, шт.",
        "Жидкость 25 мл, шт.",
        "Pod-системы, шт.",
        "Расходники, шт.",
        "Картриджи с жидкостью, шт.",
        "Никотиновые паучи, шт.",
        "ATOM",
        "Pau4",
        "Level UP",
        "Кальянная продукция, шт.",
        "в т.ч. Кальянные смеси, шт.",
        "Прочие товары, шт.",
    ],
    COL_TURNOVER: list(TURNOVER_CATEGORY_ORDER),
    COL_TRADITION_RNP: list(TRADITION_CATEGORY_ORDER),
    COL_GENERAL_TRADITION: [
        "ОЭС 2 мл, шт.",
        "ОЭС 10 мл, шт.",
        "Никотиновые паучи, шт.",
    ],
}


@dataclass(frozen=True)
class CategoryRowSpec:
    """Строка таблицы: категория целиком или разрез внутри родительской категории."""

    label: str
    parent_category: str
    razrez: str | None
    is_slice: bool


def get_category_source_column(df: pd.DataFrame) -> str | None:
    for col in ("Категория", "Категория:"):
        if col in df.columns:
            return col
    return None


def get_razrez_source_column(df: pd.DataFrame) -> str | None:
    for col in ("Разрез", "Разрез 1"):
        if col in df.columns:
            return col
    return None


def categories_reference_valid(df: pd.DataFrame) -> bool:
    return not df.empty and get_category_source_column(df) is not None


def normalize_razrez_value(value: object) -> str:
    """Приводит значение разреза к каноническому виду (без префикса «в т.ч.»)."""
    cleaned = str(value or "").strip()
    lowered = cleaned.lower()
    if lowered.startswith(SLICE_PREFIX):
        cleaned = cleaned[len(SLICE_PREFIX) :].strip()
        if cleaned.startswith("."):
            cleaned = cleaned[1:].strip()
    return cleaned


def load_category_order_list(
    category_order_df: pd.DataFrame | None,
    column_name: str,
) -> list[str]:
    """Читает список строк из столбца category_order; при отсутствии — fallback."""
    fallback = FALLBACK_ORDERS.get(column_name, [])
    if category_order_df is None or category_order_df.empty:
        return list(fallback)
    if column_name not in category_order_df.columns:
        return list(fallback)
    values = (
        category_order_df[column_name]
        .dropna()
        .astype(str)
        .str.strip()
    )
    values = values[values.ne("")].tolist()
    return values or list(fallback)


def parse_category_order(order: list[str]) -> list[CategoryRowSpec]:
    """Разбирает порядок строк: категория или «в т.ч. <разрез>» под предыдущей категорией."""
    specs: list[CategoryRowSpec] = []
    current_parent = ""
    for raw_label in order:
        label = str(raw_label).strip()
        if not label:
            continue
        if label.lower().startswith(SLICE_PREFIX):
            razrez = normalize_razrez_value(label)
            specs.append(
                CategoryRowSpec(
                    label=label,
                    parent_category=current_parent,
                    razrez=razrez or None,
                    is_slice=True,
                )
            )
        else:
            current_parent = label
            specs.append(
                CategoryRowSpec(
                    label=label,
                    parent_category=label,
                    razrez=None,
                    is_slice=False,
                )
            )
    return specs


def collect_known_category_names(
    categories_df: pd.DataFrame,
    category_order_df: pd.DataFrame | None = None,
) -> set[str]:
    names: set[str] = set()
    cat_col = get_category_source_column(categories_df)
    if cat_col:
        names.update(
            categories_df[cat_col]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )
    if category_order_df is not None and not category_order_df.empty:
        for column in category_order_df.columns:
            names.update(load_category_order_list(category_order_df, column))
    return {name for name in names if name}


def _category_series(df: pd.DataFrame) -> pd.Series:
    if "Категория агрег." in df.columns:
        return df["Категория агрег."].fillna("").astype(str).str.strip()
    if "Категория" in df.columns:
        return df["Категория"].fillna("").astype(str).str.strip()
    return pd.Series([""] * len(df), index=df.index, dtype="string")


def _razrez_series(df: pd.DataFrame) -> pd.Series:
    for col in ("Разрез", "Разрез 1"):
        if col in df.columns:
            return df[col].fillna("").astype(str).map(normalize_razrez_value)
    return pd.Series([""] * len(df), index=df.index, dtype="string")


def resolve_spec_value(
    df: pd.DataFrame,
    spec: CategoryRowSpec,
    value_column: str = "Количество",
) -> float:
    """Считает значение для строки category_order по данным продаж."""
    if df.empty:
        return 0.0
    if value_column not in df.columns:
        return 0.0

    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    categories = _category_series(df)
    razrez = _razrez_series(df)

    if spec.is_slice:
        if not spec.razrez or not spec.parent_category:
            return 0.0
        mask = categories.eq(spec.parent_category) & razrez.eq(spec.razrez)
    else:
        mask = categories.eq(spec.parent_category)

    return float(values.loc[mask].sum())


def resolve_label_value(
    df: pd.DataFrame,
    order: list[str],
    label: str,
    value_column: str = "Количество",
) -> float:
    """Считает значение по подписи строки из category_order."""
    specs = parse_category_order(order)
    for spec in specs:
        if spec.label == label:
            return resolve_spec_value(df, spec, value_column=value_column)
    fallback = CategoryRowSpec(
        label=label,
        parent_category=label,
        razrez=None,
        is_slice=False,
    )
    return resolve_spec_value(df, fallback, value_column=value_column)


def extract_category_row_values(
    df: pd.DataFrame,
    order: list[str],
    value_column: str = "Количество",
    *,
    format_value: Callable[[float], str] | None = None,
) -> dict[str, str]:
    """Возвращает словарь {подпись строки: отформатированное значение}."""
    specs = parse_category_order(order)
    rows: dict[str, str] = {}
    for spec in specs:
        value = resolve_spec_value(df, spec, value_column=value_column)
        if format_value is not None:
            rows[spec.label] = format_value(value)
        else:
            rows[spec.label] = value
    return rows
