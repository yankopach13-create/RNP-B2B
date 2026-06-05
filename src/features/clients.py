# src/features/clients.py
from __future__ import annotations

from typing import Iterable
import numpy as np
import pandas as pd
import streamlit as st


def render_clients_dynamics(
    merged_df: pd.DataFrame,
    contractors_df: pd.DataFrame,
    allowed_subdivisions: set[str] | None = None,
) -> None:
    """
    Таблица «Динамика клиентов» + итоги под таблицей.
    Учитывает, что продажи могут быть и по Клиенту, и по Группе контрагентов.
    """
    contractors = (
        contractors_df[["Контрагент", "Подразделение"]]
        .copy()
        .dropna(subset=["Контрагент"])
    )
    contractors["Контрагент"] = contractors["Контрагент"].astype(str).str.strip()
    contractors["Подразделение"] = (
        contractors["Подразделение"].fillna("").astype(str).str.strip()
    )
    contractors["__order__"] = np.arange(len(contractors))
    contractors = contractors.drop_duplicates(subset=["Контрагент"], keep="first")

    if allowed_subdivisions is not None:
        contractors = contractors[
            contractors["Подразделение"].isin(allowed_subdivisions)
        ]

    contractors = contractors.rename(columns={"Контрагент": "Ключ"})

    base = merged_df.copy()
    base["Ключ_клиент"] = base["Клиент"].fillna("").astype(str).str.strip()
    base["Ключ_группа"] = (
        base.get("Группа контрагентов", pd.Series(index=base.index, dtype="string"))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    base["Товар ур.3"] = (
        base.get("Товар ур.3", pd.Series(index=base.index, dtype="string"))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    base["Разрез 1"] = (
        base.get("Разрез 1", pd.Series(index=base.index, dtype="string"))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    base["Количество"] = pd.to_numeric(
        base.get("Количество", pd.Series(index=base.index)), errors="coerce"
    ).fillna(0.0)

    rows: list[dict[str, object]] = []
    max_order = contractors["__order__"].max() if not contractors.empty else -1
    used_indices = set()
    numeric_cols = [
        "Продажи с НДС",
        "DRAGBAR 6000, шт.",
        "Никотиновые паучи, шт.",
        "БКС, шт.",
    ]

    for _, row in contractors.iterrows():
        key = row["Ключ"]
        order = row["__order__"]
        subdivision = row["Подразделение"]

        metrics, row_indices = _compute_metrics_for_key(base, key)
        rows.append(
            {
                "Контрагент": key,
                "Подразделение": subdivision,
                "Продажи с НДС": metrics["sales"],
                "DRAGBAR 6000, шт.": metrics["dragbar_qty"],
                "Никотиновые паучи, шт.": metrics["pouch_qty"],
                "БКС, шт.": metrics["bks_qty"],
                "__order__": order,
            }
        )
        used_indices.update(row_indices)

    result_num = pd.DataFrame(rows)
    if result_num.empty:
        st.info("Нет данных по клиентам")
        return

    sum_actual = {
        "Продажи с НДС": merged_df["Продажи с НДС"].sum(),
        "DRAGBAR 6000, шт.": merged_df.loc[
            merged_df.get("Товар ур.3", "")
            .astype(str)
            .str.lower()
            .eq("dragbar 6000"),
            "Количество",
        ].sum(),
        "Никотиновые паучи, шт.": merged_df.loc[
            merged_df.get("Разрез 1", "").eq("в т.ч. Никотиновые паучи, шт."),
            "Количество",
        ].sum(),
        "БКС, шт.": merged_df.loc[
            merged_df.get("Разрез 1", "").eq("в т.ч. БКС, шт."),
            "Количество",
        ].sum(),
    }

    sum_clients = {col: result_num[col].sum() for col in numeric_cols}
    residuals = {
        col: sum_actual[col] - sum_clients.get(col, 0.0)
        for col in numeric_cols
    }
    thresholds = {
        "Продажи с НДС": 0.01,
        "DRAGBAR 6000, шт.": 0.5,
        "Никотиновые паучи, шт.": 0.5,
        "БКС, шт.": 0.5,
    }
    need_residual_row = any(
        abs(residuals[col]) > thresholds[col] for col in thresholds
    )
    if need_residual_row:
        max_order += 1
        result_num = pd.concat(
            [
                result_num,
                pd.DataFrame(
                    [
                        {
                            "Контрагент": "Прочие (не в справочнике)",
                            "Подразделение": "",
                            "Продажи с НДС": residuals["Продажи с НДС"],
                            "DRAGBAR 6000, шт.": residuals["DRAGBAR 6000, шт."],
                            "Никотиновые паучи, шт.": residuals["Никотиновые паучи, шт."],
                            "БКС, шт.": residuals["БКС, шт."],
                            "__order__": max_order,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    sum_clients = {col: result_num[col].sum() for col in numeric_cols}

    result_fmt = result_num.copy()
    result_fmt = result_fmt.sort_values("__order__").reset_index(drop=True)
    result_fmt["Продажи с НДС"] = result_fmt["Продажи с НДС"].apply(
        lambda x: "-" if np.isclose(x, 0.0) else f"{x:.2f}".replace(".", ",")
    )
    for col in ["DRAGBAR 6000, шт.", "Никотиновые паучи, шт.", "БКС, шт."]:
        result_fmt[col] = result_fmt[col].apply(
            lambda x: "" if np.isclose(x, 0.0) else f"{int(round(x))}"
        )

    st.dataframe(
        result_fmt.drop(columns="__order__"),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Продажи с НДС": st.column_config.TextColumn("Продажи с НДС"),
            "DRAGBAR 6000, шт.": st.column_config.TextColumn("DRAGBAR 6000, шт."),
            "Никотиновые паучи, шт.": st.column_config.TextColumn(
                "Никотиновые паучи, шт."
            ),
            "БКС, шт.": st.column_config.TextColumn("БКС, шт."),
        },
    )

    html = "<div style='margin-top:14px; display:flex; gap:18px; flex-wrap:wrap;'>"
    for col in numeric_cols:
        s = sum_clients[col]
        a = sum_actual[col]
        matches = np.isclose(s, a)
        bg = "#219653" if matches else "#EF5350"
        icon = "&#10004;" if matches else "&#10008;"
        if "шт." in col:
            client_val = f"{int(round(s))}"
            actual_val = f"{int(round(a))}"
        else:
            client_val = f"{s:.2f}".replace(".", ",")
            actual_val = f"{a:.2f}".replace(".", ",")
        html += (
            f"<div style='background:{bg};color:white;"
            f"padding:8px 16px;border-radius:8px;font-weight:bold;'>"
            f"{col}: {client_val} / {actual_val} {icon}</div>"
        )
    html += "</div>"
    html += (
        "<div style='font-size:0.92em;"
        " margin-top:4px;'>Слева — сумма по таблице, справа — сумма из общих данных</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _compute_metrics_for_key(
    df: pd.DataFrame,
    key: str,
) -> tuple[pd.Series, set[int]]:
    mask = (df["Ключ_клиент"] == key) | (df["Ключ_группа"] == key)
    subset = df.loc[mask]
    if subset.empty:
        metrics = {"sales": 0.0, "dragbar_qty": 0.0, "pouch_qty": 0.0, "bks_qty": 0.0}
        return pd.Series(metrics, dtype="float"), set()
    sales = subset["Продажи с НДС"].sum()
    dragbar = subset.loc[
        subset["Товар ур.3"].eq("dragbar 6000"), "Количество"
    ].sum()
    pouch = subset.loc[
        subset["Разрез 1"].eq("в т.ч. Никотиновые паучи, шт."), "Количество"
    ].sum()
    bks = subset.loc[
        subset["Разрез 1"].eq("в т.ч. БКС, шт."), "Количество"
    ].sum()
    metrics = pd.Series(
        {"sales": float(sales), "dragbar_qty": float(dragbar),
         "pouch_qty": float(pouch), "bks_qty": float(bks)},
        dtype="float",
    )
    return metrics, set(subset.index)


def _aggregate_metrics(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    grouped = df.groupby(key_col)
    result = pd.DataFrame(index=grouped.size().index)
    result["sales"] = grouped["Продажи с НДС"].sum()
    result["dragbar_qty"] = (
        df.loc[df["Товар ур.3"].eq("dragbar 6000")]
        .groupby(key_col)["Количество"]
        .sum()
    )
    result["pouch_qty"] = (
        df.loc[df["Разрез 1"].eq("в т.ч. Никотиновые паучи, шт.")]
        .groupby(key_col)["Количество"]
        .sum()
    )
    result["bks_qty"] = (
        df.loc[df["Разрез 1"].eq("в т.ч. БКС, шт.")]
        .groupby(key_col)["Количество"]
        .sum()
    )
    return result.fillna(0.0)


def _build_subdivision_map(df: pd.DataFrame, key_col: str) -> dict[str, str]:
    data = df[[key_col, "Подразделение"]].copy().dropna(subset=[key_col])
    data[key_col] = data[key_col].astype(str).str.strip()
    data["Подразделение"] = data["Подразделение"].fillna("").astype(str).str.strip()
    return data.groupby(key_col)["Подразделение"].agg(
        lambda s: next((x for x in s if x), "")
    ).to_dict()


def _build_row(
    key: str,
    subdivision: str,
    order: int,
    metrics: pd.Series,
    allow_empty_subdivision: bool = False,
) -> dict[str, object]:
    subdivision_clean = subdivision if (allow_empty_subdivision or subdivision) else subdivision
    return {
        "Контрагент": key,
        "Подразделение": subdivision_clean,
        "Продажи с НДС": float(metrics["sales"]),
        "DRAGBAR 6000, шт.": float(metrics["dragbar_qty"]),
        "Никотиновые паучи, шт.": float(metrics["pouch_qty"]),
        "БКС, шт.": float(metrics["bks_qty"]),
        "__order__": order,
    }