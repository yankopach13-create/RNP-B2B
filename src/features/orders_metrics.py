from __future__ import annotations
from typing import Iterable, List, Literal
import numpy as np
import pandas as pd
from features.data_prep import _normalise_category_name

CATEGORY_TARGETS: List[dict[str, str | Literal["category", "slice1"]]] = [
    {"label": "ОЭС 2 мл, шт.", "kind": "category", "value": "ОЭС 2 мл, шт."},
    {"label": "ОЭС 10 мл, шт.", "kind": "category", "value": "ОЭС 10 мл, шт."},
    {"label": "Жидкость 25 мл, шт.", "kind": "category", "value": "Жидкость 25 мл, шт."},
    {"label": "Pod-системы, шт.", "kind": "category", "value": "Pod-системы, шт."},
    {"label": "Расходники, шт.", "kind": "category", "value": "Расходники, шт."},
    {"label": "БКС, шт.", "kind": "slice1", "value": "в т.ч. БКС, шт."},
    {"label": "Никотиновые паучи, шт.", "kind": "slice1", "value": "в т.ч. Никотиновые паучи, шт."},
]

def calculate_orders_category_metrics(
    prepared_orders_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    last_week_value: float | int,
) -> pd.DataFrame | None:
    if prepared_orders_df.empty or categories_df.empty:
        return None

    product_col = _detect_product_level_column(prepared_orders_df)
    if product_col is None:
        return None

    if product_col not in categories_df.columns:
        return None

    mapping = (
        categories_df[[product_col, "Категория:", "Разрез 1"]]
        .dropna(subset=[product_col])
        .copy()
    )
    mapping[product_col] = mapping[product_col].astype(str).str.strip()
    mapping["Категория агрег."] = mapping["Категория:"].apply(_normalise_category_name)
    mapping["Разрез 1"] = mapping["Разрез 1"].fillna("").astype(str).str.strip()
    mapping = mapping.drop_duplicates(subset=[product_col])

    df = prepared_orders_df.copy()
    df[product_col] = df[product_col].astype(str).str.strip()
    df = df.merge(
        mapping[[product_col, "Категория агрег.", "Разрез 1"]],
        how="left",
        on=product_col,
    )
    df["Категория агрег."] = df["Категория агрег."].fillna("")
    df["Разрез 1"] = df["Разрез 1"].fillna("")

    last_week_df = df[df["Неделя"] == last_week_value]

    rows: List[dict[str, object]] = []
    for target in CATEGORY_TARGETS:
        subset_all = _slice_by_target(df, target)
        subset_last = _slice_by_target(last_week_df, target)
        total_clients = _count_clients(subset_all)
        last_week_clients = _count_clients(subset_last)
        last_week_qty = float(subset_last["Количество"].sum())
        avg_per_client = (
            last_week_qty / last_week_clients if last_week_clients else 0.0
        )
        rows.append(
            {
                "Категория": target["label"],
                "Контрагентов с начала цикла": int(total_clients),
                "Контрагентов на последней неделе": int(last_week_clients),
                "Среднее шт./клиент (посл. нед.)": int(round(avg_per_client)),
            }
        )
    result = pd.DataFrame(rows)
    return result


def _detect_product_level_column(df: pd.DataFrame) -> str | None:
    if "Товар ур.3" in df.columns:
        return "Товар ур.3"
    if "Товар ур.2" in df.columns:
        return "Товар ур.2"
    return None

def _slice_by_target(df: pd.DataFrame, target: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return df
    if target["kind"] == "category":
        return df[df["Категория агрег."].astype(str) == target["value"]]
    return df[df["Разрез 1"].astype(str) == target["value"]]

def _count_clients(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    unique_pairs = (
        df[["Группа контрагентов", "Клиент"]]
        .dropna(subset=["Клиент"])
        .drop_duplicates()
    )
    grouped_counts = unique_pairs.groupby("Группа контрагентов")["Клиент"].nunique()
    groups_total = grouped_counts.drop(labels="-", errors="ignore").index.size
    dash_group_clients = int(grouped_counts.get("-", 0))
    return int(groups_total + dash_group_clients)