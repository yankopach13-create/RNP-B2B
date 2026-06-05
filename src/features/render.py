# src/features/render.py
from __future__ import annotations

from typing import Callable, Iterable

import numpy as np
import pandas as pd
import streamlit as st

from config.constants import (
    BRAND_COMPONENTS,
    CATEGORY_DISPLAY_ORDER,
    MISC_SUM_COMPONENTS,
    SUBDIVISION_ORDER,
    TURNOVER_CATEGORY_ORDER,
)
from features.turnover import (
    calculate_turnover_by_category,
    format_turnover_value,
    has_turnover_data,
)

ORDERS_TRADITION_TABLE_HEIGHT = 290


def render_section(
    title: str,
    dataframe: pd.DataFrame,
    categories_df: pd.DataFrame,
    turnover_90_df: pd.DataFrame | None = None,
    turnover_7_df: pd.DataFrame | None = None,
    color: str | None = None,
    use_expander: bool = False,
    category_order: list[str] | None = None,
    include_overall: bool = True,
    show_turnover: bool = True,
    aggregates: dict[str, list[str]] | None = None,
    split_finance_categories: bool = False,
    combine_finance_categories: bool = False,
    overall_margin_adjustment: float = 0.0,
) -> None:
    aggregates = aggregates or {}

    box_style = "" if color is None else f"background-color:{color};"
    if use_expander:
        container = st.expander(title)
        header_html = ""
    else:
        container = st.container()
        if title.strip():
            header_html = (
                f'<div style="{box_style} padding:10px 14px; border-radius:8px; '
                f'margin-bottom:12px; font-weight:600;">{title}</div>'
            )
        else:
            header_html = ""

    with container:
        if header_html:
            st.markdown(header_html, unsafe_allow_html=True)

        subdivisions = _collect_subdivisions(
            dataframe, aggregate_names=aggregates.keys()
        )

        if split_finance_categories:
            col_finance, col_categories = st.columns([1, 1])
            with col_finance:
                st.markdown("**Финансовые метрики**")
                overall_metrics_table = build_financial_metrics_vertical_table(
                    dataframe,
                    [],
                    include_overall=True,
                    aggregates=aggregates,
                    overall_margin_adjustment=overall_margin_adjustment,
                )
                subdivisions_metrics_table = build_financial_metrics_vertical_table(
                    dataframe,
                    subdivisions,
                    include_overall=False,
                    aggregates=aggregates,
                )
                overall_category_table = build_category_vertical_table(
                    dataframe,
                    category_order=category_order,
                    subdivisions=[],
                    include_overall=True,
                    aggregates=aggregates,
                )
                subdivisions_category_table = build_category_vertical_table(
                    dataframe,
                    category_order=category_order,
                    subdivisions=subdivisions,
                    include_overall=False,
                    aggregates=aggregates,
                    spacer_between_groups=True,
                )
                visible_rows = 3
                overall_height = _table_height_from_rows(visible_rows)
                subdivisions_height = _table_height_from_rows(visible_rows)
                st.markdown("**Общие**")
                st.dataframe(
                    overall_metrics_table,
                    use_container_width=True,
                    height=overall_height,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in overall_metrics_table.columns
                    },
                )
                st.markdown("**Подразделения**")
                st.dataframe(
                    subdivisions_metrics_table,
                    use_container_width=True,
                    height=subdivisions_height,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in subdivisions_metrics_table.columns
                    },
                )
            with col_categories:
                st.markdown("**Продажи по категориям (шт.)**")
                st.markdown("**Общие**")
                st.dataframe(
                    overall_category_table,
                    use_container_width=True,
                    height=overall_height,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in overall_category_table.columns
                    },
                )
                st.markdown("**Подразделения**")
                st.dataframe(
                    subdivisions_category_table,
                    use_container_width=True,
                    height=subdivisions_height,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in subdivisions_category_table.columns
                    },
                )
        else:
            # --- Финансовые метрики -------------------------------------------------
            metrics_table = build_financial_metrics_table(
                dataframe,
                subdivisions,
                include_overall=include_overall,
                aggregates=aggregates,
                overall_margin_adjustment=overall_margin_adjustment,
            )
            category_table = build_category_table(
                dataframe,
                category_order=category_order,
                subdivisions=subdivisions,
                include_overall=include_overall,
                aggregates=aggregates,
            )
            if combine_finance_categories:
                combined_table = build_combined_finance_categories_table(
                    metrics_table, category_table
                )
                st.dataframe(
                    combined_table,
                    use_container_width=True,
                    height=ORDERS_TRADITION_TABLE_HEIGHT,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in combined_table.columns
                        if col != "Показатель"
                    },
                )
            else:
                st.markdown("**Финансовые метрики**")
                st.dataframe(
                    metrics_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in metrics_table.columns
                        if col != "Метрика"
                    },
                )

                # --- Продажи по категориям ---------------------------------------------
                st.markdown("**Продажи по категориям (шт.)**")
                st.dataframe(
                    category_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        col: st.column_config.TextColumn(col)
                        for col in category_table.columns
                        if col != "Категория"
                    },
                )

        # --- Оборачиваемость ---------------------------------------------------
        if show_turnover:
            render_turnover_block(
                dataframe=dataframe,
                categories_df=categories_df,
                turnover_90_df=turnover_90_df,
                turnover_7_df=turnover_7_df,
            )


def render_turnover_block(
    dataframe: pd.DataFrame,
    categories_df: pd.DataFrame,
    turnover_90_df: pd.DataFrame | None = None,
    turnover_7_df: pd.DataFrame | None = None,
    visible_rows: int = 3,
) -> None:
    clients_filter = (
        dataframe["Клиент"].dropna().astype(str).unique().tolist()
        if "Клиент" in dataframe.columns
        else None
    )
    turnover_90_table = calculate_turnover_by_category(
        turnover_df=turnover_90_df,
        categories_df=categories_df,
        clients_filter=clients_filter,
        period_days=90,
    )
    turnover_7_table = calculate_turnover_by_category(
        turnover_df=turnover_7_df,
        categories_df=categories_df,
        clients_filter=clients_filter,
        period_days=7,
    )

    st.markdown("**Оборачиваемость запасов (дни)**")
    if has_turnover_data(turnover_90_table) or has_turnover_data(turnover_7_table):
        turnover_table = build_turnover_table(turnover_90_table, turnover_7_table)
        st.dataframe(
            turnover_table,
            use_container_width=True,
            height=_table_height_from_rows(visible_rows),
            hide_index=True,
            column_config={
                "90 дней": st.column_config.TextColumn("90 дней"),
                "7 дней": st.column_config.TextColumn("7 дней"),
            },
        )
    else:
        st.info("Нет данных по оборачиваемости.")


def render_new_clients(new_clients: list[str]) -> None:
    if not new_clients:
        return
    styled = ", ".join(sorted(new_clients))
    st.warning(
        f"Новые клиенты без привязки к подразделению: {styled}", icon="🆕"
    )


def render_new_products(unmatched_products: list[tuple[str, str, str]]) -> None:
    """Выводит товары, которые не найдены в справочнике категорий."""
    if not unmatched_products:
        return
    
    # Format products as "Товар ур.1 / Товар ур.2 / Товар ур.3"
    formatted_products = []
    for prod1, prod2, prod3 in unmatched_products:
        parts = [p for p in [prod1, prod2, prod3] if p and p != "__NONE__"]
        if parts:
            formatted_products.append(" / ".join(parts))
    
    if not formatted_products:
        return
    
    styled = ", ".join(sorted(formatted_products))
    st.warning(
        f"Товары, не найденные в справочнике категорий: {styled}", icon="📦"
    )


# ------------------------------------------------------------------------------
# Таблицы
# ------------------------------------------------------------------------------


def build_financial_metrics_table(
    df: pd.DataFrame,
    subdivisions: list[str],
    include_overall: bool = True,
    aggregates: dict[str, list[str]] | None = None,
    overall_margin_adjustment: float = 0.0,
) -> pd.DataFrame:
    aggregates = aggregates or {}
    subset_cache = {
        subdivision: _get_subset_df(df, subdivision, aggregates)
        for subdivision in subdivisions
    }

    rows: list[dict[str, object]] = []
    metrics = (("Продажи с НДС", "Продажи с НДС"), ("Маржа", "Маржа"))

    for label, column_name in metrics:
        if column_name not in df.columns:
            continue
        row = {"Метрика": label}

        if include_overall:
            total_value = float(df[column_name].sum())
            if column_name == "Маржа" and overall_margin_adjustment:
                total_value -= overall_margin_adjustment
            row["Общие"] = _format_money(total_value)

        for subdivision in subdivisions:
            sub_df = subset_cache[subdivision]
            sub_value = float(sub_df[column_name].sum())
            row[subdivision] = _format_money(sub_value)

        rows.append(row)

    if "Продажи с НДС" in df.columns and "Маржа" in df.columns:
        pct_row = {"Метрика": "% МД"}
        if include_overall:
            total_sales_wo_vat = float(df["Продажи с НДС"].sum()) / 1.2
            total_margin = float(df["Маржа"].sum())
            if overall_margin_adjustment:
                total_margin -= overall_margin_adjustment
            total_pct = (
                (total_margin / total_sales_wo_vat) * 100
                if not np.isclose(total_sales_wo_vat, 0.0)
                else 0.0
            )
            pct_row["Общие"] = _format_percent(total_pct)

        for subdivision in subdivisions:
            sub_df = subset_cache[subdivision]
            sub_sales_wo_vat = float(sub_df["Продажи с НДС"].sum()) / 1.2
            sub_margin = float(sub_df["Маржа"].sum())
            sub_pct = (
                (sub_margin / sub_sales_wo_vat) * 100
                if not np.isclose(sub_sales_wo_vat, 0.0)
                else 0.0
            )
            pct_row[subdivision] = _format_percent(sub_pct)

        rows.append(pct_row)

    return pd.DataFrame(rows)


def build_financial_metrics_vertical_table(
    df: pd.DataFrame,
    subdivisions: list[str],
    include_overall: bool = True,
    aggregates: dict[str, list[str]] | None = None,
    format_money: Callable[[float | int | None], str] | None = None,
    overall_margin_adjustment: float = 0.0,
) -> pd.DataFrame:
    aggregates = aggregates or {}
    money_fmt = format_money if format_money is not None else _format_money
    subset_cache = {
        subdivision: _get_subset_df(df, subdivision, aggregates)
        for subdivision in subdivisions
    }

    groups: list[tuple[str, pd.DataFrame]] = []
    if include_overall:
        groups.append(("Общие", df))
    for subdivision in subdivisions:
        groups.append((subdivision, subset_cache[subdivision]))

    no_spacer_after_groups = {
        "Минская область",
        "МО Смирнов",
        "МО Навитанюк",
        "МО Бондаренко",
    }

    rows: list[dict[str, str]] = []
    for idx, (group_name, group_df) in enumerate(groups):
        sales = float(group_df["Продажи с НДС"].sum()) if "Продажи с НДС" in group_df.columns else 0.0
        margin = float(group_df["Маржа"].sum()) if "Маржа" in group_df.columns else 0.0
        if group_name == "Общие" and overall_margin_adjustment:
            margin -= overall_margin_adjustment
        sales_wo_vat = sales / 1.2
        md_percent = (
            (margin / sales_wo_vat) * 100 if not np.isclose(sales_wo_vat, 0.0) else 0.0
        )

        rows.append(
            {
                "Группа": group_name,
                "Показатель": "Продажи с НДС",
                "Значение": money_fmt(sales),
            }
        )
        rows.append(
            {
                "Группа": "",
                "Показатель": "Маржа",
                "Значение": money_fmt(margin),
            }
        )
        rows.append(
            {
                "Группа": "",
                "Показатель": "% МД",
                "Значение": _format_percent(md_percent),
            }
        )

        if idx < len(groups) - 1 and group_name not in no_spacer_after_groups:
            rows.append({"Группа": "", "Показатель": "", "Значение": ""})

    return pd.DataFrame(rows)


def build_category_table(
    df: pd.DataFrame,
    category_order: list[str] | None = None,
    subdivisions: list[str] | None = None,
    include_overall: bool = True,
    aggregates: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    aggregates = aggregates or {}
    if category_order is None:
        category_order = CATEGORY_DISPLAY_ORDER
    if subdivisions is None:
        subdivisions = []

    subset_cache = {
        subdivision: _get_subset_df(df, subdivision, aggregates)
        for subdivision in subdivisions
    }

    overall_series = _prepare_category_series(df)
    subset_series = {
        subdivision: _prepare_category_series(sub_df)
        for subdivision, sub_df in subset_cache.items()
    }

    rows: list[dict[str, object]] = []
    for category in category_order:
        row = {"Категория": category}

        if include_overall:
            overall_value = _resolve_category_value(category, *overall_series)
            row["Общие"] = _format_quantity(overall_value)

        for subdivision in subdivisions:
            cat_series, slice1_series, slice2_series = subset_series[subdivision]
            value = _resolve_category_value(
                category, cat_series, slice1_series, slice2_series
            )
            row[subdivision] = _format_quantity(value)

        rows.append(row)

    return pd.DataFrame(rows)


def build_category_vertical_table(
    df: pd.DataFrame,
    category_order: list[str] | None = None,
    subdivisions: list[str] | None = None,
    include_overall: bool = True,
    aggregates: dict[str, list[str]] | None = None,
    spacer_between_groups: bool = False,
) -> pd.DataFrame:
    aggregates = aggregates or {}
    if category_order is None:
        category_order = CATEGORY_DISPLAY_ORDER
    if subdivisions is None:
        subdivisions = []

    subset_cache = {
        subdivision: _get_subset_df(df, subdivision, aggregates)
        for subdivision in subdivisions
    }

    groups: list[tuple[str, pd.DataFrame]] = []
    if include_overall:
        groups.append(("Общие", df))
    for subdivision in subdivisions:
        groups.append((subdivision, subset_cache[subdivision]))

    rows: list[dict[str, str]] = []
    for idx, (group_name, group_df) in enumerate(groups):
        cat_series, slice1_series, slice2_series = _prepare_category_series(group_df)
        for cat_idx, category in enumerate(category_order):
            value = _resolve_category_value(
                category, cat_series, slice1_series, slice2_series
            )
            rows.append(
                {
                    "Группа": group_name if cat_idx == 0 else "",
                    "Категория": category,
                    "Значение": _format_quantity(value),
                }
            )

        if spacer_between_groups and idx < len(groups) - 1:
            rows.append({"Группа": "", "Категория": "", "Значение": ""})

    return pd.DataFrame(rows)


def build_turnover_table(
    turnover_90_table: pd.DataFrame | None,
    turnover_7_table: pd.DataFrame | None,
) -> pd.DataFrame:
    categories_set: set[str] = set()
    if has_turnover_data(turnover_90_table):
        categories_set.update(turnover_90_table["Категория"].tolist())
    if has_turnover_data(turnover_7_table):
        categories_set.update(turnover_7_table["Категория"].tolist())

    if not categories_set:
        return pd.DataFrame(columns=["Категория", "90 дней", "7 дней"])

    ordered_categories = [
        cat for cat in TURNOVER_CATEGORY_ORDER if cat in categories_set
    ]
    remaining = sorted(categories_set - set(ordered_categories))
    categories = ordered_categories + remaining

    rows: list[dict[str, object]] = []
    for category in categories:
        row = {"Категория": category}

        if has_turnover_data(turnover_90_table):
            series_90 = turnover_90_table.loc[
                turnover_90_table["Категория"] == category, "Оборачиваемость"
            ]
            value_90 = np.nan if series_90.empty else series_90.iloc[0]
            row["90 дней"] = (
                "-"
                if value_90 is None or pd.isna(value_90)
                else format_turnover_value(value_90)
            )
        else:
            row["90 дней"] = "-"

        if has_turnover_data(turnover_7_table):
            series_7 = turnover_7_table.loc[
                turnover_7_table["Категория"] == category, "Оборачиваемость"
            ]
            value_7 = np.nan if series_7.empty else series_7.iloc[0]
            row["7 дней"] = (
                "-"
                if value_7 is None or pd.isna(value_7)
                else format_turnover_value(value_7)
            )
        else:
            row["7 дней"] = "-"

        rows.append(row)

    return pd.DataFrame(rows)


def build_combined_finance_categories_table(
    metrics_table: pd.DataFrame, category_table: pd.DataFrame
) -> pd.DataFrame:
    left_label_col = "Показатель"
    value_columns = [col for col in metrics_table.columns if col != "Метрика"]
    if not value_columns:
        value_columns = [col for col in category_table.columns if col != "Категория"]

    metrics_part = metrics_table.rename(columns={"Метрика": left_label_col}).copy()
    categories_part = category_table.rename(columns={"Категория": left_label_col}).copy()

    target_columns = [left_label_col] + value_columns
    metrics_part = metrics_part.reindex(columns=target_columns, fill_value="")
    categories_part = categories_part.reindex(columns=target_columns, fill_value="")

    spacer = pd.DataFrame(
        [{left_label_col: "", **{col: "" for col in value_columns}} for _ in range(2)]
    )
    return pd.concat([metrics_part, spacer, categories_part], ignore_index=True)


# ------------------------------------------------------------------------------
# Вспомогательные функции
# ------------------------------------------------------------------------------


def _collect_subdivisions(
    df: pd.DataFrame, aggregate_names: Iterable[str] | None = None
) -> list[str]:
    available: set[str] = set()
    if "Подразделение" in df.columns:
        available.update(
            df["Подразделение"]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
        )
    if aggregate_names:
        available.update(aggregate_names)

    ordered = [sub for sub in SUBDIVISION_ORDER if sub in available]
    others = sorted(available - set(ordered))

    return ordered + others


def _get_subset_df(
    df: pd.DataFrame, subdivision: str, aggregates: dict[str, list[str]]
) -> pd.DataFrame:
    if aggregates and subdivision in aggregates:
        components = aggregates[subdivision]
        return df[df["Подразделение"].isin(components)]
    return df[df["Подразделение"] == subdivision]


def _prepare_category_series(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if df.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    quantity_by_category = df.groupby("Категория агрег.")["Количество"].sum()
    quantity_by_slice1 = df.groupby("Разрез 1")["Количество"].sum()
    quantity_by_slice2 = df.groupby("Разрез 2")["Количество"].sum()

    return quantity_by_category, quantity_by_slice1, quantity_by_slice2


def _resolve_category_value(
    category: str,
    by_category: pd.Series,
    by_slice1: pd.Series,
    by_slice2: pd.Series,
) -> float:
    if category == "Прочие товары, шт.:":
        return sum(by_slice1.get(item, 0.0) for item in MISC_SUM_COMPONENTS)

    if category in MISC_SUM_COMPONENTS:
        return float(by_slice1.get(category, 0.0))

    if category == "Никотиновые паучи, шт.":
        return float(by_slice1.get("в т.ч. Никотиновые паучи, шт.", 0.0))

    if category in BRAND_COMPONENTS:
        return float(by_slice2.get(category, 0.0))

    return float(by_category.get(category, 0.0))


def _format_money(value: float | int | None) -> str:
    if value is None:
        return "0,00"
    numeric = float(value)
    if np.isclose(numeric, 0.0):
        return "0,00"
    return f"{numeric:,.2f}".replace(",", " ").replace(".", ",")


def _format_money_compact(value: float | int | None) -> str:
    """Денежный формат без разделителя тысяч (удобно копировать в Google Sheets)."""
    if value is None:
        return "0,00"
    numeric = float(value)
    if np.isclose(numeric, 0.0):
        return "0,00"
    return f"{numeric:.2f}".replace(".", ",")


def _format_quantity(value: float | int | None) -> str:
    if value is None:
        return ""
    numeric = float(value)
    if np.isclose(numeric, 0.0):
        return ""
    return f"{int(round(numeric)):,}".replace(",", " ")


def _format_quantity_compact(value: float | int | None) -> str:
    """Целое количество без разделителя тысяч (копирование в Google Sheets)."""
    if value is None:
        return ""
    numeric = float(value)
    if np.isclose(numeric, 0.0):
        return ""
    return str(int(round(numeric)))


def _format_percent(value: float | int | None) -> str:
    if value is None:
        return "0,0%"
    numeric = float(value)
    if np.isclose(numeric, 0.0):
        return "0,0%"
    return f"{numeric:.1f}".replace(".", ",") + "%"


def _table_height_from_rows(rows_count: int) -> int:
    header_height = 36
    row_height = 35
    padding = 2
    min_height = 140
    return max(min_height, header_height + rows_count * row_height + padding)