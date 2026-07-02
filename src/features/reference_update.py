from __future__ import annotations

import pandas as pd

from data.references import (
    REF_CATEGORIES,
    REF_CONTRACTORS,
    append_reference_rows,
    get_reference_label,
    load_reference,
    patch_reference_cells,
    reference_exists,
)
from features.category_order import (
    get_category_source_column,
    get_razrez_source_column,
)


def _prepare_contractors_df(df: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    if "Контрагент" not in df.columns:
        return None, "В справочнике контрагентов нет столбца «Контрагент»."
    if "Подразделение" not in df.columns:
        return None, "В справочнике контрагентов нет столбца «Подразделение»."
    return df, None


def _prepare_categories_df(df: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    cat_col = get_category_source_column(df)
    if cat_col is None:
        return None, "В справочнике категорий нет столбца «Категория»."
    required = ["Товар ур.1", "Товар ур.2", "Товар ур.3"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return None, f"В справочнике категорий нет столбцов: {', '.join(missing)}."
    razrez_col = get_razrez_source_column(df)
    if razrez_col is None:
        df = df.copy()
        df["Разрез"] = ""
    return df, None


def batch_add_clients_to_reference(
    items: list[tuple[str, str]],
) -> list[tuple[bool, str]]:
    """Пакетное добавление/обновление клиентов — одно чтение и одна запись."""
    label = get_reference_label(REF_CONTRACTORS)
    if not items:
        return []

    if not reference_exists(REF_CONTRACTORS):
        message = f"Справочник не найден: {label}"
        return [(False, message) for _ in items]

    try:
        df = load_reference(REF_CONTRACTORS)
    except Exception as exc:  # noqa: BLE001
        message = f"Не удалось прочитать справочник контрагентов: {exc}"
        return [(False, message) for _ in items]

    df, error = _prepare_contractors_df(df)
    if error or df is None:
        return [(False, error or "Ошибка справочника контрагентов.") for _ in items]

    results: list[tuple[bool, str]] = []
    rows_to_append: list[dict[str, object]] = []
    cell_patches: list[tuple[int, str, object]] = []

    existing_clients_norm = (
        df["Контрагент"].fillna("").astype(str).str.strip().str.lower()
    )
    subdivisions_norm = df["Подразделение"].fillna("").astype(str).str.strip()
    pending_client_names: set[str] = set()

    for client_name, subdivision in items:
        client = str(client_name).strip()
        subdivision_value = str(subdivision).strip()
        if not client:
            results.append((False, "Пустое имя клиента."))
            continue
        if not subdivision_value:
            results.append(
                (False, f"Для клиента «{client}» не выбрано подразделение.")
            )
            continue

        client_lower = client.lower()
        if client_lower in pending_client_names:
            results.append(
                (False, f"Клиент «{client}» уже добавлен в этой операции.")
            )
            continue

        matched_idx = df.index[
            existing_clients_norm.to_numpy() == client_lower
        ].tolist()
        if matched_idx:
            empty_subdivision_idx = [
                idx for idx in matched_idx if not subdivisions_norm.loc[idx]
            ]
            if empty_subdivision_idx:
                target_idx = empty_subdivision_idx[0]
                cell_patches.append((target_idx, "Подразделение", subdivision_value))
                subdivisions_norm.loc[target_idx] = subdivision_value
                if "Сегмент" in df.columns:
                    segment_value = str(df.loc[target_idx, "Сегмент"]).strip()
                    if not segment_value or segment_value.lower() == "nan":
                        cell_patches.append((target_idx, "Сегмент", "C"))
                results.append(
                    (True, f"Обновлён клиент «{client}» (заполнено подразделение).")
                )
            else:
                results.append((False, f"Клиент «{client}» уже есть в справочнике."))
            continue

        new_row: dict[str, object] = {col: "" for col in df.columns}
        new_row["Контрагент"] = client
        new_row["Подразделение"] = subdivision_value
        if "Сегмент" in df.columns:
            new_row["Сегмент"] = "C"
        rows_to_append.append(new_row)
        pending_client_names.add(client_lower)
        results.append((True, f"Добавлен клиент «{client}»."))

    try:
        if cell_patches:
            patch_reference_cells(REF_CONTRACTORS, cell_patches)
        if rows_to_append:
            append_reference_rows(REF_CONTRACTORS, rows_to_append)
    except Exception as exc:  # noqa: BLE001
        message = f"Не удалось записать справочник контрагентов: {exc}"
        return [
            (False, message) if ok else (ok, msg)
            for ok, msg in results
        ]

    return results


def batch_add_products_to_reference(
    items: list[tuple[tuple[str, str, str], str, str]],
) -> list[tuple[bool, str]]:
    """Пакетное добавление товаров — одно чтение и одна запись."""
    label = get_reference_label(REF_CATEGORIES)
    if not items:
        return []

    if not reference_exists(REF_CATEGORIES):
        message = f"Справочник не найден: {label}"
        return [(False, message) for _ in items]

    try:
        df = load_reference(REF_CATEGORIES)
    except Exception as exc:  # noqa: BLE001
        message = f"Не удалось прочитать справочник категорий: {exc}"
        return [(False, message) for _ in items]

    df, error = _prepare_categories_df(df)
    if error or df is None:
        return [(False, error or "Ошибка справочника категорий.") for _ in items]

    cat_col = get_category_source_column(df)
    razrez_col = get_razrez_source_column(df) or "Разрез"

    results: list[tuple[bool, str]] = []
    rows_to_append: list[dict[str, object]] = []
    existing_keys = set(
        (
            df["Товар ур.1"].fillna("").astype(str).str.strip().str.lower()
            + "|||"
            + df["Товар ур.2"].fillna("").astype(str).str.strip().str.lower()
            + "|||"
            + df["Товар ур.3"].fillna("").astype(str).str.strip().str.lower()
        ).tolist()
    )

    for product_levels, category, razrez in items:
        p1, p2, p3 = (
            str(product_levels[0]).strip(),
            str(product_levels[1]).strip(),
            str(product_levels[2]).strip(),
        )
        category_value = str(category).strip()
        razrez_value = str(razrez).strip()

        if not category_value:
            results.append(
                (False, f"Для товара «{p1} / {p2} / {p3}» не выбрана категория.")
            )
            continue

        new_key = f"{p1.lower()}|||{p2.lower()}|||{p3.lower()}"
        if new_key in existing_keys:
            results.append(
                (False, f"Товар «{p1} / {p2} / {p3}» уже есть в справочнике.")
            )
            continue

        new_row: dict[str, object] = {col: "" for col in df.columns}
        new_row["Товар ур.1"] = p1
        new_row["Товар ур.2"] = p2
        new_row["Товар ур.3"] = p3
        new_row[cat_col] = category_value
        new_row[razrez_col] = razrez_value
        rows_to_append.append(new_row)
        existing_keys.add(new_key)
        results.append((True, f"Добавлен товар «{p1} / {p2} / {p3}»."))

    if rows_to_append:
        try:
            append_reference_rows(REF_CATEGORIES, rows_to_append)
        except Exception as exc:  # noqa: BLE001
            message = f"Не удалось записать справочник категорий: {exc}"
            return [
                (False, message) if ok else (ok, msg)
                for ok, msg in results
            ]

    return results


def add_client_to_reference(client_name: str, subdivision: str) -> tuple[bool, str]:
    results = batch_add_clients_to_reference([(client_name, subdivision)])
    return results[0] if results else (False, "Нет данных для добавления.")


def add_product_to_reference(
    product_levels: tuple[str, str, str],
    category: str,
    razrez: str,
) -> tuple[bool, str]:
    results = batch_add_products_to_reference(
        [(product_levels, category, razrez)]
    )
    return results[0] if results else (False, "Нет данных для добавления.")
