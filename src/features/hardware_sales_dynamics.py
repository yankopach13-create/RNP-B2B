"""Динамика продаж pod-систем и расходников (железо B2B).

Простая сверка со справочником Sales_pod_cartridge:
- поды → сумма «Количество» по совпадению с Товар ур.3;
- расходники → сумма по совпадению с Товар ур.4 (если пусто/«-» — по ур.3);
- порядок строк — как в справочнике.
"""

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
    level: int  # 3 = под (ур.3), 4 = расходник (ур.4)


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
    lower = _display_product_name(name).casefold()
    if (
        lower.startswith("под-система")
        or lower.startswith("под система")
        or lower.startswith("стартовый комплект")
        or lower.startswith("стартовый набор")
    ):
        return 3
    return 4


def product_level_to_category(level: int) -> str:
    return CATEGORY_PODS_LABEL if level == 3 else CATEGORY_CONSUMABLES_LABEL


def category_label_to_level(category: str) -> int:
    normalized = _display_product_name(category).casefold()
    if not normalized:
        return 4
    if normalized in {"поды", "pod", "pods", "под-системы", "под системы"}:
        return 3
    if "расход" in normalized:
        return 4
    if "pod" in normalized or "под" in normalized:
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


def _normalize_sales_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит продажи к ур.3 / ур.4 / Количество (+ категория, если есть)."""
    prepared = _rename_product_level_columns(df.copy())

    level3_col = _find_column(prepared, LEVEL3_ALIASES) or (
        LEVEL3_COLUMN if LEVEL3_COLUMN in prepared.columns else None
    )
    level4_col = _find_column(prepared, LEVEL4_ALIASES) or (
        LEVEL4_COLUMN if LEVEL4_COLUMN in prepared.columns else None
    )
    quantity_col = _find_column(prepared, QUANTITY_ALIASES)

    missing: list[str] = []
    if level3_col is None:
        missing.append(LEVEL3_COLUMN)
    if quantity_col is None:
        missing.append(QUANTITY_COLUMN)
    if missing:
        raise ValueError(
            "В файле продаж не хватает столбцов: "
            + ", ".join(missing)
            + ". Ожидаются: Товар ур.3, Товар ур.4, Количество."
        )

    result = pd.DataFrame(
        {
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
    if "Категория агрег." in prepared.columns:
        result["Категория агрег."] = prepared["Категория агрег."].map(
            _display_product_name
        )
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


def _build_level_sales_maps(
    sales_df: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float], dict[str, str], dict[str, str]]:
    """Карты продаж по всем строкам: ур.3 и ур.4 отдельно."""
    sales_level3: dict[str, float] = {}
    sales_level4: dict[str, float] = {}
    names3: dict[str, str] = {}
    names4: dict[str, str] = {}

    for _, row in sales_df.iterrows():
        qty = float(row[QUANTITY_COLUMN])
        if qty <= 0:
            continue
        name3 = _display_product_name(row[LEVEL3_COLUMN])
        name4 = _normalize_level4_value(row[LEVEL4_COLUMN])
        if name3:
            _add_to_sales_map(sales_level3, names3, name3, qty)
        if name4:
            _add_to_sales_map(sales_level4, names4, name4, qty)

    return sales_level3, sales_level4, names3, names4


def _parse_reference_products(reference_df: pd.DataFrame) -> list[ReferenceProduct]:
    """Список товаров из Sales_pod_cartridge в порядке листа."""
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

    product_col = columns.get(REFERENCE_PRODUCT_COLUMN)
    category_col = columns.get(REFERENCE_CATEGORY_COLUMN)
    level3_col = columns.get(LEVEL3_COLUMN)
    level4_col = columns.get(LEVEL4_COLUMN)

    for _, row in reference_df.iterrows():
        name = ""
        level = 4

        if product_col is not None:
            name = _display_product_name(row.get(product_col))
            if name:
                level = (
                    _level_from_category_or_name(row.get(category_col, ""), name)
                    if category_col is not None
                    else _infer_reference_product_level(name)
                )

        if not name and level4_col is not None:
            name = _display_product_name(row.get(level4_col))
            if name:
                level = 4

        if not name and level3_col is not None:
            name = _display_product_name(row.get(level3_col))
            if name:
                level = 3

        if not name and product_col is None and level3_col is None and level4_col is None:
            first_col = reference_df.columns[0]
            name = _display_product_name(row.get(first_col))
            if name:
                level = (
                    _level_from_category_or_name(row.get(category_col, ""), name)
                    if category_col is not None
                    else _infer_reference_product_level(name)
                )

        if name:
            _append(name, level)

    return products


def _resolve_sales_quantity(
    product: ReferenceProduct,
    sales_level3: dict[str, float],
    sales_level4: dict[str, float],
) -> float:
    """Под → ур.3; расходник → ур.4, иначе ур.3."""
    key = _normalize_product_name(product.name)
    if product.level == 3:
        return float(sales_level3.get(key, 0.0))
    qty4 = float(sales_level4.get(key, 0.0))
    if qty4 > 0:
        return qty4
    return float(sales_level3.get(key, 0.0))


def _discover_new_products(
    reference_products: list[ReferenceProduct],
    sales_df: pd.DataFrame,
) -> list[ReferenceProduct]:
    """Новинки: поды/расходники из продаж по категории РНП, которых нет в справочнике."""
    known = {
        _normalize_product_name(product.name)
        for product in reference_products
        if _normalize_product_name(product.name)
    }
    discovered: dict[str, tuple[ReferenceProduct, float]] = {}

    has_category = "Категория агрег." in sales_df.columns

    for _, row in sales_df.iterrows():
        qty = float(row[QUANTITY_COLUMN])
        if qty <= 0:
            continue
        name3 = _display_product_name(row[LEVEL3_COLUMN])
        name4 = _normalize_level4_value(row[LEVEL4_COLUMN])
        category = row["Категория агрег."] if has_category else ""

        cat_text = _display_product_name(category).casefold()
        is_pod = "pod-систем" in cat_text or "pod систем" in cat_text
        is_cons = "расходник" in cat_text

        if has_category:
            if is_pod and name3:
                name, level = name3, 3
            elif is_cons:
                name = name4 or name3
                if not name:
                    continue
                level = 4
            else:
                continue
        else:
            if name3 and _infer_reference_product_level(name3) == 3:
                name, level = name3, 3
            else:
                continue

        key = _normalize_product_name(name)
        if not key or key in known:
            continue
        existing = discovered.get(key)
        if existing is None:
            discovered[key] = (ReferenceProduct(name=name, level=level), qty)
        else:
            product, prev = existing
            discovered[key] = (product, prev + qty)

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
    """Добавляет новые товары в конец справочника."""
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
    """Таблица в порядке Sales_pod_cartridge + новинки в конце."""
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
    sales_level3, sales_level4, _names3, _names4 = _build_level_sales_maps(
        normalized_sales
    )

    candidates = _discover_new_products(reference_products, normalized_sales)

    # Порядок справочника, затем новинки
    all_products = reference_products + candidates
    rows = [
        {
            "Товар": product.name,
            "Продажи, шт.": _resolve_sales_quantity(
                product, sales_level3, sales_level4
            ),
        }
        for product in all_products
    ]

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
    return build_hardware_sales_result(reference_df, sales_df).table
