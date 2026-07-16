"""ИИ-отчёт B2B: сводная таблица для копирования (метрики из блока РНП)."""

from __future__ import annotations

import pandas as pd

from data.references import REF_DZ_SPEC, REF_DZ_TRAD
from features.category_order import (
    COL_SPEC_RNP,
    COL_TRADITION_RNP,
    _label_key,
    extract_category_row_values,
    load_category_order_list,
)
from features.factor_analysis import RTRADE_CLIENTS
from features.orders import _count_clients
from features.render import (
    _format_money_compact,
    _format_quantity_compact,
    build_financial_metrics_vertical_table,
)

AI_REPORT_VERSION = "2026-07-16-v2"

AI_REPORT_SPEC_CATEGORY_LABELS = [
    "ОЭС 2 мл, шт.",
    "ОЭС 10 мл, шт.",
    "Жидкость 25 мл, шт.",
    "Pod-системы, шт.",
    "Расходники, шт.",
    "Кальянная продукция, шт.",
    "в т.ч. Уголь, шт.",
    "в т.ч. БКС/ТКС, шт.",
    "Никотиновые паучи, шт.",
    "Прочие товары, шт.",
]

AI_REPORT_TRADITION_CATEGORY_ROWS: list[tuple[str, str]] = [
    (
        "Одноразовые электронные сигареты ( 2 мл ) Традиция",
        "ОЭС 2 мл, шт.",
    ),
    (
        "Одноразовые электронные сигареты ( 10 мл ) Традиция",
        "ОЭС 10 мл, шт.",
    ),
    ("Никотиновые паучи Традиция", "Никотиновые паучи, шт."),
    ("в т.ч. Уголь, шт.", "в т.ч. Уголь, шт."),
]


def _safe_sum(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or df.empty:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum())


def _vertical_metrics_lookup(table: pd.DataFrame) -> dict[str, str]:
    if table.empty:
        return {}
    result: dict[str, str] = {}
    for _, row in table.iterrows():
        label = str(row.get("Показатель", "")).strip()
        if not label:
            continue
        result[label] = str(row.get("Значение", "")).strip()
    return result


def _lookup_category_row_value(categories: dict[str, str], label: str) -> str:
    if label in categories:
        return categories[label]
    target_key = _label_key(label)
    for key, value in categories.items():
        if _label_key(key) == target_key:
            return str(value)
    return ""


def build_ai_report_table(
    spec_df: pd.DataFrame,
    tradition_df: pd.DataFrame,
    receivables_df: pd.DataFrame | None,
    category_order_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from features.dashboard import (
        _calc_dz_total_by_reference,
        get_excise_liquid_margin_deduction,
    )

    spec_order = load_category_order_list(category_order_df, COL_SPEC_RNP)
    tradition_order = load_category_order_list(category_order_df, COL_TRADITION_RNP)
    margin_adjustment = get_excise_liquid_margin_deduction()

    spec_finance = _vertical_metrics_lookup(
        build_financial_metrics_vertical_table(
            spec_df,
            subdivisions=[],
            include_overall=True,
            aggregates={},
            format_money=_format_money_compact,
            overall_margin_adjustment=margin_adjustment,
        )
    )
    tradition_finance = _vertical_metrics_lookup(
        build_financial_metrics_vertical_table(
            tradition_df,
            subdivisions=[],
            include_overall=True,
            aggregates={},
            format_money=_format_money_compact,
        )
    )

    spec_categories = extract_category_row_values(
        spec_df,
        spec_order,
        format_value=_format_quantity_compact,
    )
    tradition_categories = extract_category_row_values(
        tradition_df,
        tradition_order,
        format_value=_format_quantity_compact,
    )

    rtrade_mask = (
        spec_df["Клиент"].fillna("").astype(str).str.strip().isin(RTRADE_CLIENTS)
        if "Клиент" in spec_df.columns
        else pd.Series(False, index=spec_df.index)
    )
    rtrade_sales = _safe_sum(spec_df.loc[rtrade_mask], "Продажи с НДС")
    rtrade_margin = _safe_sum(spec_df.loc[rtrade_mask], "Маржа")
    dz_spec_total, _ = _calc_dz_total_by_reference(REF_DZ_SPEC, receivables_df)
    dz_trad_total, _ = _calc_dz_total_by_reference(REF_DZ_TRAD, receivables_df)

    rows: list[dict[str, str]] = [
        {"Показатель": "Заказы", "Значение": ""},
        {
            "Показатель": "Кол-во клиентов сделавших заказ B2B Спец.розница",
            "Значение": str(_count_clients(spec_df)),
        },
        {
            "Показатель": "Продажи с НДС B2B Спец.розница",
            "Значение": spec_finance.get("Продажи с НДС", ""),
        },
        {
            "Показатель": "Маржа B2B Спец.розница",
            "Значение": spec_finance.get("Маржа", ""),
        },
        {
            "Показатель": "% Маржи B2B Спец.розница",
            "Значение": spec_finance.get("% МД", ""),
        },
        {
            "Показатель": "Продажи с НДС Ртрейд",
            "Значение": _format_money_compact(rtrade_sales),
        },
        {
            "Показатель": "Маржа Ртрейд",
            "Значение": _format_money_compact(rtrade_margin),
        },
        {
            "Показатель": "Дебиторская задолженность B2B Спец.розница",
            "Значение": _format_money_compact(dz_spec_total),
        },
    ]

    for category_label in AI_REPORT_SPEC_CATEGORY_LABELS:
        rows.append(
            {
                "Показатель": category_label,
                "Значение": _lookup_category_row_value(spec_categories, category_label),
            }
        )

    rows.extend(
        [
            {
                "Показатель": "Продажи с НДС Традиция",
                "Значение": tradition_finance.get("Продажи с НДС", ""),
            },
            {
                "Показатель": "Маржа Традиция",
                "Значение": tradition_finance.get("Маржа", ""),
            },
            {
                "Показатель": "% Маржи Традиция",
                "Значение": tradition_finance.get("% МД", ""),
            },
            {
                "Показатель": "Дебиторская задолженность Традиция",
                "Значение": _format_money_compact(dz_trad_total),
            },
        ]
    )

    for display_label, lookup_label in AI_REPORT_TRADITION_CATEGORY_ROWS:
        rows.append(
            {
                "Показатель": display_label,
                "Значение": _lookup_category_row_value(
                    tradition_categories, lookup_label
                ),
            }
        )

    return pd.DataFrame(rows)
