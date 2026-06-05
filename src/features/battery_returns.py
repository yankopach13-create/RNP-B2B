# src/features/battery_returns.py
from __future__ import annotations

from typing import Set

import numpy as np
import pandas as pd
import streamlit as st

REQUIRED_COLUMNS: Set[str] = {"Контрагент"}
ALTERNATIVE_CLIENT_COLUMNS = {
    "Клиент": "Контрагент",
    "Контрагент ": "Контрагент",
}


def render_battery_returns_block(
    sales_df: pd.DataFrame | None,
    battery_clients_df: pd.DataFrame | None,
    title: str = "Возврат АКБ",
) -> None:
    """Отрисовывает блок «Возврат АКБ»."""
    st.subheader(title)

    if sales_df is None or sales_df.empty:
        st.info("Нет данных по продажам.")
        return

    if battery_clients_df is None or battery_clients_df.empty:
        st.info("Не загружен список контрагентов для возврата АКБ.")
        return

    clients_series = _extract_clients_column(battery_clients_df)
    if clients_series is None:
        st.error("Не найден столбец с контрагентами в справочнике возврата АКБ.")
        return

    clients_series = (
        clients_series.astype(str).str.strip().replace({"": np.nan}).dropna()
    )
    clients_ordered = clients_series.drop_duplicates().tolist()

    if not clients_ordered:
        st.info("Список контрагентов для возврата АКБ пуст.")
        return

    if "Клиент" not in sales_df.columns:
        st.error("В данных продаж нет столбца «Клиент» — невозможно сопоставить контрагентов.")
        return

    if "Продажи с НДС" not in sales_df.columns:
        st.error("В данных продаж нет столбца «Продажи с НДС» — нечего суммировать.")
        return

    sales = sales_df.copy()
    sales["Клиент"] = sales["Клиент"].astype(str).str.strip()
    sales["Продажи с НДС"] = pd.to_numeric(
        sales["Продажи с НДС"], errors="coerce"
    ).fillna(0.0)

    aggregated = sales.groupby("Клиент", sort=False)["Продажи с НДС"].sum()
    summary = pd.DataFrame({"Клиент": clients_ordered})
    summary["Продажи с НДС (num)"] = summary["Клиент"].map(aggregated).fillna(0.0)

    summary["Продажи с НДС"] = summary["Продажи с НДС (num)"].apply(_format_money_or_dash)

    st.dataframe(
        summary[["Клиент", "Продажи с НДС"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Продажи с НДС": st.column_config.TextColumn("Продажи с НДС"),
        },
    )

    total = summary["Продажи с НДС (num)"].sum()
    st.markdown(
        f"<div style='margin-top:10px;font-weight:600;'>Итого: {_format_money(total)}</div>",
        unsafe_allow_html=True,
    )


def render_rtrade_margin(sales_df: pd.DataFrame | None) -> None:
    """Выводит маржу контрагента Ртрейд."""
    RTRADE_CLIENTS = {
        'ООО "РТрейдИмпорт"',
        'ООО \"РТрейдИмпорт\"',
        "ООО «РТрейдИмпорт»",
        "ООО «РтрейдИмпорт»",
    }
    
    if sales_df is None or sales_df.empty:
        return
    
    if "Клиент" not in sales_df.columns:
        return
    
    if "Маржа" not in sales_df.columns:
        return
    
    sales = sales_df.copy()
    sales["Клиент"] = sales["Клиент"].astype(str).str.strip()
    sales["Маржа"] = pd.to_numeric(sales["Маржа"], errors="coerce").fillna(0.0)
    
    mask_rtrade = sales["Клиент"].isin(RTRADE_CLIENTS)
    rtrade_margin = sales.loc[mask_rtrade, "Маржа"].sum()
    
    st.markdown("---")
    st.markdown(
        f"<div style='margin-top:10px;font-weight:600;'>Маржа Ртрейд: {_format_money(rtrade_margin)}</div>",
        unsafe_allow_html=True,
    )


def _extract_clients_column(df: pd.DataFrame) -> pd.Series | None:
    columns = {col.strip(): col for col in df.columns}

    for candidate in REQUIRED_COLUMNS:
        if candidate in columns:
            return df[columns[candidate]]

    for alt, target in ALTERNATIVE_CLIENT_COLUMNS.items():
        if alt in columns:
            return df[columns[alt]].rename(target)

    return None


def _format_money(value: float | int | None) -> str:
    if value is None:
        return "0,00"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0,00"
    return f"{numeric:,.2f}".replace(",", " ").replace(".", ",")


def _format_money_or_dash(value: float | int | None) -> str:
    if value is None or np.isclose(float(value), 0.0):
        return "-"
    return _format_money(value)