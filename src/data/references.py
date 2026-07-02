"""Справочники: Google Sheets (основной источник) с fallback на локальные xlsx."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = PROJECT_ROOT / "data" / "reference"

REF_CONTRACTORS = "contractors"
REF_CATEGORIES = "categories"
REF_CATEGORY_ORDER = "category_order"
REF_DZ_SPEC = "dz_spec"
REF_DZ_TRAD = "dz_trad"
REF_DZ_REMOVE = "dz_remove"
REF_SALES_POD_CARTRIDGE = "sales_pod_cartridge"

DEFAULT_PRELOAD_KEYS: tuple[str, ...] = (
    REF_CONTRACTORS,
    REF_CATEGORIES,
    REF_DZ_SPEC,
    REF_DZ_TRAD,
    REF_DZ_REMOVE,
)

_REFERENCE_META: dict[str, dict[str, str]] = {
    REF_CONTRACTORS: {
        "sheet": "contractors",
        "local": "contractors.xlsx",
        "title": "Контрагенты",
    },
    REF_CATEGORIES: {
        "sheet": "categories",
        "local": "categories.xlsx",
        "title": "Категории товаров",
    },
    REF_CATEGORY_ORDER: {
        "sheet": "category_order",
        "local": "category_order.xlsx",
        "title": "Порядок категорий",
    },
    REF_DZ_SPEC: {
        "sheet": "dz_spec",
        "local": "ДЗ_Спец_Розница.xlsx",
        "title": "ДЗ Спец розница",
    },
    REF_DZ_TRAD: {
        "sheet": "dz_trad",
        "local": "ДЗ_Традиция.xlsx",
        "title": "ДЗ Традиция",
    },
    REF_DZ_REMOVE: {
        "sheet": "dz_remove",
        "local": "ДЗ_Убрать.xlsx",
        "title": "ДЗ Убрать",
    },
    REF_SALES_POD_CARTRIDGE: {
        "sheet": "Sales_pod_cartridge",
        "local": "Sales_pod_cartridge.xlsx",
        "title": "Динамика продаж железа B2B",
    },
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_PLACEHOLDER_SPREADSHEET_ID = "REPLACE_WITH_YOUR_SPREADSHEET_ID"
_REFERENCES_SESSION_KEY = "references_session_cache"
_SHEETS_CACHE_TTL_SEC = 600
_API_MAX_ATTEMPTS = 3
_API_RETRY_DELAY_SEC = 0.6
_API_QUOTA_RETRY_DELAY_SEC = 35

T = TypeVar("T")


class ReferenceConcurrentModificationError(RuntimeError):
    """Справочник изменился другим пользователем между чтением и записью."""


def _references_config() -> dict[str, Any]:
    try:
        return dict(st.secrets.get("references", {}))
    except Exception:  # noqa: BLE001
        return {}


def sheets_configured() -> bool:
    """True, если в secrets заданы учётные данные и ID таблицы."""
    try:
        if "gcp_service_account" not in st.secrets:
            return False
        refs = _references_config()
        spreadsheet_id = str(refs.get("spreadsheet_id", "")).strip()
        return bool(spreadsheet_id) and spreadsheet_id != _PLACEHOLDER_SPREADSHEET_ID
    except Exception:  # noqa: BLE001
        return False


def _sheet_name(key: str) -> str:
    refs = _references_config()
    override = refs.get(f"sheet_{key}")
    if override:
        return str(override).strip()
    return _REFERENCE_META[key]["sheet"]


def _spreadsheet_id() -> str:
    refs = _references_config()
    return str(refs["spreadsheet_id"]).strip()


def get_reference_title(key: str) -> str:
    return _REFERENCE_META[key]["title"]


def get_reference_label(key: str) -> str:
    if sheets_configured():
        return f"лист «{_sheet_name(key)}»"
    return _REFERENCE_META[key]["local"]


def _session_ref_cache() -> dict[str, pd.DataFrame]:
    if _REFERENCES_SESSION_KEY not in st.session_state:
        st.session_state[_REFERENCES_SESSION_KEY] = {}
    return st.session_state[_REFERENCES_SESSION_KEY]


def clear_session_references() -> None:
    """Сбрасывает кэш справочников в session_state (при новой загрузке данных)."""
    st.session_state.pop(_REFERENCES_SESSION_KEY, None)


def reference_exists(key: str) -> bool:
    if key not in _REFERENCE_META:
        return False
    if key in _session_ref_cache():
        return True
    if sheets_configured():
        try:
            _open_worksheet(_spreadsheet_id(), _sheet_name(key))
            return True
        except Exception:  # noqa: BLE001
            return False
    return _local_path(key).exists()


def _resolve_ssl_verify() -> bool | str:
    """Путь к CA-сертификату, True (по умолчанию) или False (корп. прокси)."""
    refs = _references_config()

    ssl_verify = refs.get("ssl_verify", True)
    if isinstance(ssl_verify, str):
        if ssl_verify.strip().lower() in {"false", "0", "no", "off"}:
            return False
        if ssl_verify.strip().lower() in {"true", "1", "yes", "on"}:
            return True

    if ssl_verify is False:
        return False

    ca_bundle = refs.get("ssl_ca_bundle")
    if ca_bundle:
        path = Path(str(ca_bundle).strip())
        if path.is_file():
            return str(path)

    for env_name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        env_path = os.environ.get(env_name, "").strip()
        if env_path and Path(env_path).is_file():
            return env_path

    return True


def _apply_ssl_verify(client) -> None:
    verify = _resolve_ssl_verify()
    if verify is not True:
        client.http_client.session.verify = verify


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "quota exceeded" in message


def _retry_sheets_api(operation: Callable[[], T], *, action: str) -> T:
    last_error: Exception | None = None
    for attempt in range(1, _API_MAX_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= _API_MAX_ATTEMPTS:
                break
            if _is_quota_error(exc):
                time.sleep(_API_QUOTA_RETRY_DELAY_SEC * attempt)
            else:
                time.sleep(_API_RETRY_DELAY_SEC * attempt)
    raise RuntimeError(f"Не удалось выполнить операцию «{action}»: {last_error}") from last_error


@st.cache_resource
def _get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    info = dict(st.secrets["gcp_service_account"])
    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(credentials)
    _apply_ssl_verify(client)
    return client


def _values_to_dataframe(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    header = [str(col).strip() for col in rows[0]]
    if len(rows) == 1:
        return pd.DataFrame(columns=header)
    return pd.DataFrame(rows[1:], columns=header)


def _fetch_worksheet_values(spreadsheet_id: str, worksheet_name: str) -> list[list[Any]]:
    def _read() -> list[list[Any]]:
        client = _get_gspread_client()
        worksheet = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
        return worksheet.get_all_values()

    return _retry_sheets_api(_read, action=f"чтение листа «{worksheet_name}»")


@st.cache_data(ttl=_SHEETS_CACHE_TTL_SEC, show_spinner=False)
def _load_from_sheets_cached(spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    rows = _fetch_worksheet_values(spreadsheet_id, worksheet_name)
    return _values_to_dataframe(rows)


def _load_from_sheets_fresh(spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    rows = _fetch_worksheet_values(spreadsheet_id, worksheet_name)
    return _values_to_dataframe(rows)


def _open_worksheet(spreadsheet_id: str, worksheet_name: str):
    def _open():
        client = _get_gspread_client()
        return client.open_by_key(spreadsheet_id).worksheet(worksheet_name)

    return _retry_sheets_api(_open, action=f"открытие листа «{worksheet_name}»")


def _worksheet_row_count(spreadsheet_id: str, worksheet_name: str) -> int:
    worksheet = _open_worksheet(spreadsheet_id, worksheet_name)
    return len(worksheet.get_all_values())


def _row_dicts_to_sheet_rows(
    header: list[str], rows: list[dict[str, object]]
) -> list[list[object]]:
    return [[row.get(col, "") for col in header] for row in rows]


def _append_rows_to_sheets(
    spreadsheet_id: str,
    worksheet_name: str,
    rows: list[dict[str, object]],
    *,
    header: list[str] | None = None,
) -> None:
    if not rows:
        return

    def _append() -> None:
        worksheet = _open_worksheet(spreadsheet_id, worksheet_name)
        resolved_header = header
        if not resolved_header:
            values = worksheet.get_all_values()
            resolved_header = (
                [str(col).strip() for col in values[0]]
                if values
                else list(rows[0].keys())
            )
        sheet_rows = _row_dicts_to_sheet_rows(resolved_header, rows)
        worksheet.append_rows(
            sheet_rows,
            value_input_option="USER_ENTERED",
            table_range="A1",
        )

    _retry_sheets_api(_append, action=f"добавление строк в «{worksheet_name}»")


def _patch_cells_in_sheets(
    spreadsheet_id: str,
    worksheet_name: str,
    patches: list[tuple[int, str, object]],
    *,
    columns: list[str] | None = None,
) -> None:
    """Обновляет ячейки: (индекс строки в DataFrame, имя столбца, значение)."""
    if not patches:
        return

    from gspread.utils import rowcol_to_a1

    def _patch() -> None:
        worksheet = _open_worksheet(spreadsheet_id, worksheet_name)
        header = [str(col).strip() for col in columns] if columns else None
        if header is None:
            values = worksheet.get_all_values()
            if not values:
                raise RuntimeError(
                    f"Лист «{worksheet_name}» пуст — нельзя обновить ячейки."
                )
            header = [str(col).strip() for col in values[0]]
        col_index = {name: idx + 1 for idx, name in enumerate(header)}
        batch_data: list[dict[str, object]] = []
        for df_index, column_name, value in patches:
            col_num = col_index.get(column_name)
            if col_num is None:
                raise RuntimeError(
                    f"Столбец «{column_name}» не найден на листе «{worksheet_name}»."
                )
            sheet_row = int(df_index) + 2
            cell_range = rowcol_to_a1(sheet_row, col_num)
            batch_data.append({"range": cell_range, "values": [[value]]})
        worksheet.batch_update(batch_data, value_input_option="USER_ENTERED")

    _retry_sheets_api(_patch, action=f"обновление ячеек в «{worksheet_name}»")


def _save_to_sheets(
    spreadsheet_id: str,
    worksheet_name: str,
    df: pd.DataFrame,
    *,
    expected_row_count: int | None = None,
) -> None:
    def _save() -> None:
        worksheet = _open_worksheet(spreadsheet_id, worksheet_name)
        current_values = worksheet.get_all_values()
        current_row_count = len(current_values)
        if (
            expected_row_count is not None
            and current_row_count != expected_row_count
        ):
            raise ReferenceConcurrentModificationError(
                f"Лист «{worksheet_name}» изменился другим пользователем "
                f"(было {expected_row_count} строк, сейчас {current_row_count}). "
                "Повторите операцию."
            )

        if df.empty and list(df.columns):
            values: list[list[object]] = [list(df.columns)]
        elif df.empty:
            values = []
        else:
            payload = df.copy().where(pd.notnull(df), "")
            values = [payload.columns.tolist()] + payload.values.tolist()

        if not values:
            return

        nrows = len(values)
        ncols = max(len(row) for row in values)
        normalized = [row + [""] * (ncols - len(row)) for row in values]
        worksheet.resize(rows=nrows, cols=ncols)
        worksheet.update(
            normalized,
            range_name="A1",
            value_input_option="USER_ENTERED",
        )

    _retry_sheets_api(_save, action=f"сохранение листа «{worksheet_name}»")


def _local_path(key: str) -> Path:
    return REF_DIR / _REFERENCE_META[key]["local"]


def _load_local_reference(key: str) -> pd.DataFrame:
    local_path = _local_path(key)
    if not local_path.exists():
        raise FileNotFoundError(f"Файл не найден: {local_path}")
    return pd.read_excel(local_path)


def _save_local_reference(key: str, df: pd.DataFrame) -> None:
    local_path = _local_path(key)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(local_path, index=False)


def _append_rows_local(key: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    df = _load_local_reference(key)
    header = list(df.columns) if not df.empty else list(rows[0].keys())
    new_df = pd.DataFrame(rows, columns=header)
    updated = pd.concat([df, new_df], ignore_index=True)
    _save_local_reference(key, updated)


def _patch_cells_local(key: str, patches: list[tuple[int, str, object]]) -> None:
    if not patches:
        return
    df = _load_local_reference(key)
    for df_index, column_name, value in patches:
        df.loc[df_index, column_name] = value
    _save_local_reference(key, df)


def _load_reference_data(key: str, *, fresh: bool = False) -> pd.DataFrame:
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")

    if sheets_configured():
        spreadsheet_id = _spreadsheet_id()
        sheet = _sheet_name(key)
        if fresh:
            return _load_from_sheets_fresh(spreadsheet_id, sheet).copy()
        return _load_from_sheets_cached(spreadsheet_id, sheet).copy()

    return _load_local_reference(key)


def _store_session_reference(key: str, df: pd.DataFrame) -> None:
    _session_ref_cache()[key] = df.copy()


def _append_rows_to_session_cache(key: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    cache = _session_ref_cache()
    if key not in cache:
        return
    current = cache[key]
    header = list(current.columns)
    new_df = pd.DataFrame(
        [{col: row.get(col, "") for col in header} for row in rows]
    )
    cache[key] = pd.concat([current, new_df], ignore_index=True)


def _patch_session_cache(key: str, patches: list[tuple[int, str, object]]) -> None:
    if not patches or key not in _session_ref_cache():
        return
    df = _session_ref_cache()[key]
    for df_index, column_name, value in patches:
        df.loc[df_index, column_name] = value


def preload_references(
    keys: list[str] | tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """Загружает справочники в session_state. Повторные вызовы не ходят в API."""
    keys_to_load = list(keys or DEFAULT_PRELOAD_KEYS)
    cache = _session_ref_cache()
    for key in keys_to_load:
        if key not in cache:
            cache[key] = _load_reference_data(key, fresh=False)
    return {key: cache[key].copy() for key in keys_to_load if key in cache}


def load_category_order_reference() -> pd.DataFrame:
    """Загружает лист category_order; при отсутствии — пустой DataFrame."""
    if not reference_exists(REF_CATEGORY_ORDER):
        return pd.DataFrame()
    try:
        return load_reference(REF_CATEGORY_ORDER)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def load_reference(key: str, *, fresh: bool = False) -> pd.DataFrame:
    """Загружает справочник. fresh=True — из API; иначе session_state → кэш."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")

    if not fresh:
        cached = _session_ref_cache().get(key)
        if cached is not None:
            return cached.copy()

    df = _load_reference_data(key, fresh=fresh)
    _store_session_reference(key, df)
    return df.copy()


def load_reference_fresh(key: str) -> pd.DataFrame:
    """Свежая копия справочника из API — только для операций записи."""
    df = _load_reference_data(key, fresh=True)
    _store_session_reference(key, df)
    clear_reference_cache(key)
    return df.copy()


def append_reference_rows(key: str, rows: list[dict[str, object]]) -> None:
    """Добавляет строки в конец справочника, не затрагивая существующие данные."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")
    if not rows:
        return

    header: list[str] | None = None
    cached = _session_ref_cache().get(key)
    if cached is not None and not cached.empty:
        header = [str(col) for col in cached.columns]

    if sheets_configured():
        _append_rows_to_sheets(
            _spreadsheet_id(),
            _sheet_name(key),
            rows,
            header=header,
        )
    else:
        _append_rows_local(key, rows)

    _append_rows_to_session_cache(key, rows)
    clear_reference_cache(key)


def patch_reference_cells(
    key: str, patches: list[tuple[int, str, object]]
) -> None:
    """Точечно обновляет ячейки по индексу строки DataFrame."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")
    if not patches:
        return

    columns: list[str] | None = None
    cached = _session_ref_cache().get(key)
    if cached is not None and not cached.empty:
        columns = [str(col) for col in cached.columns]

    if sheets_configured():
        _patch_cells_in_sheets(
            _spreadsheet_id(),
            _sheet_name(key),
            patches,
            columns=columns,
        )
    else:
        _patch_cells_local(key, patches)

    _patch_session_cache(key, patches)
    clear_reference_cache(key)


def save_reference(
    key: str,
    df: pd.DataFrame,
    *,
    expected_row_count: int | None = None,
) -> None:
    """Полная синхронизация справочника (использовать только при необходимости)."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")

    if sheets_configured():
        if expected_row_count is None:
            expected_row_count = _worksheet_row_count(
                _spreadsheet_id(), _sheet_name(key)
            )
        _save_to_sheets(
            _spreadsheet_id(),
            _sheet_name(key),
            df,
            expected_row_count=expected_row_count,
        )
    else:
        _save_local_reference(key, df)
    _store_session_reference(key, df)
    clear_reference_cache(key)


def clear_reference_cache(key: str | None = None) -> None:
    """Сбрасывает глобальный кэш чтения: для одного справочника или для всех."""
    if key is None:
        _load_from_sheets_cached.clear()
        return
    if sheets_configured():
        _load_from_sheets_cached.clear(_spreadsheet_id(), _sheet_name(key))
