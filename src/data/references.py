"""Справочники: Google Sheets (основной источник) с fallback на локальные xlsx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = PROJECT_ROOT / "data" / "reference"

REF_CONTRACTORS = "contractors"
REF_CATEGORIES = "categories"
REF_DZ_SPEC = "dz_spec"
REF_DZ_TRAD = "dz_trad"
REF_DZ_REMOVE = "dz_remove"
REF_SALES_POD_CARTRIDGE = "sales_pod_cartridge"

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


def get_reference_title(key: str) -> str:
    return _REFERENCE_META[key]["title"]


def get_reference_label(key: str) -> str:
    if sheets_configured():
        return f"лист «{_sheet_name(key)}»"
    return _REFERENCE_META[key]["local"]


def reference_exists(key: str) -> bool:
    if sheets_configured():
        try:
            load_reference(key)
            return True
        except Exception:  # noqa: BLE001
            return False
    return (REF_DIR / _REFERENCE_META[key]["local"]).exists()


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


@st.cache_resource
def _get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    info = dict(st.secrets["gcp_service_account"])
    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(credentials)
    _apply_ssl_verify(client)
    return client


@st.cache_data(ttl=120, show_spinner=False)
def _load_from_sheets(spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    client = _get_gspread_client()
    worksheet = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    records = worksheet.get_all_records()
    if records:
        return pd.DataFrame(records)
    rows = worksheet.get_all_values()
    if rows:
        return pd.DataFrame(columns=rows[0])
    return pd.DataFrame()


def _save_to_sheets(spreadsheet_id: str, worksheet_name: str, df: pd.DataFrame) -> None:
    client = _get_gspread_client()
    worksheet = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    worksheet.clear()
    if df.empty and list(df.columns):
        worksheet.update([list(df.columns)])
        return
    if df.empty:
        return
    payload = df.copy().where(pd.notnull(df), "")
    values = [payload.columns.tolist()] + payload.values.tolist()
    worksheet.update(values, value_input_option="USER_ENTERED")


def load_reference(key: str) -> pd.DataFrame:
    """Загружает справочник из Google Sheets или локального xlsx."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")

    if sheets_configured():
        refs = _references_config()
        spreadsheet_id = str(refs["spreadsheet_id"]).strip()
        return _load_from_sheets(spreadsheet_id, _sheet_name(key)).copy()

    local_path = REF_DIR / _REFERENCE_META[key]["local"]
    if not local_path.exists():
        raise FileNotFoundError(f"Файл не найден: {local_path}")
    return pd.read_excel(local_path)


def save_reference(key: str, df: pd.DataFrame) -> None:
    """Сохраняет справочник в Google Sheets или локальный xlsx."""
    if key not in _REFERENCE_META:
        raise ValueError(f"Неизвестный справочник: {key}")

    if sheets_configured():
        refs = _references_config()
        spreadsheet_id = str(refs["spreadsheet_id"]).strip()
        _save_to_sheets(spreadsheet_id, _sheet_name(key), df)
    else:
        local_path = REF_DIR / _REFERENCE_META[key]["local"]
        local_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(local_path, index=False)
    clear_reference_cache()


def clear_reference_cache() -> None:
    _load_from_sheets.clear()
