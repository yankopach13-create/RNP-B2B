# src/features/orders.py
from __future__ import annotations

from typing import Set

import numpy as np
import pandas as pd
import streamlit as st

from config.constants import SPECIAL_RETAIL_SUBDIVISIONS
from features.orders_metrics import calculate_orders_category_metrics

ORDERS_TRADITION_TABLE_HEIGHT = 290

REQUIRED_COLUMNS: Set[str] = {
    "Неделя",
    "Клиент",
    "Группа контрагентов",
    "Товар ур.3",
    "Количество",
}
EXCLUDED_CLIENTS = {
    'ООО "РТрейдИмпорт"',
    'ООО \"РТрейдИмпорт\"',
    "ООО «РТрейдИмпорт»",
    "ООО «РтрейдИмпорт»",
}
EXCLUDED_SUBDIVISIONS = {"Традиция"}


def render_orders_summary(
    orders_df: pd.DataFrame | None,
    contractors_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    allowed_subdivisions: set[str] | None = None,
) -> None:
    """Отрисовка блока «Заказы» на основе продаж по Товар ур.3."""
    st.subheader("Заказы")

    if orders_df is None or orders_df.empty:
        st.info("Нет данных по файлу «Продажи с начала цикла».")
        return

    missing_columns = REQUIRED_COLUMNS.difference(orders_df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        st.error(f"В файле продаж по Товар ур.3 отсутствуют обязательные столбцы: {missing}")
        return

    prepared_df, unmatched_clients = _prepare_orders_dataset(
        orders_df=orders_df,
        contractors_df=contractors_df,
        allowed_subdivisions=allowed_subdivisions,
    )

    if prepared_df.empty:
        st.info(
            "Нет заказов, соответствующих условиям отбора "
            "(Спец. розница, без исключений)."
        )
        if unmatched_clients:
            st.caption(
                "Не удалось сопоставить подразделения для клиентов: "
                + ", ".join(sorted(unmatched_clients))
            )
        return

    last_week = prepared_df["Неделя"].max()
    if pd.isna(last_week):
        st.info("Не удалось определить последнюю неделю в данных продаж.")
        return
    last_week_num = int(round(float(last_week)))

    last_week_df = prepared_df[prepared_df["Неделя"] == last_week]

    total_clients = _count_clients(prepared_df)
    last_week_clients = _count_clients(last_week_df)
    last_week_quantity = int(round(last_week_df["Количество"].sum()))

    col_total, col_last, col_qty = st.columns(3)
    _render_compact_metric(col_total, "Контрагентов с начала цикла", str(total_clients))
    _render_compact_metric(
        col_last,
        f"Контрагентов на неделе {last_week_num}",
        str(last_week_clients),
    )
    _render_compact_metric(
        col_qty,
        f"Наполненность (шт.), неделя {last_week_num}",
        f"{last_week_quantity:,}".replace(",", " "),
    )

    if unmatched_clients:
        st.caption(
            "Предупреждение: не удалось определить подразделения для клиентов — "
            + ", ".join(sorted(unmatched_clients))
        )

    metrics_table = calculate_orders_category_metrics(
        prepared_orders_df=prepared_df,
        categories_df=categories_df,
        last_week_value=last_week,
    )

    if metrics_table is not None and not metrics_table.empty:
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        st.dataframe(
            metrics_table,
            use_container_width=True,
            height=ORDERS_TRADITION_TABLE_HEIGHT,
            hide_index=True,
            column_config={
                "Контрагентов с начала цикла": st.column_config.NumberColumn(format="%d"),
                "Контрагентов на последней неделе": st.column_config.NumberColumn(format="%d"),
                "Количество последняя неделя": st.column_config.NumberColumn(format="%d"),
                "Среднее шт./клиент (посл. нед.)": st.column_config.NumberColumn(format="%.2f"),
            },
        )


def _prepare_orders_dataset(
    orders_df: pd.DataFrame,
    contractors_df: pd.DataFrame,
    allowed_subdivisions: set[str] | None = None,
) -> tuple[pd.DataFrame, set[str]]:
    df = orders_df.copy()
    df["Клиент"] = df["Клиент"].astype(str).str.strip()
    df["Группа контрагентов"] = (
        df["Группа контрагентов"].astype(str).str.strip().replace({"": "-"})
    )
    df["Неделя"] = pd.to_numeric(df["Неделя"], errors="coerce")
    df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["Неделя", "Клиент"])

    contractors = contractors_df.copy()
    contractors["Контрагент"] = contractors["Контрагент"].astype(str).str.strip()

    if "Группа контрагентов" in contractors.columns:
        contractors["Группа контрагентов"] = (
            contractors["Группа контрагентов"].astype(str).str.strip().replace({"": "-"})
        )
    elif "Сегмент" in contractors.columns:
        contractors["Группа контрагентов"] = (
            contractors["Сегмент"].astype(str).str.strip().replace({"": "-"})
        )
    else:
        contractors["Группа контрагентов"] = "-"

    contractors["Подразделение"] = (
        contractors["Подразделение"].astype(str).str.strip().replace({"": np.nan})
    )
    contractors = contractors.dropna(subset=["Контрагент"])

    contractors_map = contractors.set_index("Контрагент")["Подразделение"].to_dict()
    df["Подразделение"] = df["Клиент"].map(contractors_map)

    missing_mask = df["Подразделение"].isna() & df["Группа контрагентов"].ne("-")
    df.loc[missing_mask, "Подразделение"] = df.loc[
        missing_mask, "Группа контрагентов"
    ].map(contractors_map)

    unmatched_clients = set(
        df.loc[df["Подразделение"].isna(), "Клиент"].dropna().unique().tolist()
    )
    df = df.dropna(subset=["Подразделение"])

    allowed = (
        set(SPECIAL_RETAIL_SUBDIVISIONS)
        if allowed_subdivisions is None
        else allowed_subdivisions
    )
    filtered = df[
        df["Подразделение"].isin(allowed)
        & ~df["Подразделение"].isin(EXCLUDED_SUBDIVISIONS)
        & ~df["Клиент"].isin(EXCLUDED_CLIENTS)
    ].copy()

    filtered["Группа контрагентов"] = filtered["Группа контрагентов"].apply(
        _normalise_group_name
    )

    return filtered, unmatched_clients


def _normalise_group_name(name: str | None) -> str:
    if not isinstance(name, str):
        return "-"
    cleaned = name.strip()
    if cleaned in {"", "-", "—", "–"}:
        return "-"
    return cleaned


def _count_clients(df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    unique_pairs = (
        df[["Группа контрагентов", "Клиент"]].dropna(subset=["Клиент"]).drop_duplicates()
    )
    grouped_counts = unique_pairs.groupby("Группа контрагентов")["Клиент"].nunique()

    groups_total = grouped_counts.drop(labels="-", errors="ignore").index.size
    dash_group_clients = int(grouped_counts.get("-", 0))

    return int(groups_total + dash_group_clients)


def _render_compact_metric(container, label: str, value: str) -> None:
    container.markdown(
        (
            "<div style='padding:4px 0 0 0;'>"
            f"<div style='font-size:13px; color:#666;'>{label}</div>"
            f"<div style='font-size:22px; font-weight:600; line-height:1.2;'>{value}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )