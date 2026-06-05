# src/features/tradition.py

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

CATEGORY_CONFIG = [
    {"label": "ОЭС 2 мл, шт.", "kind": "category", "value": "ОЭС 2 мл, шт."},
    {"label": "ОЭС 10 мл, шт.", "kind": "category", "value": "ОЭС 10 мл, шт."},
    {"label": "Картриджи с жидкостью, шт.", "kind": "category", "value": "Картриджи с жидкостью, шт."},
    {"label": "Никотиновые паучи, шт.", "kind": "product1", "value": "3.5 Никотиновые паучи"},
]


def render_tradition_block(merged_df: pd.DataFrame | None) -> None:
    """Отрисовывает блок «Традиция»: продажи, маржу и продажи по категориям в штуках."""
    st.subheader("Традиция")

    if merged_df is None or merged_df.empty:
        st.info("Нет данных для подразделения «Традиция».")
        return

    required_cols = {"Подразделение", "Продажи с НДС", "Маржа", "Количество"}
    missing_cols = required_cols.difference(merged_df.columns)
    if missing_cols:
        st.warning(
            "Не хватает столбцов для расчёта блока «Традиция»: "
            + ", ".join(sorted(missing_cols))
        )
        return

    tradition_df = merged_df[merged_df["Подразделение"] == "Традиция"].copy()
    if tradition_df.empty:
        st.info("В данных нет продаж подразделения «Традиция».")
        return

    tradition_df["Продажи с НДС"] = pd.to_numeric(
        tradition_df["Продажи с НДС"], errors="coerce"
    ).fillna(0.0)
    tradition_df["Маржа"] = pd.to_numeric(
        tradition_df["Маржа"], errors="coerce"
    ).fillna(0.0)
    tradition_df["Количество"] = pd.to_numeric(
        tradition_df["Количество"], errors="coerce"
    ).fillna(0.0)

    total_sales = float(tradition_df["Продажи с НДС"].sum())
    total_margin = float(tradition_df["Маржа"].sum())

    col_sales, col_margin = st.columns(2)
    col_sales.metric("Продажи с НДС", _format_money(total_sales))
    col_margin.metric("Маржа", _format_money(total_margin))

    for col in ["Категория агрег.", "Разрез 1"]:
        if col not in tradition_df.columns:
            tradition_df[col] = ""

    rows: list[dict[str, object]] = []
    for cfg in CATEGORY_CONFIG:
        subset = _slice_by_config(tradition_df, cfg)
        qty = int(round(subset["Количество"].sum())) if not subset.empty else 0
        rows.append({"Категория": cfg["label"], "Продажи, шт.": qty if qty else 0})

    table = pd.DataFrame(rows)
    table["Продажи, шт."] = table["Продажи, шт."].apply(
        lambda x: "" if x == 0 else f"{x:,}".replace(",", " ")
    )

    st.markdown("**Продажи по категориям (шт.)**")
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Продажи, шт.": st.column_config.TextColumn("Продажи, шт.")
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _slice_by_config(df: pd.DataFrame, cfg: dict[str, str]) -> pd.DataFrame:
    if cfg["kind"] == "category":
        return df[df["Категория агрег."].astype(str) == cfg["value"]]
    if cfg["kind"] == "slice1":
        return df[df["Разрез 1"].astype(str) == cfg["value"]]
    if cfg["kind"] == "product1":
        return df[df["Товар ур.1"].astype(str) == cfg["value"]]
    return df.head(0)


def _format_money(value: float | int | None) -> str:
    if value is None:
        return "0,00"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return f"{numeric:,.2f}".replace(",", " ").replace(".", ",")