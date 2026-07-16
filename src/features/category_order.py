"""Порядок категорий из листа category_order и агрегация по категории/разрезу."""

from __future__ import annotations

from typing import Callable

from dataclasses import dataclass

import pandas as pd

from config.constants import (
    CATEGORY_DISPLAY_ORDER,
    TRADITION_CATEGORY_ORDER,
    TURNOVER_CATEGORY_ORDER,
)

SLICE_PREFIX = "в т.ч."

COL_SPEC_RNP = "Категории РНП Спец розница"
COL_GENERAL_SPEC = "Категории Общий РНП Спец розница"
COL_TURNOVER = "Оборачиваемость"
COL_TRADITION_RNP = "Категории РНП Традиция"
COL_GENERAL_TRADITION = "Категории Общий РНП Традиция"

FALLBACK_ORDERS: dict[str, list[str]] = {
    COL_SPEC_RNP: list(CATEGORY_DISPLAY_ORDER),
    COL_GENERAL_SPEC: [
        "ОЭС 2 мл, шт.",
        "ОЭС 4 мл, шт.",
        "ОЭС 10 мл, шт.",
        "Жидкость 25 мл, шт.",
        "Pod-системы, шт.",
        "Расходники, шт.",
        "Картриджи с жидкостью, шт.",
        "Никотиновые паучи, шт.",
        "ATOM",
        "Pau4",
        "Level UP",
        "Кальянная продукция, шт.",
        "в т.ч. Кальянные смеси, шт.",
        "Прочие товары, шт.",
    ],
    COL_TURNOVER: list(TURNOVER_CATEGORY_ORDER),
    COL_TRADITION_RNP: list(TRADITION_CATEGORY_ORDER),
    COL_GENERAL_TRADITION: [
        "ОЭС 2 мл, шт.",
        "ОЭС 10 мл, шт.",
        "Никотиновые паучи, шт.",
    ],
}


@dataclass(frozen=True)
class CategoryRowSpec:
    """Строка таблицы: категория целиком или разрез внутри родительской категории."""

    label: str
    parent_category: str
    razrez: str | None
    is_slice: bool


def get_category_source_column(df: pd.DataFrame) -> str | None:
    for col in ("Категория", "Категория:"):
        if col in df.columns:
            return col
    return None


def get_razrez_source_column(df: pd.DataFrame) -> str | None:
    for col in ("Разрез", "Разрез 1"):
        if col in df.columns:
            return col
    return None


def categories_reference_valid(df: pd.DataFrame) -> bool:
    return not df.empty and get_category_source_column(df) is not None


def normalize_razrez_value(value: object) -> str:
    """Приводит значение разреза к каноническому виду (без префикса «в т.ч.»)."""
    cleaned = str(value or "").strip()
    lowered = cleaned.lower()
    if lowered.startswith(SLICE_PREFIX):
        cleaned = cleaned[len(SLICE_PREFIX) :].strip()
        if cleaned.startswith("."):
            cleaned = cleaned[1:].strip()
    return cleaned


def _label_key(value: object) -> str:
    """Ключ для сравнения подписей категорий и разрезов без учёта регистра и «:»/«.» в конце."""
    cleaned = str(value or "").strip().casefold()
    while cleaned and cleaned[-1] in ":.":
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _razrez_match_key(value: object) -> str:
    """Ключ разреза без единиц измерения («, шт.») для гибкого сопоставления."""
    key = _label_key(value)
    for suffix in (", шт", " шт", ",шт"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].rstrip().rstrip(",")
    return key


def _razrez_match_patterns(spec_razrez: str) -> list[str]:
    """Шаблоны для сопоставления разреза: целиком и по частям «БКС/ТКС»."""
    key = _razrez_match_key(spec_razrez)
    if not key:
        return []
    patterns = [key]
    if "/" in key:
        patterns.extend(part.strip() for part in key.split("/") if part.strip())
    return list(dict.fromkeys(patterns))


def _razrez_matches_series(razrez_series: pd.Series, spec_razrez: str) -> pd.Series:
    """Маска строк, у которых разрез совпадает с подписью из category_order."""
    patterns = _razrez_match_patterns(spec_razrez)
    if not patterns:
        return pd.Series(False, index=razrez_series.index)

    keys = razrez_series.map(_razrez_match_key)
    mask = pd.Series(False, index=razrez_series.index)
    for pattern in patterns:
        mask = mask | keys.eq(pattern) | keys.str.contains(pattern, regex=False, na=False)
    return mask


def _lookup_parent_keys_for_razrez(
    razrez_parent_map: dict[str, set[str]],
    spec_razrez: str,
) -> set[str]:
    """Находит родительские категории по разрезу в справочнике categories."""
    parents: set[str] = set()
    for pattern in _razrez_match_patterns(spec_razrez):
        parents |= razrez_parent_map.get(pattern, set())
    return parents


def build_razrez_parent_map(
    categories_df: pd.DataFrame,
    known_categories: set[str] | None = None,
) -> dict[str, set[str]]:
    """Строит карту «разрез → родительские категории» из справочника categories."""
    cat_col = get_category_source_column(categories_df)
    if cat_col is None or categories_df.empty:
        return {}

    from features.data_prep import _normalise_category_name

    razrez_col = get_razrez_source_column(categories_df)
    mapping = categories_df.copy()
    parent_names = mapping[cat_col].fillna("").astype(str).str.strip()
    if razrez_col:
        razrez_values = (
            mapping[razrez_col]
            .fillna("")
            .astype(str)
            .str.strip()
            .map(normalize_razrez_value)
        )
    else:
        razrez_values = pd.Series([""] * len(mapping), index=mapping.index, dtype="string")

    known = known_categories or set()
    result: dict[str, set[str]] = {}
    for parent_name, razrez_value in zip(parent_names, razrez_values):
        if not razrez_value:
            continue
        parent_norm = _normalise_category_name(parent_name, known)
        parent_key = _label_key(parent_norm)
        razrez_key = _razrez_match_key(razrez_value)
        if not parent_key or not razrez_key:
            continue
        result.setdefault(razrez_key, set()).add(parent_key)
        if "/" in razrez_key:
            for part in razrez_key.split("/"):
                part = part.strip()
                if part:
                    result.setdefault(part, set()).add(parent_key)
    return result


def match_turnover_spec_mask(
    df: pd.DataFrame,
    spec: CategoryRowSpec,
    razrez_parent_map: dict[str, set[str]] | None = None,
) -> pd.Series:
    """Маска для оборачиваемости: категория, разрез 1 или авто-родитель из справочника."""
    if df.empty:
        return pd.Series(dtype=bool)

    categories = _category_series(df).map(_label_key)
    razrez = _razrez_series(df)

    if not spec.is_slice:
        return categories.eq(_label_key(spec.parent_category))

    if not spec.razrez:
        return pd.Series(False, index=df.index)

    razrez_mask = _razrez_matches_series(razrez, spec.razrez)

    if spec.parent_category:
        return categories.eq(_label_key(spec.parent_category)) & razrez_mask

    parent_map = razrez_parent_map or {}
    parent_keys = _lookup_parent_keys_for_razrez(parent_map, spec.razrez)

    if len(parent_keys) == 1:
        return categories.eq(next(iter(parent_keys))) & razrez_mask
    if len(parent_keys) > 1:
        return categories.isin(parent_keys) & razrez_mask

    return razrez_mask


def build_known_razrez_keys(categories_df: pd.DataFrame) -> set[str]:
    """Собирает ключи разрезов из справочника categories (столбец «Разрез» / «Разрез 1»)."""
    razrez_col = get_razrez_source_column(categories_df)
    if razrez_col is None or categories_df.empty:
        return set()

    keys: set[str] = set()
    for raw in categories_df[razrez_col].dropna().astype(str).str.strip():
        if not raw:
            continue
        normalized = normalize_razrez_value(raw)
        razrez_key = _razrez_match_key(normalized)
        if not razrez_key:
            continue
        keys.add(razrez_key)
        if "/" in razrez_key:
            keys.update(part.strip() for part in razrez_key.split("/") if part.strip())
    return keys


def resolve_turnover_match_mode(
    label: str,
    known_categories: set[str],
    known_razrez_keys: set[str],
) -> str:
    """Определяет, искать строку оборачиваемости как категорию или как разрез 1."""
    cleaned = str(label).strip()
    if not cleaned:
        return "category"
    if cleaned.lower().startswith(SLICE_PREFIX):
        return "razrez"

    label_key = _label_key(cleaned)
    cat_keys = {_label_key(name) for name in known_categories if name}
    razrez_key = _razrez_match_key(normalize_razrez_value(cleaned))

    in_categories = label_key in cat_keys
    in_razrez = bool(razrez_key) and (
        razrez_key in known_razrez_keys
        or any(
            razrez_key in known_key or known_key in razrez_key
            for known_key in known_razrez_keys
        )
    )

    if in_categories and not in_razrez:
        return "category"
    if in_razrez and not in_categories:
        return "razrez"
    if in_categories:
        return "category"
    if in_razrez:
        return "razrez"
    return "category"


def _is_coal_product_mask(df: pd.DataFrame) -> pd.Series:
    """Маска строк с углём по названию товара (как в data_prep для продаж)."""
    if df.empty:
        return pd.Series(dtype=bool)

    product_cols = [col for col in ("Товар ур.1", "Товар ур.2", "Товар ур.3") if col in df.columns]
    if not product_cols:
        return pd.Series(False, index=df.index)

    return df[product_cols].astype(str).apply(
        lambda series: series.str.contains("Уголь", case=False, na=False)
    ).any(axis=1)


def _razrez_label_implies_coal(label: str) -> bool:
    patterns = _razrez_match_patterns(normalize_razrez_value(label))
    return any("уголь" in pattern for pattern in patterns)


def _razrez_label_implies_bks_tks(label: str) -> bool:
    patterns = _razrez_match_patterns(normalize_razrez_value(label))
    return any(pattern in ("бкс", "ткс") or "бкс" in pattern or "ткс" in pattern for pattern in patterns)


def _match_turnover_by_category(df: pd.DataFrame, label: str) -> pd.Series:
    categories = _category_series(df).map(_label_key)
    return categories.eq(_label_key(label))


def _match_turnover_by_razrez(df: pd.DataFrame, label: str) -> pd.Series:
    razrez = _razrez_series(df)
    mask = _razrez_matches_series(razrez, normalize_razrez_value(label))

    if _razrez_label_implies_coal(label):
        mask = mask | _is_coal_product_mask(df)
    if _razrez_label_implies_bks_tks(label):
        mask = mask | _is_bks_tks_mask(df)
    return mask


def match_turnover_label_mask(
    df: pd.DataFrame,
    label: str,
    known_categories: set[str],
    known_razrez_keys: set[str],
) -> pd.Series:
    """Маска для строки столбца «Оборачиваемость»: категория или разрез 1."""
    if df.empty:
        return pd.Series(dtype=bool)

    mode = resolve_turnover_match_mode(label, known_categories, known_razrez_keys)
    if mode == "razrez":
        return _match_turnover_by_razrez(df, label)
    return _match_turnover_by_category(df, label)


def match_spec_mask(df: pd.DataFrame, spec: CategoryRowSpec) -> pd.Series:
    """Маска строк DataFrame, попадающих под строку category_order."""
    if df.empty:
        return pd.Series(dtype=bool)

    categories = _category_series(df).map(_label_key)
    parent_key = _label_key(spec.parent_category)

    if spec.is_slice:
        if not spec.razrez or not spec.parent_category:
            return pd.Series(False, index=df.index)
        razrez = _razrez_series(df).map(_label_key)
        razrez_key = _label_key(spec.razrez)
        return categories.eq(parent_key) & razrez.eq(razrez_key)

    return categories.eq(parent_key)


def load_category_order_list(
    category_order_df: pd.DataFrame | None,
    column_name: str,
) -> list[str]:
    """Читает список строк из столбца category_order; при отсутствии — fallback."""
    fallback = FALLBACK_ORDERS.get(column_name, [])
    if category_order_df is None or category_order_df.empty:
        return list(fallback)
    if column_name not in category_order_df.columns:
        return list(fallback)
    values = (
        category_order_df[column_name]
        .dropna()
        .astype(str)
        .str.strip()
    )
    values = values[values.ne("")].tolist()
    return values or list(fallback)


def category_labels_only(order: list[str]) -> list[str]:
    """Возвращает порядок только категорий, без строк-разрезов «в т.ч. …»."""
    return [
        label
        for label in order
        if str(label).strip()
        and not str(label).strip().lower().startswith(SLICE_PREFIX)
    ]


def parse_category_order(order: list[str]) -> list[CategoryRowSpec]:
    """Разбирает порядок строк: категория или «в т.ч. <разрез>» под предыдущей категорией."""
    specs: list[CategoryRowSpec] = []
    current_parent = ""
    for raw_label in order:
        label = str(raw_label).strip()
        if not label:
            continue
        if label.lower().startswith(SLICE_PREFIX):
            razrez = normalize_razrez_value(label)
            specs.append(
                CategoryRowSpec(
                    label=label,
                    parent_category=current_parent,
                    razrez=razrez or None,
                    is_slice=True,
                )
            )
        else:
            current_parent = label
            specs.append(
                CategoryRowSpec(
                    label=label,
                    parent_category=label,
                    razrez=None,
                    is_slice=False,
                )
            )
    return specs


def collect_known_category_names(
    categories_df: pd.DataFrame,
    category_order_df: pd.DataFrame | None = None,
) -> set[str]:
    names: set[str] = set()
    cat_col = get_category_source_column(categories_df)
    if cat_col:
        names.update(
            categories_df[cat_col]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )
    if category_order_df is not None and not category_order_df.empty:
        for column in category_order_df.columns:
            names.update(load_category_order_list(category_order_df, column))
    return {name for name in names if name}


def _category_series(df: pd.DataFrame) -> pd.Series:
    if "Категория агрег." in df.columns:
        return df["Категория агрег."].fillna("").astype(str).str.strip()
    if "Категория" in df.columns:
        return df["Категория"].fillna("").astype(str).str.strip()
    return pd.Series([""] * len(df), index=df.index, dtype="string")


def _razrez_series(df: pd.DataFrame) -> pd.Series:
    for col in ("Разрез", "Разрез 1"):
        if col in df.columns:
            return df[col].fillna("").astype(str).map(normalize_razrez_value)
    return pd.Series([""] * len(df), index=df.index, dtype="string")


def resolve_spec_value(
    df: pd.DataFrame,
    spec: CategoryRowSpec,
    value_column: str = "Количество",
) -> float:
    """Считает значение для строки category_order по данным продаж."""
    if df.empty:
        return 0.0
    if value_column not in df.columns:
        return 0.0

    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    mask = match_spec_mask(df, spec)
    return float(values.loc[mask].sum())


def resolve_label_value(
    df: pd.DataFrame,
    order: list[str],
    label: str,
    value_column: str = "Количество",
) -> float:
    """Считает значение по подписи строки из category_order."""
    specs = parse_category_order(order)
    label_key = _label_key(label)
    for spec in specs:
        if _label_key(spec.label) == label_key:
            return resolve_spec_value(df, spec, value_column=value_column)
    fallback = CategoryRowSpec(
        label=label,
        parent_category=label,
        razrez=None,
        is_slice=False,
    )
    return resolve_spec_value(df, fallback, value_column=value_column)


def find_category_label_by_fragment(order: list[str], fragment: str) -> str | None:
    """Находит подпись категории в порядке по фрагменту названия."""
    fragment_key = _label_key(fragment)
    for label in category_labels_only(order):
        if fragment_key in _label_key(label):
            return label
    return None


def sum_parent_category(
    df: pd.DataFrame,
    parent_label: str,
    value_column: str = "Количество",
) -> float:
    """Сумма по всей категории (включая все разрезы)."""
    if df.empty or value_column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    categories = _category_series(df).map(_label_key)
    parent_key = _label_key(parent_label)
    return float(values.loc[categories.eq(parent_key)].sum())


def sum_razrez_in_parent(
    df: pd.DataFrame,
    parent_label: str,
    razrez_fragment: str,
    value_column: str = "Количество",
) -> float:
    """Сумма по разрезу (частичное совпадение имени) внутри категории."""
    if df.empty or value_column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    categories = _category_series(df).map(_label_key)
    razrez = _razrez_series(df).map(_label_key)
    parent_key = _label_key(parent_label)
    fragment_key = _label_key(razrez_fragment)
    mask = categories.eq(parent_key) & razrez.str.contains(fragment_key, regex=False, na=False)
    return float(values.loc[mask].sum())


def sum_hookah_products_in_parent(
    df: pd.DataFrame,
    parent_label: str,
    value_column: str = "Количество",
) -> float:
    """Сумма кальянной продукции (Товар ур.1) внутри указанной категории."""
    if df.empty or value_column not in df.columns or "Товар ур.1" not in df.columns:
        return 0.0
    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    categories = _category_series(df).map(_label_key)
    parent_key = _label_key(parent_label)
    level1 = df["Товар ур.1"].fillna("").astype(str).str.strip().str.casefold()
    mask = categories.eq(parent_key) & level1.eq("1.1 кальянная продукция")
    return float(values.loc[mask].sum())


def _is_bks_tks_mask(df: pd.DataFrame) -> pd.Series:
    """Маска строк с БКС/ТКС в разрезе или уровнях товара."""
    if df.empty:
        return pd.Series(dtype=bool)
    patterns = ("бкс", "ткс")
    mask = pd.Series(False, index=df.index)
    razrez = _razrez_series(df).map(_label_key)
    for pattern in patterns:
        mask = mask | razrez.str.contains(pattern, regex=False, na=False)
    for col in ("Товар ур.2", "Товар ур.3", "Товар ур.4"):
        if col not in df.columns:
            continue
        values = df[col].fillna("").astype(str).str.strip().str.casefold()
        for pattern in patterns:
            mask = mask | values.str.contains(pattern, regex=False, na=False)
    return mask


def sum_bks_tks_in_hookah_in_parent(
    df: pd.DataFrame,
    parent_label: str,
    value_column: str = "Количество",
) -> float:
    """Сумма БКС/ТКС внутри кальянной продукции указанной категории."""
    if df.empty or value_column not in df.columns or "Товар ур.1" not in df.columns:
        return 0.0
    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0.0)
    categories = _category_series(df).map(_label_key)
    parent_key = _label_key(parent_label)
    level1 = df["Товар ур.1"].fillna("").astype(str).str.strip().str.casefold()
    hookah_mask = categories.eq(parent_key) & level1.eq("1.1 кальянная продукция")
    mask = hookah_mask & _is_bks_tks_mask(df)
    return float(values.loc[mask].sum())


def calc_ai_misc_breakdown(
    df: pd.DataFrame,
    category_order: list[str],
    value_column: str = "Количество",
) -> tuple[float, float, float, float]:
    """Возвращает (картриджи, бкс/ткс в кальяне, прочие итого, вся категория) для ИИ-отчёта."""
    misc_label = find_category_label_by_fragment(category_order, "прочие товары")
    if misc_label is None:
        return 0.0, 0.0, 0.0, 0.0

    misc_total = sum_parent_category(df, misc_label, value_column=value_column)
    cartridges = sum_razrez_in_parent(
        df, misc_label, "картридж", value_column=value_column
    )
    hookah = sum_hookah_products_in_parent(df, misc_label, value_column=value_column)
    bks = sum_bks_tks_in_hookah_in_parent(df, misc_label, value_column=value_column)
    # БКС/ТКС остаются в «Прочих товарах», остальная кальянная продукция вычитается.
    misc_net = misc_total - cartridges - hookah + bks
    return cartridges, bks, misc_net, misc_total


def extract_category_row_values(
    df: pd.DataFrame,
    order: list[str],
    value_column: str = "Количество",
    *,
    format_value: Callable[[float], str] | None = None,
) -> dict[str, str]:
    """Возвращает словарь {подпись строки: отформатированное значение}."""
    specs = parse_category_order(order)
    rows: dict[str, str] = {}
    for spec in specs:
        value = resolve_spec_value(df, spec, value_column=value_column)
        if format_value is not None:
            rows[spec.label] = format_value(value)
        else:
            rows[spec.label] = value
    return rows
