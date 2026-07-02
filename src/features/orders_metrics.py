from __future__ import annotations
from typing import List
import pandas as pd

from features.category_order import (
    COL_SPEC_RNP,
    CategoryRowSpec,
    collect_known_category_names,
    get_category_source_column,
    get_razrez_source_column,
    load_category_order_list,
    match_spec_mask,
    normalize_razrez_value,
    parse_category_order,
)
from features.data_prep import _normalise_category_name


def calculate_orders_category_metrics(
    prepared_orders_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    last_week_value: float | int,
    category_order_df: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    if prepared_orders_df.empty or categories_df.empty:
        return None

    product_col = _detect_product_level_column(prepared_orders_df)
    if product_col is None:
        return None

    if product_col not in categories_df.columns:
        return None

    cat_col = get_category_source_column(categories_df)
    if cat_col is None:
        return None

    known_categories = collect_known_category_names(
        categories_df, category_order_df
    )
    razrez_col = get_razrez_source_column(categories_df)
    mapping_cols = [product_col, cat_col]
    if razrez_col:
        mapping_cols.append(razrez_col)
    mapping = categories_df[mapping_cols].dropna(subset=[product_col]).copy()
    mapping[product_col] = mapping[product_col].astype(str).str.strip()
    mapping["Категория агрег."] = mapping[cat_col].apply(
        lambda name: _normalise_category_name(name, known_categories)
    )
    if razrez_col:
        mapping["Разрез"] = mapping[razrez_col].fillna("").astype(str).map(
            normalize_razrez_value
        )
    else:
        mapping["Разрез"] = ""
    mapping = mapping.drop_duplicates(subset=[product_col])

    df = prepared_orders_df.copy()
    df[product_col] = df[product_col].astype(str).str.strip()
    df = df.merge(
        mapping[[product_col, "Категория агрег.", "Разрез"]],
        how="left",
        on=product_col,
    )
    df["Категория агрег."] = df["Категория агрег."].fillna("")
    df["Разрез"] = df["Разрез"].fillna("")

    last_week_df = df[df["Неделя"] == last_week_value]
    order = load_category_order_list(category_order_df, COL_SPEC_RNP)
    specs = parse_category_order(order)

    rows: List[dict[str, object]] = []
    for spec in specs:
        subset_all = _slice_by_spec(df, spec)
        subset_last = _slice_by_spec(last_week_df, spec)
        total_clients = _count_clients(subset_all)
        last_week_clients = _count_clients(subset_last)
        last_week_qty = float(subset_last["Количество"].sum())
        avg_per_client = (
            last_week_qty / last_week_clients if last_week_clients else 0.0
        )
        rows.append(
            {
                "Категория": spec.label,
                "Контрагентов с начала цикла": int(total_clients),
                "Контрагентов на последней неделе": int(last_week_clients),
                "Среднее шт./клиент (посл. нед.)": int(round(avg_per_client)),
            }
        )
    return pd.DataFrame(rows)


def _detect_product_level_column(df: pd.DataFrame) -> str | None:
    if "Товар ур.3" in df.columns:
        return "Товар ур.3"
    if "Товар ур.2" in df.columns:
        return "Товар ур.2"
    return None


def _slice_by_spec(df: pd.DataFrame, spec: CategoryRowSpec) -> pd.DataFrame:
    if df.empty:
        return df
    mask = match_spec_mask(df, spec)
    return df.loc[mask]


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
