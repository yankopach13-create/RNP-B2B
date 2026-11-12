"""Блок «Мастер файл»: категория из столбца справочника и суммы по клиенту."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from features.data_prep import (
    PRODUCT_COLUMNS,
    _level4_match_key,
    _normalise_product_columns,
    _rename_product_level_columns,
    merge_product_categories,
    product_level3_key,
)
from features.render import _format_money_compact, _format_quantity_compact

MASTER_CATEGORY_COLUMN = "Мастер файл"
CLIENT_BLOCK_CATEGORY_COLUMN = "Клиентский блок"
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
    "Товар ур.3",
    "Товар ур.4",
    "Месяц",
    "Продажи с НДС",
    "Маржа",
    "Количество",
)
_LEVEL3_HEADER_KEYS = frozenset(
    {"товар ур.3", "товар ур. 3", "товар3", "товар 3", "товар.ур.3"}
)
_LEVEL4_HEADER_KEYS = frozenset(
    {"товар ур.4", "товар ур. 4", "товар4", "товар 4", "товар.ур.4", "товар ур4"}
)


def find_labeled_column(df: pd.DataFrame, label: str) -> str | None:
    """Имя столбца справочника с заданным заголовком, без учёта регистра."""
    if df is None:
        return None
    for col in df.columns:
        if str(col).strip().casefold() == label.casefold():
            return str(col)
    return None


def find_master_category_column(df: pd.DataFrame) -> str | None:
    """Имя столбца «Мастер файл» в справочнике категорий."""
    return find_labeled_column(df, MASTER_CATEGORY_COLUMN)


def find_client_block_category_column(df: pd.DataFrame) -> str | None:
    """Имя столбца «Клиентский блок» в справочнике категорий."""
    return find_labeled_column(df, CLIENT_BLOCK_CATEGORY_COLUMN)


def _labeled_category_options(categories_df: pd.DataFrame, label: str) -> list[str]:
    """Уникальные непустые значения столбца справочника для списка в форме."""
    column = find_labeled_column(categories_df, label)
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


def master_category_options(categories_df: pd.DataFrame) -> list[str]:
    """Уникальные непустые значения столбца «Мастер файл» для списка в форме."""
    return _labeled_category_options(categories_df, MASTER_CATEGORY_COLUMN)


def client_block_category_options(categories_df: pd.DataFrame) -> list[str]:
    """Уникальные непустые значения столбца «Клиентский блок» для списка в форме."""
    return _labeled_category_options(categories_df, CLIENT_BLOCK_CATEGORY_COLUMN)


def build_master_file_table(
    master_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    week_number: int | None,
) -> pd.DataFrame:
    """Суммы по конечному клиенту, месяцу, неделе и категории мастер-файла.

    Конечный клиент — «Группа контрагентов», если она заполнена, иначе «Клиент».
    Неделя — номер из поля «Актуальная неделя», в файле её нет.
    Категория берётся по «Товар ур.3» и «Товар ур.4». Если у одной пары
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

    lookup = _master_category_by_level34(categories_df)
    category_column = find_master_category_column(categories_df)
    if category_column is None:
        raise ValueError(
            "В справочнике категорий нет столбца «Мастер файл»."
        )

    level3_values = _column_series(prepared, "Товар ур.3").tolist()
    level4_values = _column_series(prepared, "Товар ур.4").tolist()
    categories = [
        lookup.get(key, "") if (key := _product_pair_key(level3, level4)) else ""
        for level3, level4 in zip(level3_values, level4_values)
    ]
    week_label = "" if week_number is None else str(int(week_number))
    frame = pd.DataFrame(
        {
            "Клиент": _resolved_client_name(prepared),
            "Месяц": prepared["Месяц"].map(_month_label),
            "Неделя": week_label,
            "Продажи с НДС": _coerce_numbers(
                _column_series(prepared, "Продажи с НДС")
            ),
            "Маржа": _coerce_numbers(_column_series(prepared, "Маржа")),
            "Количество": _coerce_numbers(_column_series(prepared, "Количество")),
            "Категория товара": categories,
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
    has_levels = bool(folded & _LEVEL3_HEADER_KEYS) and bool(folded & _LEVEL4_HEADER_KEYS)
    return {"клиент", "продажи с ндс"} <= folded and has_levels


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


def _product_pair_key(level3: object, level4: object) -> tuple[str, str] | None:
    """Ключ «Товар ур.3» + «Товар ур.4». Пустая пара не участвует в поиске."""
    level3_key = product_level3_key(level3)
    if level3_key in {"__none__", "nan", "none"}:
        level3_key = ""
    level4_key = _level4_match_key(level4)
    if not level3_key and not level4_key:
        return None
    return level3_key, level4_key


def _master_category_by_level34(
    categories_df: pd.DataFrame,
) -> dict[tuple[str, str], str]:
    """Первая непустая категория «Мастер файл» для пары «Товар ур.3» и «Товар ур.4»."""
    if categories_df is None or categories_df.empty:
        return {}
    prepared = categories_df.copy()
    prepared.columns = [str(col).strip() for col in prepared.columns]
    prepared = _rename_product_level_columns(prepared)
    column = find_labeled_column(prepared, MASTER_CATEGORY_COLUMN)
    if (
        column is None
        or "Товар ур.3" not in prepared.columns
        or "Товар ур.4" not in prepared.columns
    ):
        return {}
    lookup: dict[tuple[str, str], str] = {}
    level3_values = _column_series(prepared, "Товар ур.3").tolist()
    level4_values = _column_series(prepared, "Товар ур.4").tolist()
    category_values = _column_series(prepared, column).tolist()
    for level3, level4, raw_category in zip(level3_values, level4_values, category_values):
        key = _product_pair_key(level3, level4)
        if key is None or key in lookup:
            continue
        category = _category_cell_text(raw_category)
        if not category:
            continue
        lookup[key] = category
    return lookup


def map_client_block_categories(
    sales_df: pd.DataFrame,
    categories_df: pd.DataFrame,
) -> pd.Series:
    """Категория столбца «Клиентский блок» для строк продаж.

    Сначала «Товар ур.2» + «Товар ур.3» + «Товар ур.4».
    Если ур.4 пустой или прочерк — по ур.2 и ур.3 среди таких же строк справочника.
    Если ур.4 заполнен и точной тройки нет — только по ур.4.
    Пустые ячейки столбца пропускаются, остаётся первое непустое значение.
    Нет совпадения — пустая строка.
    """
    empty = pd.Series("", index=sales_df.index, dtype="string")
    if sales_df is None or sales_df.empty:
        return empty
    lookup = _client_block_category_lookup(categories_df)
    if lookup.empty:
        return empty

    sales = _normalise_product_columns(_rename_product_level_columns(sales_df.copy()))
    if any(column not in sales.columns for column in PRODUCT_COLUMNS):
        return empty

    merged = merge_product_categories(
        sales,
        lookup,
        value_cols=(CLIENT_BLOCK_CATEGORY_COLUMN,),
    )
    categories = (
        merged[CLIENT_BLOCK_CATEGORY_COLUMN].fillna("").astype(str).str.strip()
    )
    categories.index = sales_df.index
    return categories


def _client_block_category_lookup(categories_df: pd.DataFrame) -> pd.DataFrame:
    """Строки справочника с непустым «Клиентский блок» и нормализованными уровнями товара."""
    columns = PRODUCT_COLUMNS + [CLIENT_BLOCK_CATEGORY_COLUMN]
    empty = pd.DataFrame(columns=columns)
    if categories_df is None or categories_df.empty:
        return empty
    if find_client_block_category_column(categories_df) is None:
        return empty

    prepared = categories_df.copy()
    prepared.columns = [str(col).strip() for col in prepared.columns]
    prepared = _normalise_product_columns(_rename_product_level_columns(prepared))
    column = find_client_block_category_column(prepared)
    if column is None or any(name not in prepared.columns for name in PRODUCT_COLUMNS):
        return empty

    cleaned = _column_series(prepared, column).map(_category_cell_text)
    filled = prepared.loc[cleaned.ne("")].copy()
    if filled.empty:
        return empty
    filled[CLIENT_BLOCK_CATEGORY_COLUMN] = cleaned.loc[filled.index].to_numpy()
    return filled[columns].drop_duplicates(subset=PRODUCT_COLUMNS, keep="first")


def _category_cell_text(value: object) -> str:
    """Текст ячейки категории. Пустые и служебные значения — пустая строка."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "<na>"}:
        return ""
    return text


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
