"""Блок «Мастер файл»: категория из столбца справочника и суммы по клиенту."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from features.data_prep import (
    _level4_match_key,
    _rename_product_level_columns,
)
from features.render import _format_money_compact, _format_quantity_compact

MASTER_CATEGORY_COLUMN = "Мастер файл"
# Пустые заголовки-разделители для вставки таблицы в Excel. Символы разные,
# чтобы имена столбцов не совпали, и на экране они не видны.
COLUMN_GAP_BEFORE_PERIOD = "\u00a0"
COLUMN_GAP_BEFORE_CATEGORY = "\u200b"

MASTER_TABLE_COLUMNS = [
    "Клиент",
    COLUMN_GAP_BEFORE_PERIOD,
    "Месяц",
    "Неделя",
    "Продажи с НДС",
    "Маржа",
    "Количество",
    COLUMN_GAP_BEFORE_CATEGORY,
    "Категория товара",
]

_EMPTY_COUNTERPARTY_GROUPS = frozenset({"", "-", "—", "–", "―", "‑"})
_REQUIRED_COLUMNS = (
    "Клиент",
    "Группа контрагентов",
    "Товар ур.4",
    "Месяц",
    "Неделя",
    "Продажи с НДС",
    "Маржа",
    "Количество",
)


def find_master_category_column(df: pd.DataFrame) -> str | None:
    """Имя столбца «Мастер файл» в справочнике категорий."""
    for col in df.columns:
        if str(col).strip().casefold() == MASTER_CATEGORY_COLUMN.casefold():
            return str(col)
    return None


def master_category_options(categories_df: pd.DataFrame) -> list[str]:
    """Уникальные непустые значения столбца «Мастер файл» для списка в форме."""
    column = find_master_category_column(categories_df)
    if column is None:
        return []
    values = (
        categories_df[column]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    cleaned = {
        value
        for value in values.tolist()
        if value and value.casefold() not in {"nan", "none"}
    }
    return sorted(cleaned)


def master_file_week_number(master_df: pd.DataFrame | None) -> int | None:
    """Номер недели из мастер-файла. В файле ожидается одна неделя."""
    if master_df is None or master_df.empty:
        return None
    prepared = _prepare_master_frame(master_df)
    if "Неделя" not in prepared.columns:
        return None
    numbers = pd.to_numeric(prepared["Неделя"], errors="coerce").dropna()
    if numbers.empty:
        return None
    week = int(round(float(numbers.iloc[0])))
    if week < 1 or week > 53:
        return None
    return week


def build_master_file_table(
    master_df: pd.DataFrame,
    categories_df: pd.DataFrame,
) -> pd.DataFrame:
    """Суммы по конечному клиенту, месяцу, неделе и категории мастер-файла.

    Конечный клиент — «Группа контрагентов», если она заполнена, иначе «Клиент».
    Категория берётся по «Товар ур.4». Если у одного товара в справочнике
    несколько значений, остаётся первое непустое.
    """
    if master_df is None or master_df.empty:
        return pd.DataFrame(columns=MASTER_TABLE_COLUMNS)

    prepared = _prepare_master_frame(master_df)
    missing = [col for col in _REQUIRED_COLUMNS if col not in prepared.columns]
    if missing:
        raise ValueError(
            "В мастер-файле нет столбцов: " + ", ".join(missing) + "."
        )

    lookup = _master_category_by_level4(categories_df)
    category_column = find_master_category_column(categories_df)
    if category_column is None:
        raise ValueError(
            "В справочнике категорий нет столбца «Мастер файл»."
        )

    frame = pd.DataFrame(
        {
            "Клиент": _resolved_client_name(prepared),
            "Месяц": prepared["Месяц"].map(_month_label),
            "Неделя": prepared["Неделя"].map(_week_label),
            "Продажи с НДС": pd.to_numeric(
                prepared["Продажи с НДС"], errors="coerce"
            ).fillna(0.0),
            "Маржа": pd.to_numeric(prepared["Маржа"], errors="coerce").fillna(0.0),
            "Количество": pd.to_numeric(
                prepared["Количество"], errors="coerce"
            ).fillna(0.0),
            "Категория товара": prepared["Товар ур.4"].map(
                lambda value: lookup.get(_level4_match_key(value), "")
            ),
        }
    )
    frame = frame[frame["Клиент"].ne("")]
    if frame.empty:
        return pd.DataFrame(columns=MASTER_TABLE_COLUMNS)

    grouped = frame.groupby(
        ["Клиент", "Месяц", "Неделя", "Категория товара"],
        dropna=False,
        as_index=False,
    )[["Продажи с НДС", "Маржа", "Количество"]].sum()
    grouped["_month_sort"] = grouped["Месяц"].map(_month_sort_value)
    grouped["_week_sort"] = pd.to_numeric(grouped["Неделя"], errors="coerce")
    grouped = grouped.sort_values(
        ["Клиент", "_month_sort", "_week_sort", "Категория товара"],
        kind="stable",
    )
    return pd.DataFrame(
        {
            "Клиент": grouped["Клиент"],
            COLUMN_GAP_BEFORE_PERIOD: "",
            "Месяц": grouped["Месяц"],
            "Неделя": grouped["Неделя"],
            "Продажи с НДС": grouped["Продажи с НДС"].map(
                lambda value: _format_money_compact(float(value))
            ),
            "Маржа": grouped["Маржа"].map(
                lambda value: _format_money_compact(float(value))
            ),
            "Количество": grouped["Количество"].map(
                lambda value: _format_quantity_compact(float(value))
            ),
            COLUMN_GAP_BEFORE_CATEGORY: "",
            "Категория товара": grouped["Категория товара"],
        }
    ).reset_index(drop=True)


def _prepare_master_frame(master_df: pd.DataFrame) -> pd.DataFrame:
    """Срезает пробелы в заголовках и приводит имя столбца «Товар ур.4»."""
    prepared = master_df.copy()
    prepared.columns = [str(col).strip() for col in prepared.columns]
    return _rename_product_level_columns(prepared)


def _resolved_client_name(df: pd.DataFrame) -> pd.Series:
    """Группа контрагентов, если она задана, иначе клиент."""
    clients = df["Клиент"].fillna("").astype(str).str.strip()
    groups = df["Группа контрагентов"].fillna("").astype(str).str.strip()
    use_group = ~groups.isin(_EMPTY_COUNTERPARTY_GROUPS)
    return groups.where(use_group, clients)


def _master_category_by_level4(categories_df: pd.DataFrame) -> dict[str, str]:
    """Первая непустая категория «Мастер файл» для каждого «Товар ур.4»."""
    column = find_master_category_column(categories_df)
    if column is None or categories_df.empty:
        return {}
    prepared = categories_df.copy()
    prepared.columns = [str(col).strip() for col in prepared.columns]
    prepared = _rename_product_level_columns(prepared)
    if "Товар ур.4" not in prepared.columns:
        return {}
    category_column = find_master_category_column(prepared) or column
    lookup: dict[str, str] = {}
    for level4, raw_category in zip(
        prepared["Товар ур.4"].tolist(),
        prepared[category_column].tolist(),
    ):
        key = _level4_match_key(level4)
        if not key or key in lookup:
            continue
        if raw_category is None or (
            isinstance(raw_category, float) and pd.isna(raw_category)
        ):
            continue
        category = str(raw_category).strip()
        if not category or category.casefold() in {"nan", "none"}:
            continue
        lookup[key] = category
    return lookup


def _month_label(value: object) -> str:
    """Месяц как в файле. Дата Excel показывается как ММ.ГГГГ."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return ""
        return value.strftime("%m.%Y")
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "nat", "none"}:
        return ""
    if text.endswith("00:00:00"):
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.notna(parsed):
            return parsed.strftime("%m.%Y")
    return text


def _week_label(value: object) -> str:
    """Номер недели без дробной части, если ячейка числовая."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    number = pd.to_numeric(value, errors="coerce")
    if pd.notna(number):
        return str(int(round(float(number))))
    text = str(value).strip()
    if text.casefold() in {"nan", "none"}:
        return ""
    return text


def _month_sort_value(label: object) -> tuple[int, object]:
    """Ключ сортировки: сначала распознанный месяц, затем текст как есть."""
    text = "" if label is None else str(label).strip()
    parsed = pd.to_datetime(text, format="%m.%Y", errors="coerce")
    if pd.notna(parsed):
        return (0, parsed.to_pydatetime())
    return (1, text)
