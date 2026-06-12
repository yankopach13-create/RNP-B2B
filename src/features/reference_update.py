from __future__ import annotations

import pandas as pd

from data.references import (
    REF_CATEGORIES,
    REF_CONTRACTORS,
    get_reference_label,
    load_reference,
    reference_exists,
    save_reference,
)


def add_client_to_reference(client_name: str, subdivision: str) -> tuple[bool, str]:
    client = str(client_name).strip()
    subdivision_value = str(subdivision).strip()
    label = get_reference_label(REF_CONTRACTORS)
    if not client:
        return False, "Пустое имя клиента."
    if not subdivision_value:
        return False, f"Для клиента «{client}» не выбрано подразделение."
    if not reference_exists(REF_CONTRACTORS):
        return False, f"Справочник не найден: {label}"

    try:
        df = load_reference(REF_CONTRACTORS)
    except Exception as exc:  # noqa: BLE001
        return False, f"Не удалось прочитать справочник контрагентов: {exc}"

    if "Контрагент" not in df.columns:
        return False, "В справочнике контрагентов нет столбца «Контрагент»."
    if "Подразделение" not in df.columns:
        return False, "В справочнике контрагентов нет столбца «Подразделение»."

    existing_clients_norm = (
        df["Контрагент"].fillna("").astype(str).str.strip().str.lower()
    )
    matched_idx = df.index[existing_clients_norm == client.lower()].tolist()
    if matched_idx:
        subdivisions_norm = (
            df["Подразделение"].fillna("").astype(str).str.strip()
        )
        empty_subdivision_idx = [
            idx for idx in matched_idx if not subdivisions_norm.loc[idx]
        ]
        if empty_subdivision_idx:
            target_idx = empty_subdivision_idx[0]
            df.loc[target_idx, "Подразделение"] = subdivision_value
            if "Сегмент" in df.columns:
                segment_value = str(df.loc[target_idx, "Сегмент"]).strip()
                if not segment_value or segment_value.lower() == "nan":
                    df.loc[target_idx, "Сегмент"] = "C"
            try:
                save_reference(REF_CONTRACTORS, df)
            except Exception as exc:  # noqa: BLE001
                return False, f"Не удалось записать справочник контрагентов: {exc}"
            return True, f"Обновлён клиент «{client}» (заполнено подразделение)."
        return False, f"Клиент «{client}» уже есть в справочнике."

    new_row: dict[str, object] = {col: "" for col in df.columns}
    new_row["Контрагент"] = client
    new_row["Подразделение"] = subdivision_value
    if "Сегмент" in df.columns:
        new_row["Сегмент"] = "C"

    updated = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    try:
        save_reference(REF_CONTRACTORS, updated)
    except Exception as exc:  # noqa: BLE001
        return False, f"Не удалось записать справочник контрагентов: {exc}"

    return True, f"Добавлен клиент «{client}»."


def add_product_to_reference(
    product_levels: tuple[str, str, str],
    category: str,
    slice1: str,
    slice2: str,
) -> tuple[bool, str]:
    p1, p2, p3 = (
        str(product_levels[0]).strip(),
        str(product_levels[1]).strip(),
        str(product_levels[2]).strip(),
    )
    category_value = str(category).strip()
    slice1_value = str(slice1).strip()
    slice2_value = str(slice2).strip()
    label = get_reference_label(REF_CATEGORIES)

    if not category_value:
        return False, f"Для товара «{p1} / {p2} / {p3}» не выбрана категория."
    if not reference_exists(REF_CATEGORIES):
        return False, f"Справочник не найден: {label}"

    try:
        df = load_reference(REF_CATEGORIES)
    except Exception as exc:  # noqa: BLE001
        return False, f"Не удалось прочитать справочник категорий: {exc}"

    required = ["Товар ур.1", "Товар ур.2", "Товар ур.3", "Категория:"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return False, f"В справочнике категорий нет столбцов: {', '.join(missing)}."

    for col in ("Разрез 1", "Разрез 2"):
        if col not in df.columns:
            df[col] = ""

    existing_key = (
        df["Товар ур.1"].fillna("").astype(str).str.strip().str.lower()
        + "|||"
        + df["Товар ур.2"].fillna("").astype(str).str.strip().str.lower()
        + "|||"
        + df["Товар ур.3"].fillna("").astype(str).str.strip().str.lower()
    )
    new_key = f"{p1.lower()}|||{p2.lower()}|||{p3.lower()}"
    if new_key in set(existing_key.tolist()):
        return False, f"Товар «{p1} / {p2} / {p3}» уже есть в справочнике."

    new_row: dict[str, object] = {col: "" for col in df.columns}
    new_row["Товар ур.1"] = p1
    new_row["Товар ур.2"] = p2
    new_row["Товар ур.3"] = p3
    new_row["Категория:"] = category_value
    new_row["Разрез 1"] = slice1_value
    new_row["Разрез 2"] = slice2_value

    updated = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    try:
        save_reference(REF_CATEGORIES, updated)
    except Exception as exc:  # noqa: BLE001
        return False, f"Не удалось записать справочник категорий: {exc}"

    return True, f"Добавлен товар «{p1} / {p2} / {p3}»."
