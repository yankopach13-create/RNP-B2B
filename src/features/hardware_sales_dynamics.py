"""Динамика продаж pod-систем и картриджей (железо B2B)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

LEVEL1_COLUMN = "Товар ур.1"
LEVEL3_COLUMN = "Товар ур.3"
LEVEL4_COLUMN = "Товар ур.4"
QUANTITY_COLUMN = "Количество"
REFERENCE_PRODUCT_COLUMN = "Товар"
REFERENCE_CATEGORY_COLUMN = "Категория"
CATEGORY_PODS_LABEL = "Поды"
CATEGORY_CONSUMABLES_LABEL = "Расходники"
HARDWARE_CATEGORY_OPTIONS = (CATEGORY_PODS_LABEL, CATEGORY_CONSUMABLES_LABEL)

LEVEL1_ALIASES = (
    "Товар ур.1",
    "Товар 1",
    "Товар1",
    "Товар ур. 1",
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
LEVEL4_EMPTY_MARKERS = frozenset({"-", "—", "–", "―", "‑"})


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


def _is_pod_level1(value: object) -> bool:
    text = _display_product_name(value).casefold()
    if not text:
        return False
    markers = (
        "pod-mod",
        "pod mod",
        "pod-систем",
        "pod систем",
        "pod - систем",
        "2.0 pod",
    )
    return any(marker in text for marker in markers) or text.startswith("pod")


def _is_consumable_level1(value: object) -> bool:
    text = _display_product_name(value).casefold()
    if not text:
        return False
    return any(
        marker in text
        for marker in ("картридж", "испарител", "расходник", "2.3 расход")
    )


def _is_level4_empty(value: object) -> bool:
    text = _display_product_name(value)
    if not text:
        return True
    return text in LEVEL4_EMPTY_MARKERS


def _normalize_levels_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит загруженный файл к единой структуре."""
    level1_col = _find_column(df, LEVEL1_ALIASES)
    level3_col = _find_column(df, LEVEL3_ALIASES)
    level4_col = _find_column(df, LEVEL4_ALIASES)
    quantity_col = _find_column(df, QUANTITY_ALIASES)

    missing: list[str] = []
    if level1_col is None:
        missing.append(LEVEL1_COLUMN)
    if level3_col is None:
        missing.append(LEVEL3_COLUMN)
    if level4_col is None:
        missing.append(LEVEL4_COLUMN)
    if quantity_col is None:
        missing.append(QUANTITY_COLUMN)
    if missing:
        raise ValueError(
            "В файле не хватает столбцов: "
            + ", ".join(missing)
            + ". Ожидаются: Товар ур.1, Товар ур.3, Товар ур.4, Количество."
        )

    return pd.DataFrame(
        {
            LEVEL1_COLUMN: df[level1_col].map(_display_product_name),
            LEVEL3_COLUMN: df[level3_col].map(_display_product_name),
            LEVEL4_COLUMN: df[level4_col].map(_display_product_name),
            QUANTITY_COLUMN: pd.to_numeric(df[quantity_col], errors="coerce").fillna(0.0),
        }
    )


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


def _build_sales_maps_from_levels(
    levels_df: pd.DataFrame,
) -> tuple[
    dict[str, float],
    dict[str, float],
    dict[str, str],
    dict[str, float],
    dict[str, str],
    dict[str, float],
    dict[str, str],
]:
    """
    Возвращает:
    - sales_level3: все продажи, сопоставляемые по ур.3
    - sales_level4: все продажи, сопоставляемые по ур.4
    - display_names: объединённые отображаемые имена
    - pod_sales_level3: только POD по ур.3 (для обнаружения новинок)
    - pod_names_level3
    - cons_sales_level4: расходники по ур.4
    - cons_names_level4
    - cons_sales_level3: расходники с прочерком в ур.4
    - cons_names_level3
    """
    sales_level3: dict[str, float] = {}
    sales_level4: dict[str, float] = {}
    display_names: dict[str, str] = {}

    pod_sales_level3: dict[str, float] = {}
    pod_names_level3: dict[str, str] = {}

    cons_sales_level4: dict[str, float] = {}
    cons_names_level4: dict[str, str] = {}

    cons_sales_level3: dict[str, float] = {}
    cons_names_level3: dict[str, str] = {}

    for _, row in levels_df.iterrows():
        qty = float(row[QUANTITY_COLUMN])
        if qty <= 0:
            continue

        level1 = row[LEVEL1_COLUMN]
        name3 = _display_product_name(row[LEVEL3_COLUMN])
        name4 = _display_product_name(row[LEVEL4_COLUMN])

        if _is_pod_level1(level1):
            if not name3:
                continue
            _add_to_sales_map(sales_level3, display_names, name3, qty)
            _add_to_sales_map(pod_sales_level3, pod_names_level3, name3, qty)
            continue

        if _is_consumable_level1(level1):
            if _is_level4_empty(name4):
                if not name3:
                    continue
                _add_to_sales_map(sales_level3, display_names, name3, qty)
                _add_to_sales_map(cons_sales_level3, cons_names_level3, name3, qty)
            else:
                _add_to_sales_map(sales_level4, display_names, name4, qty)
                _add_to_sales_map(cons_sales_level4, cons_names_level4, name4, qty)

    return (
        sales_level3,
        sales_level4,
        display_names,
        pod_sales_level3,
        pod_names_level3,
        cons_sales_level4,
        cons_names_level4,
        cons_sales_level3,
        cons_names_level3,
    )


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
    return float(sales_level3.get(key, 0.0))


def _discover_new_products(
    reference_products: list[ReferenceProduct],
    pod_sales_level3: dict[str, float],
    pod_names_level3: dict[str, str],
    cons_sales_level4: dict[str, float],
    cons_names_level4: dict[str, str],
    cons_sales_level3: dict[str, float],
    cons_names_level3: dict[str, str],
) -> list[ReferenceProduct]:
    """Новинки по типу из ур.1: POD — ур.3, расходники — ур.4 или ур.3 при прочерке."""
    known_keys = {
        _normalize_product_name(product.name)
        for product in reference_products
        if _normalize_product_name(product.name)
    }

    discovered: list[tuple[ReferenceProduct, float]] = []

    def _append_candidate(
        key: str,
        qty: float,
        display_names: dict[str, str],
        level: int,
    ) -> None:
        if qty <= 0 or key in known_keys:
            return
        known_keys.add(key)
        discovered.append(
            (
                ReferenceProduct(name=display_names.get(key, key), level=level),
                qty,
            )
        )

    for key, qty in pod_sales_level3.items():
        _append_candidate(key, qty, pod_names_level3, 3)

    for key, qty in cons_sales_level4.items():
        _append_candidate(key, qty, cons_names_level4, 4)

    for key, qty in cons_sales_level3.items():
        _append_candidate(key, qty, cons_names_level3, 3)

    discovered.sort(key=lambda item: (-item[1], item[0].name.casefold()))
    return [product for product, _ in discovered]


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
    levels_df: pd.DataFrame | None,
) -> HardwareSalesResult:
    """Считает таблицу продаж и список кандидатов для дополнения справочника."""
    ref_source = reference_df if reference_df is not None else pd.DataFrame()
    reference_products = _parse_reference_products(ref_source)

    if levels_df is None or levels_df.empty:
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

    normalized_levels = _normalize_levels_dataframe(levels_df)
    (
        sales_level3,
        sales_level4,
        _display_names,
        pod_sales_level3,
        pod_names_level3,
        cons_sales_level4,
        cons_names_level4,
        cons_sales_level3,
        cons_names_level3,
    ) = _build_sales_maps_from_levels(normalized_levels)

    candidates = _discover_new_products(
        reference_products,
        pod_sales_level3,
        pod_names_level3,
        cons_sales_level4,
        cons_names_level4,
        cons_sales_level3,
        cons_names_level3,
    )

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
    levels_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Таблица: товары из справочника + новые pod/картриджи, продажи в шт."""
    return build_hardware_sales_result(reference_df, levels_df).table
