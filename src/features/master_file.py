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
    values_column = categories_df[column]
    if isinstance(values_column, pd.DataFrame):
        values_column = values_column.iloc[:, 0]
    values = values_column.fillna("").astype(str).str.strip()
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
    try:
        prepared = _prepare_master_frame(master_df)
    except (TypeError, ValueError):
        return None
    week_series = _column_series(prepared, "Неделя")
    if week_series is None or pd.api.types.is_datetime64_any_dtype(week_series):
        return None
    numbers = _coerce_numbers(week_series).dropna()
    for value in numbers.tolist():
        week = _as_week_number(value)
        if week is not None:
            return week
    return None


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
            "Продажи с НДС": _coerce_numbers(
                _column_series(prepared, "Продажи с НДС")
            ),
            "Маржа": _coerce_numbers(_column_series(prepared, "Маржа")),
            "Количество": _coerce_numbers(_column_series(prepared, "Количество")),
            "Категория товара": _column_series(prepared, "Товар ур.4").map(
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
            "Продажи с НДС": grouped["Продажи с НДС"].map(_format_money_cell),
            "Маржа": grouped["Маржа"].map(_format_money_cell),
            "Количество": grouped["Количество"].map(_format_quantity_cell),
            COLUMN_GAP_BEFORE_CATEGORY: "",
            "Категория товара": grouped["Категория товара"],
        }
    ).reset_index(drop=True)


def _prepare_master_frame(master_df: pd.DataFrame) -> pd.DataFrame:
    """Находит строку заголовков и оставляет по одному столбцу с каждым именем."""
    prepared = master_df.copy()
    prepared.columns = [_header_text(col) for col in prepared.columns]
    prepared = _promote_header_row(prepared)
    prepared = _drop_duplicate_columns(prepared)
    return _rename_product_level_columns(prepared)


def _header_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _promote_header_row(df: pd.DataFrame) -> pd.DataFrame:
    """Если первая строка — шапка отчёта, берёт заголовки из строки с названиями столбцов."""
    if _has_required_columns(df):
        return df
    limit = min(20, len(df))
    for index in range(limit):
        headers = [_header_text(value) for value in df.iloc[index].tolist()]
        if not _row_has_required_headers(headers):
            continue
        body = df.iloc[index + 1 :].copy()
        width = body.shape[1]
        body.columns = (headers + [""] * width)[:width]
        return body.reset_index(drop=True)
    return df


def _has_required_columns(df: pd.DataFrame) -> bool:
    return all(column in df.columns for column in _REQUIRED_COLUMNS)


def _row_has_required_headers(headers: list[str]) -> bool:
    folded = {header.casefold() for header in headers if header}
    return {"клиент", "товар ур.4", "продажи с ндс"} <= folded


def _drop_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Повторяющиеся заголовки Excel оставляет один раз, иначе столбец читается как таблица."""
    seen: set[str] = set()
    keep: list[int] = []
    for index, name in enumerate(df.columns):
        if name in seen:
            continue
        seen.add(str(name))
        keep.append(index)
    if len(keep) == len(df.columns):
        return df
    trimmed = df.iloc[:, keep].copy()
    trimmed.columns = [df.columns[index] for index in keep]
    return trimmed


def _column_series(df: pd.DataFrame, name: str) -> pd.Series:
    """Один столбец. При дубле заголовка берётся первый."""
    value = df[name]
    if isinstance(value, pd.DataFrame):
        value = value.iloc[:, 0]
    return value


def _coerce_numbers(series: pd.Series | None) -> pd.Series:
    """Числа из Excel, в том числе текст вида «1 234,50». Сбой разбора даёт 0."""
    if series is None:
        return pd.Series(dtype="float64")
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    parsed = series.map(_parse_number_text)
    try:
        numbers = pd.to_numeric(parsed, errors="coerce")
    except (TypeError, ValueError):
        numbers = pd.Series(0.0, index=series.index)
    return numbers.fillna(0.0).astype(float)


def _parse_number_text(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (pd.Timestamp, datetime)):
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text or text.casefold() in {"nan", "none", "<na>", "nat"}:
        return None
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    return text


def _as_week_number(value: object) -> int | None:
    try:
        week = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None
    if week < 1 or week > 53:
        return None
    return week


def _format_money_cell(value: object) -> str:
    return _format_money_compact(_as_float(value))


def _format_quantity_cell(value: object) -> str:
    return _format_quantity_compact(_as_float(value))


def _as_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(number):
        return 0.0
    return number


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
    if not text or text.casefold() in {"nan", "nat", "none", "<na>"}:
        return ""
    if text.endswith("00:00:00"):
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.notna(parsed):
            return parsed.strftime("%m.%Y")
    return text


def _week_label(value: object) -> str:
    """Номер недели без дробной части. Даты и пустые ячейки остаются пустыми."""
    if isinstance(value, (pd.Timestamp, datetime)):
        return ""
    week = _as_week_number(value)
    if week is not None:
        return str(week)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.casefold() in {"nan", "none", "<na>", "nat"}:
        return ""
    return text


def _month_sort_value(label: object) -> str:
    """Ключ сортировки из текста, без сравнения дат и строк между собой."""
    text = "" if label is None else str(label).strip()
    try:
        parsed = pd.to_datetime(text, format="%m.%Y", errors="coerce")
    except (TypeError, ValueError):
        return f"1|{text}"
    if isinstance(parsed, pd.Series) or pd.isna(parsed):
        return f"1|{text}"
    return f"0|{pd.Timestamp(parsed).strftime('%Y-%m')}"
