from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List

from config.constants import (
    TURNOVER_CATEGORY_ORDER,
    MISC_SUM_COMPONENTS,
    BRAND_COMPONENTS,
)
from features.data_prep import (
    PRODUCT_COLUMNS,
    _normalise_product_columns,
    _normalise_category_name,
)


def calculate_turnover_by_category(
    turnover_df: pd.DataFrame | None,
    categories_df: pd.DataFrame,
    clients_filter: List[str] | None = None,
    period_days: int = 90,
) -> pd.DataFrame | None:
    if turnover_df is None or turnover_df.empty:
        return None

    df = turnover_df.copy()
    rename_map = {
        "Товар1": "Товар ур.1",
        "Товар 1": "Товар ур.1",
        "Товар2": "Товар ур.2",
        "Товар 2": "Товар ур.2",
        "Товар3": "Товар ур.3",
        "Товар 3": "Товар ур.3",
    }
    df = df.rename(columns=rename_map)

    product_cols_present = [col for col in PRODUCT_COLUMNS if col in df.columns]
    if not product_cols_present:
        return None

    if "Клиент" in df.columns and clients_filter:
        df = df[df["Клиент"].astype(str).isin(clients_filter)]
        if df.empty:
            return None

    df = _normalise_product_columns(df)

    categories_map = (
        categories_df[product_cols_present + ["Категория:", "Разрез 1", "Разрез 2"]]
        .drop_duplicates(subset=product_cols_present)
        .rename(columns={"Категория:": "Категория агрег."})
    )
    categories_map = _normalise_product_columns(categories_map)

    df = df.merge(
        categories_map[product_cols_present + ["Категория агрег.", "Разрез 1", "Разрез 2"]],
        how="left",
        on=product_cols_present,
    )
    df["Категория агрег."] = df["Категория агрег."].apply(_normalise_category_name)
    df["Разрез 1"] = df["Разрез 1"].fillna("")
    df["Разрез 2"] = df["Разрез 2"].fillna("")

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

    cat_group = df.groupby("Категория агрег.")[["Остаток сред.дн. (Q)", "Продажи (Q)"]].sum()
    slice1_group = df.groupby("Разрез 1")[["Остаток сред.дн. (Q)", "Продажи (Q)"]].sum()

    rows = []
    for category in TURNOVER_CATEGORY_ORDER:
        if category == "Прочие товары, шт.":
            stock = sum(
                slice1_group.loc[item, "Остаток сред.дн. (Q)"] if item in slice1_group.index else 0.0
                for item in MISC_SUM_COMPONENTS
            )
            sales = sum(
                slice1_group.loc[item, "Продажи (Q)"] if item in slice1_group.index else 0.0
                for item in MISC_SUM_COMPONENTS
            )
        elif category == "БКС, шт.":
            stock = (
                slice1_group.loc["в т.ч. БКС, шт.", "Остаток сред.дн. (Q)"]
                if "в т.ч. БКС, шт." in slice1_group.index
                else 0.0
            )
            sales = (
                slice1_group.loc["в т.ч. БКС, шт.", "Продажи (Q)"]
                if "в т.ч. БКС, шт." in slice1_group.index
                else 0.0
            )
        elif category == "Никотиновые паучи, шт.":
            stock = (
                slice1_group.loc["в т.ч. Никотиновые паучи, шт.", "Остаток сред.дн. (Q)"]
                if "в т.ч. Никотиновые паучи, шт." in slice1_group.index
                else 0.0
            )
            sales = (
                slice1_group.loc["в т.ч. Никотиновые паучи, шт.", "Продажи (Q)"]
                if "в т.ч. Никотиновые паучи, шт." in slice1_group.index
                else 0.0
            )
        else:
            stock = (
                cat_group.loc[category, "Остаток сред.дн. (Q)"] if category in cat_group.index else 0.0
            )
            sales = (
                cat_group.loc[category, "Продажи (Q)"] if category in cat_group.index else 0.0
            )

        turnover_value = _calc_turnover(stock, sales, period_days)
        rows.append({"Категория": category, "Оборачиваемость": turnover_value})

    return pd.DataFrame(rows)


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