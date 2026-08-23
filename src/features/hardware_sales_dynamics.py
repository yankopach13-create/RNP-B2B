"""Динамика продаж pod-систем и картриджей (железо B2B)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from features.data_prep import (
    _normalize_level4_value,
    _rename_product_level_columns,
)

LEVEL2_COLUMN = "Товар ур.2"
LEVEL3_COLUMN = "Товар ур.3"
LEVEL4_COLUMN = "Товар ур.4"
QUANTITY_COLUMN = "Количество"
CATEGORY_COLUMN = "Категория агрег."
REFERENCE_PRODUCT_COLUMN = "Товар"
REFERENCE_CATEGORY_COLUMN = "Категория"
CATEGORY_PODS_LABEL = "Поды"
CATEGORY_CONSUMABLES_LABEL = "Расходники"
HARDWARE_CATEGORY_OPTIONS = (CATEGORY_PODS_LABEL, CATEGORY_CONSUMABLES_LABEL)

LEVEL2_ALIASES = (
    "Товар ур.2",
    "Товар 2",
    "Товар2",
    "Товар ур. 2",
)
LEVEL3_ALIASES = (
    "Товар ур.3",
    "Товар 3",
    "Товар3",
    "Товар ур. 3",
)
LEVEL4_ALIASES = (
    "Товар ур.4",
    "Товар 4",
    "Товар4",
    "Товар ур. 4",
)
QUANTITY_ALIASES = (
    "Количество",
    "количество",
    "Кол-во",
    "Кол во",
)


@dataclass(frozen=True)
class ReferenceProduct:
    name: str
    level: int


@dataclass
class HardwareSalesResult:
    """Результат расчёта блока «Динамика продаж железа»."""

    table: pd.DataFrame
    reference_products: list[ReferenceProduct] = field(default_factory=list)
    candidates_for_reference: list[ReferenceProduct] = field(default_factory=list)


def _normalize_product_name(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text == "__NONE__" or text.lower() == "nan":
        return ""
    text = (
        text.replace("«", '"')
        .replace("»", '"')
        .replace("“", '"')
        .replace("”", '"')
        .replace("„", '"')
    )
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _display_product_name(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text == "__NONE__" or text.lower() == "nan":
        return ""
    return text


def _infer_reference_product_level(name: str) -> int:
    """Под-системы в справочнике — ур.3, остальное — ур.4."""
    lower = _display_product_name(name).casefold()
    if lower.startswith("под-система") or lower.startswith("под система"):
        return 3
    return 4


def product_level_to_category(level: int) -> str:
    return CATEGORY_PODS_LABEL if level == 3 else CATEGORY_CONSUMABLES_LABEL


def category_label_to_level(category: str) -> int:
    normalized = _display_product_name(category).casefold()
    if normalized in {"поды", "pod", "pods", "под-системы", "под системы"}:
        return 3
    return 4


def _level_from_category_or_name(category: object, name: str) -> int:
    category_text = _display_product_name(category)
    if category_text:
        return category_label_to_level(category_text)
    return _infer_reference_product_level(name)


def _find_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    column_map = {str(col).strip().casefold(): str(col) for col in df.columns}
    for alias in aliases:
        actual = column_map.get(alias.casefold())
        if actual is not None:
            return actual
    return None


def _is_pod_category(category: object) -> bool:
    text = _display_product_name(category).casefold()
    if not text:
        return False
    return (
        "pod-систем" in text
        or "pod систем" in text
        or text.startswith("pod")
        or text.startswith("pod-")
    )


def _is_consumable_category(category: object) -> bool:
    text = _display_product_name(category).casefold()
    if not text:
        return False
    return "расходник" in text or "картридж" in text


def _normalize_sales_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит загруженные продажи к единой структуре для блока железа."""
    prepared = _rename_product_level_columns(df.copy())

    level2_col = _find_column(prepared, LEVEL2_ALIASES) or (
        LEVEL2_COLUMN if LEVEL2_COLUMN in prepared.columns else None
    )
    level3_col = _find_column(prepared, LEVEL3_ALIASES) or (
        LEVEL3_COLUMN if LEVEL3_COLUMN in prepared.columns else None
    )
    level4_col = _find_column(prepared, LEVEL4_ALIASES) or (
        LEVEL4_COLUMN if LEVEL4_COLUMN in prepared.columns else None
    )
    quantity_col = _find_column(prepared, QUANTITY_ALIASES)

    missing: list[str] = []
    if level2_col is None:
        missing.append(LEVEL2_COLUMN)
    if level3_col is None:
        missing.append(LEVEL3_COLUMN)
    if quantity_col is None:
        missing.append(QUANTITY_COLUMN)
    if missing:
        raise ValueError(
            "В файле продаж не хватает столбцов: "
            + ", ".join(missing)
            + ". Ожидаются: Товар ур.2, Товар ур.3, Товар ур.4, Количество."
        )

    result = pd.DataFrame(
        {
            LEVEL2_COLUMN: prepared[level2_col].map(_display_product_name),
            LEVEL3_COLUMN: prepared[level3_col].map(_display_product_name),
            LEVEL4_COLUMN: (
                prepared[level4_col].map(_normalize_level4_value)
                if level4_col is not None
                else ""
            ),
            QUANTITY_COLUMN: pd.to_numeric(
                prepared[quantity_col], errors="coerce"
            ).fillna(0.0),
        }
    )
    if CATEGORY_COLUMN in prepared.columns:
        result[CATEGORY_COLUMN] = prepared[CATEGORY_COLUMN].map(_display_product_name)
    else:
        result[CATEGORY_COLUMN] = ""
    return result


def _add_to_sales_map(
    quantities: dict[str, float],
    display_names: dict[str, str],
    name: str,
    qty: float,
) -> None:
    key = _normalize_product_name(name)
    if not key or qty <= 0:
        return
    quantities[key] = quantities.get(key, 0.0) + qty
    if key not in display_names:
        display_names[key] = name


def _build_sales_maps_from_sales(
    sales_df: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
    """Агрегирует продажи pod/расходников: отдельные карты ур.3 и ур.4 без двойного учёта."""
    sales_level3: dict[str, float] = {}
    sales_level4: dict[str, float] = {}
    display_names: dict[str, str] = {}

    for _, row in sales_df.iterrows():
        qty = float(row[QUANTITY_COLUMN])
        if qty <= 0:
            continue

        category = row.get(CATEGORY_COLUMN, "")
        name3 = _display_product_name(row[LEVEL3_COLUMN])
        name4 = _normalize_level4_value(row[LEVEL4_COLUMN])

        if _is_pod_category(category):
            if name3:
                _add_to_sales_map(sales_level3, display_names, name3, qty)
            continue

        if _is_consumable_category(category):
            if name4:
                _add_to_sales_map(sales_level4, display_names, name4, qty)
            elif name3:
                # Расходник с прочерком в ур.4 — учитываем по ур.3
                _add_to_sales_map(sales_level3, display_names, name3, qty)

    return sales_level3, sales_level4, display_names


def _parse_reference_products(reference_df: pd.DataFrame) -> list[ReferenceProduct]:
    """Возвращает упорядоченный список товаров из справочника Sales_pod_cartridge."""
    if reference_df is None or reference_df.empty:
        return []

    columns = {str(col).strip(): col for col in reference_df.columns}
    products: list[ReferenceProduct] = []
    seen: set[str] = set()

    def _append(name: object, level: int) -> None:
        display = _display_product_name(name)
        key = _normalize_product_name(display)
        if not key or key in seen:
            return
        seen.add(key)
        products.append(ReferenceProduct(name=display, level=level))

    has_level3 = LEVEL3_COLUMN in columns
    has_level4 = LEVEL4_COLUMN in columns

    if has_level3 or has_level4:
        for _, row in reference_df.iterrows():
            level4_name = (
                _display_product_name(row.get(columns[LEVEL4_COLUMN]))
                if has_level4
                else ""
            )
            level3_name = (
                _display_product_name(row.get(columns[LEVEL3_COLUMN]))
                if has_level3
                else ""
            )
            if level4_name:
                _append(level4_name, 4)
            elif level3_name:
                _append(level3_name, 3)
    elif REFERENCE_PRODUCT_COLUMN in columns:
        product_col = columns[REFERENCE_PRODUCT_COLUMN]
        category_col = columns.get(REFERENCE_CATEGORY_COLUMN)
        if category_col:
            for _, row in reference_df.iterrows():
                display = _display_product_name(row.get(product_col))
                if display:
                    _append(
                        display,
                        _level_from_category_or_name(
                            row.get(category_col, ""),
                            display,
                        ),
                    )
        else:
            for value in reference_df[product_col]:
                display = _display_product_name(value)
                if display:
                    _append(display, _infer_reference_product_level(display))
    else:
        first_col = reference_df.columns[0]
        category_col = columns.get(REFERENCE_CATEGORY_COLUMN)
        if category_col:
            for _, row in reference_df.iterrows():
                display = _display_product_name(row.get(first_col))
                if display:
                    _append(
                        display,
                        _level_from_category_or_name(
                            row.get(category_col, ""),
                            display,
                        ),
                    )
        else:
            for value in reference_df[first_col]:
                display = _display_product_name(value)
                if display:
                    _append(display, _infer_reference_product_level(display))

    return products


def _resolve_sales_quantity(
    product: ReferenceProduct,
    sales_level3: dict[str, float],
    sales_level4: dict[str, float],
) -> float:
    key = _normalize_product_name(product.name)
    if product.level == 3:
        return float(sales_level3.get(key, 0.0))
    qty = float(sales_level4.get(key, 0.0))
    if qty > 0:
        return qty
    # Расходник без совпадения в ур.4 — fallback только на ур.3 (строки расходников с «-»)
    if product.level == 4:
        return float(sales_level3.get(key, 0.0))
    return 0.0


def _discover_new_products(
    reference_products: list[ReferenceProduct],
    sales_df: pd.DataFrame,
) -> list[ReferenceProduct]:
    """Новинки: категории Pod-системы / Расходники из продаж, которых нет в справочнике."""
    known_keys = {
        _normalize_product_name(product.name)
        for product in reference_products
        if _normalize_product_name(product.name)
    }

    discovered: dict[str, tuple[ReferenceProduct, float]] = {}

    for _, row in sales_df.iterrows():
        qty = float(row[QUANTITY_COLUMN])
        if qty <= 0:
            continue

        category = row.get(CATEGORY_COLUMN, "")
        name3 = _display_product_name(row[LEVEL3_COLUMN])
        name4 = _normalize_level4_value(row[LEVEL4_COLUMN])

        if _is_pod_category(category):
            name = name3
            level = 3
        elif _is_consumable_category(category):
            name = name4 or name3
            level = 4 if name4 else 3
        else:
            continue

        key = _normalize_product_name(name)
        if not key or key in known_keys:
            continue

        existing = discovered.get(key)
        if existing is None:
            discovered[key] = (ReferenceProduct(name=name, level=level), qty)
        else:
            product, prev_qty = existing
            discovered[key] = (product, prev_qty + qty)

    ordered = sorted(
        discovered.values(),
        key=lambda item: (-item[1], item[0].name.casefold()),
    )
    return [product for product, _ in ordered]


def _reference_product_column(reference_df: pd.DataFrame) -> str:
    columns = {str(col).strip(): col for col in reference_df.columns}
    if REFERENCE_PRODUCT_COLUMN in columns:
        return columns[REFERENCE_PRODUCT_COLUMN]
    return str(reference_df.columns[0])


def append_products_to_cartridge_reference(
    reference_df: pd.DataFrame,
    products: list[ReferenceProduct],
) -> tuple[pd.DataFrame, list[str]]:
    """Добавляет новые товары в конец справочника. Возвращает обновлённый df и список добавленных имён."""
    if reference_df is None or reference_df.empty:
        raise ValueError("Справочник пуст — нечего дополнять.")

    product_col = _reference_product_column(reference_df)
    updated = reference_df.copy()
    if REFERENCE_CATEGORY_COLUMN not in updated.columns:
        updated[REFERENCE_CATEGORY_COLUMN] = ""

    existing_keys = {
        _normalize_product_name(value)
        for value in updated[product_col].tolist()
        if _normalize_product_name(value)
    }

    added_names: list[str] = []
    new_rows: list[dict[str, object]] = []

    for product in products:
        key = _normalize_product_name(product.name)
        if not key or key in existing_keys:
            continue
        existing_keys.add(key)
        added_names.append(product.name)
        row = {col: "" for col in updated.columns}
        row[product_col] = product.name
        row[REFERENCE_CATEGORY_COLUMN] = product_level_to_category(product.level)
        new_rows.append(row)

    if new_rows:
        updated = pd.concat([updated, pd.DataFrame(new_rows)], ignore_index=True)

    return updated, added_names


def build_hardware_sales_result(
    reference_df: pd.DataFrame | None,
    sales_df: pd.DataFrame | None,
) -> HardwareSalesResult:
    """Считает таблицу продаж и список кандидатов для дополнения справочника.

    sales_df — обычные продажи (желательно уже с «Категория агрег.» после prepare_dataset).
    """
    ref_source = reference_df if reference_df is not None else pd.DataFrame()
    reference_products = _parse_reference_products(ref_source)

    if sales_df is None or sales_df.empty:
        rows = [
            {"Товар": product.name, "Продажи, шт.": 0.0}
            for product in reference_products
        ]
        table = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(columns=["Товар", "Продажи, шт."])
        )
        return HardwareSalesResult(
            table=table,
            reference_products=reference_products,
            candidates_for_reference=[],
        )

    normalized_sales = _normalize_sales_dataframe(sales_df)
    sales_level3, sales_level4, _display_names = _build_sales_maps_from_sales(
        normalized_sales
    )

    candidates = _discover_new_products(reference_products, normalized_sales)

    all_products = reference_products + candidates
    rows: list[dict[str, object]] = []
    for product in all_products:
        qty = _resolve_sales_quantity(product, sales_level3, sales_level4)
        rows.append({"Товар": product.name, "Продажи, шт.": qty})

    table = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["Товар", "Продажи, шт."])
    )
    return HardwareSalesResult(
        table=table,
        reference_products=reference_products,
        candidates_for_reference=candidates,
    )


def build_hardware_sales_dynamics_table(
    reference_df: pd.DataFrame | None,
    sales_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Таблица: товары из справочника + новые pod/картриджи, продажи в шт."""
    return build_hardware_sales_result(reference_df, sales_df).table
