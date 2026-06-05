import pandas as pd
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def _resolve_path(filepath: str | Path) -> Path:
    path = Path(filepath)
    if not path.is_absolute():
        path = DATA_DIR / path
    return path


def load_contractors(filepath: str | Path = "Контрагент-подразделение.xlsx") -> pd.DataFrame:
    path = _resolve_path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл со справочником контрагентов: {path}")
    return pd.read_excel(path)


def load_sales(filepath: str | Path = "продажи.xlsx") -> pd.DataFrame:
    path = _resolve_path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл с продажами: {path}")
    return pd.read_excel(path)


def load_categories(filepath: str | Path = "категории товаров.xlsx") -> pd.DataFrame:
    path = _resolve_path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл со справочником категорий: {path}")
    return pd.read_excel(path)


def load_orders(filepath: str | Path = "заказы.xlsx") -> pd.DataFrame:
    path = _resolve_path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл с заказами: {path}")
    return pd.read_excel(path)


def load_turnover(filepath: str | Path) -> pd.DataFrame:
    """
    Универсальная загрузка оборачиваемости.
    Если файл не найден — возвращает пустой DataFrame (без исключения),
    чтобы приложение продолжало работать.
    """
    path = _resolve_path(filepath)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_excel(path)