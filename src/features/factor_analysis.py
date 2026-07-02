# src/features/factor_analysis.py
from __future__ import annotations
from typing import Iterable
import numpy as np
import pandas as pd
import streamlit as st

from features.category_order import (
    COL_SPEC_RNP,
    category_labels_only,
    collect_known_category_names,
    load_category_order_list,
    parse_category_order,
    resolve_spec_value,
)
from features.data_prep import (
    PRODUCT_COLUMNS,
    _build_categories_map,
    _normalise_category_name,
    _normalise_product_columns,
)

RTRADE_CLIENTS = {
    'ООО "РТрейдИмпорт"',
    'ООО \"РТрейдИмпорт\"',
    "ООО «РТрейдИмпорт»",
    "ООО «РтрейдИмпорт»",
}

def render_factor_analysis(
    sales_df: pd.DataFrame | None,
    contractors_df: pd.DataFrame | None,
    category_order_df: pd.DataFrame | None = None,
) -> None:
    """Рисует блок «Факторный анализ» одной сводной таблицей."""
    st.markdown("**Факторный анализ**")
    if sales_df is None or sales_df.empty:
        st.info("Нет данных по Спец. рознице для расчёта факторного анализа.")
        return
    prepared_df = _prepare_factor_base(sales_df)
    if prepared_df is None:
        return

    order = load_category_order_list(category_order_df, COL_SPEC_RNP)
    table = _build_factor_table(prepared_df, order)
    st.dataframe(
        table,
        use_container_width=True,
        height=_table_height_from_rows(3),
        hide_index=True,
        column_config={
            "Значение": st.column_config.TextColumn("Значение"),
        },
    )


def _build_factor_table(df: pd.DataFrame, category_order: list[str]) -> pd.DataFrame:
    segment_rows = _build_segment_rows(df)
    quantity_rows = _build_category_rows(
        df, value_column="Количество", category_order=category_order
    )
    revenue_rows = _build_category_rows(
        df, value_column="Продажи с НДС", category_order=category_order
    )

    rows: list[dict[str, str]] = []
    for idx, row in enumerate(segment_rows):
        rows.append(row)
        if idx < len(segment_rows) - 1:
            rows.append({"Показатель": "", "Значение": ""})
    rows.extend([{"Показатель": "", "Значение": ""} for _ in range(3)])
    rows.extend(quantity_rows)
    rows.append({"Показатель": "", "Значение": ""})
    rows.extend(revenue_rows)
    return pd.DataFrame(rows)


def _build_segment_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    mask_rtrade = df["Клиент"].isin(RTRADE_CLIENTS)
    rtrade_sales = float(df.loc[mask_rtrade, "Продажи с НДС"].sum())
    non_rtrade = df.loc[~mask_rtrade].copy()

    a_sales = _sum_by_segment(non_rtrade, {"A"})
    b_sales = _sum_by_segment(non_rtrade, {"B"})
    c_lost_sales = _sum_by_segment(non_rtrade, {"C", "LOST"})
    return [
        {"Показатель": "Выручка Ртрейд", "Значение": _format_money(rtrade_sales)},
        {"Показатель": "Выручка A сегмента", "Значение": _format_money(a_sales)},
        {"Показатель": "Выручка B сегмента", "Значение": _format_money(b_sales)},
        {"Показатель": "Выручка C сегмента", "Значение": _format_money(c_lost_sales)},
    ]


def _build_category_rows(
    df: pd.DataFrame,
    value_column: str,
    category_order: list[str],
) -> list[dict[str, str]]:
    specs = parse_category_order(category_labels_only(category_order))
    rows: list[dict[str, str]] = []
    for spec in specs:
        value = resolve_spec_value(df, spec, value_column=value_column)
        if value_column == "Количество":
            value_formatted = _format_quantity(value)
        else:
            value_formatted = _format_money(value)
        rows.append({"Показатель": spec.label, "Значение": value_formatted})
    return rows


def _prepare_factor_base(sales_df: pd.DataFrame) -> pd.DataFrame | None:
    required = {"Клиент", "Сегмент", "Продажи с НДС", "Количество"}
    missing = sorted(required.difference(sales_df.columns))
    if missing:
        st.warning(
            "В данных нет обязательных столбцов для факторного анализа: "
            + ", ".join(missing)
        )
        return None

    df = sales_df.copy()
    df["Клиент"] = df["Клиент"].astype(str).str.strip()
    df["Сегмент"] = (
        df["Сегмент"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
        .str.translate(str.maketrans({"А": "A", "В": "B", "С": "C"}))
    )
    df["Продажи с НДС"] = pd.to_numeric(df["Продажи с НДС"], errors="coerce").fillna(0.0)
    df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0.0)

    if "Категория агрег." not in df.columns or "Разрез" not in df.columns:
        categories_df = st.session_state.get("categories_df")
        if categories_df is None:
            st.warning("Справочник категорий не загружен.")
            return None
        category_order_df = st.session_state.get("category_order_df")
        df = _merge_categories(df, categories_df, category_order_df)

    if "Товар ур.3" in df.columns:
        df["Товар ур.3_lower"] = df["Товар ур.3"].astype(str).str.lower().str.strip()
        oes_10_mask = (
            df["Товар ур.3_lower"].str.contains("dragbar 6000", case=False, na=False)
            | df["Товар ур.3_lower"].str.contains("1.9 fill x", case=False, na=False)
        )
        df.loc[oes_10_mask, "Категория агрег."] = "ОЭС 10 мл, шт."
        oes_2_original_mask = df["Категория агрег."] == "ОЭС 2 мл, шт."
        df.loc[oes_2_original_mask & oes_10_mask, "Категория агрег."] = "ОЭС 10 мл, шт."

    return df


def _merge_categories(
    sales_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    category_order_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    sales_prep = _normalise_product_columns(sales_df.copy())
    known_categories = collect_known_category_names(
        categories_df, category_order_df
    )
    categories_map = _build_categories_map(categories_df)
    categories_map["Категория агрег."] = categories_map["Категория raw"].apply(
        lambda name: _normalise_category_name(name, known_categories)
    )

    merged = sales_prep.merge(
        categories_map[PRODUCT_COLUMNS + ["Категория агрег.", "Разрез"]].drop_duplicates(),
        on=PRODUCT_COLUMNS,
        how="left",
    )
    merged["Категория агрег."] = (
        merged["Категория агрег."]
        .fillna("Прочие товары, шт.:")
        .apply(lambda name: _normalise_category_name(name, known_categories))
    )
    merged["Разрез"] = merged["Разрез"].fillna("").astype(str).str.strip()
    return merged

def _sum_by_segment(df: pd.DataFrame, codes: Iterable[str]) -> float:
    if df.empty:
        return 0.0
    codes_norm = {code.upper().strip() for code in codes}
    mask = df["Сегмент"].isin(codes_norm)
    return float(df.loc[mask, "Продажи с НДС"].sum())

def _format_money(value: float | int | None) -> str:
    if value is None:
        return "0,00"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0,00"
    return f"{numeric:,.2f}".replace(",", " ").replace(".", ",")


def _format_quantity(value: float | int | None) -> str:
    if value is None:
        return "0"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0"
    return f"{int(round(numeric)):,}".replace(",", " ")


def _table_height_from_rows(rows_count: int) -> int:
    header_height = 36
    row_height = 35
    padding = 2
    min_height = 140
    return max(min_height, header_height + rows_count * row_height + padding)
