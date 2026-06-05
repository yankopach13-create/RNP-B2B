import base64
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

# --- подготовка путей -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
REF_DIR = PROJECT_ROOT / "data" / "reference"
INSTRUCTIONS_DIR = PROJECT_ROOT / "assets" / "instructions"
CONTRACTORS_PATH = REF_DIR / "contractors.xlsx"
CATEGORIES_PATH = REF_DIR / "categories.xlsx"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

# --- собственные модули ----------------------------------------------------------------------------
from features.dashboard import (  # noqa: E402
    CLIENT_BLOCK_WEEK_INPUT_KEY,
    render_special_retail_dashboard,
)


# --------------------------------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------------------------------
def _read_excel(uploaded_file, description: str) -> pd.DataFrame | None:
    if uploaded_file is None:
        return None
    try:
        return pd.read_excel(uploaded_file)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не получилось прочитать «{description}»: {exc}")
        return None


def _render_uploader_help(image_name: str, caption: str = "") -> None:
    with st.popover("Инфо"):
        if caption:
            st.caption(caption)
        image_path = INSTRUCTIONS_DIR / image_name
        if image_path.exists():
            st.image(str(image_path), use_container_width=True)
        else:
            st.warning(f"Скриншот не найден: {image_name}")


def _build_instruction_image_html(image_name: str) -> str:
    image_path = INSTRUCTIONS_DIR / image_name
    if not image_path.exists():
        return (
            "<div class='help-popover__warning'>"
            f"Скриншот не найден: {image_name}"
            "</div>"
        )

    suffix = image_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"

    return (
        "<div class='help-popover__image-wrapper'>"
        f"<img src='{data_url}' alt='{image_name}' class='help-popover__image' />"
        f"<a href='{data_url}' download='{image_path.name}' class='help-popover__download'>"
        "Скачать изображение"
        "</a>"
        "</div>"
    )


def _split_caption_paragraphs(caption: str) -> list[str]:
    if not caption:
        return []
    return [part.strip() for part in caption.split("<br><br>") if part.strip()]


def _render_custom_help_popover(
    popover_key: str,
    caption: str,
    image_name: str,
    second_image_name: str | None = None,
    second_caption: str = "",
    trigger_label: str = "ℹ️",
    align: str = "right",
    two_column_layout: bool = False,
    compact_images: bool = False,
) -> None:
    parts: list[str] = []
    if two_column_layout and second_image_name:
        left_paragraphs = _split_caption_paragraphs(caption)
        right_paragraphs = _split_caption_paragraphs(second_caption)
        rows_count = max(len(left_paragraphs), len(right_paragraphs))
        text_rows: list[str] = []
        for idx in range(rows_count):
            left_part = left_paragraphs[idx] if idx < len(left_paragraphs) else ""
            right_part = right_paragraphs[idx] if idx < len(right_paragraphs) else ""
            text_rows.append(
                (
                    "<div class='help-popover__row'>"
                    f"<div class='help-popover__paragraph'>{left_part}</div>"
                    f"<div class='help-popover__paragraph'>{right_part}</div>"
                    "</div>"
                )
            )

        parts.append(
            (
                "<div class='help-popover__split help-popover__split-text'>"
                f"{''.join(text_rows)}"
                "</div>"
                "<div class='help-popover__split help-popover__split-images'>"
                f"<div class='help-popover__split-col'>{_build_instruction_image_html(image_name)}</div>"
                f"<div class='help-popover__split-col'>{_build_instruction_image_html(second_image_name)}</div>"
                "</div>"
            )
        )
    else:
        if caption:
            parts.append(f"<div class='help-popover__caption'>{caption}</div>")
        parts.append(_build_instruction_image_html(image_name))

        if second_image_name:
            if second_caption:
                parts.append(f"<div class='help-popover__caption'>{second_caption}</div>")
            parts.append(_build_instruction_image_html(second_image_name))

    compact_class = " help-popover--compact" if compact_images else ""

    st.markdown(
        (
            f"<div class='help-popover help-popover--{align}{compact_class}' id='help-popover-{popover_key}'>"
            f"<input type='checkbox' id='help-toggle-{popover_key}' class='help-popover__toggle' />"
            f"<label for='help-toggle-{popover_key}' class='help-popover__trigger'>{trigger_label}</label>"
            f"<label for='help-toggle-{popover_key}' class='help-popover__backdrop' aria-hidden='true'></label>"
            f"<div class='help-popover__panel'>{''.join(parts)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_section_header_with_help(
    title: str,
    image_name: str,
    caption: str,
    second_image_name: str | None = None,
    second_caption: str = "",
    align: str = "right",
    two_column_layout: bool = False,
    compact_images: bool = False,
) -> None:
    title_col, help_col = st.columns([0.82, 0.18], gap="small")
    with title_col:
        st.subheader(title)
    with help_col:
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        _render_custom_help_popover(
            popover_key=title.lower().replace(" ", "-"),
            caption=caption,
            image_name=image_name,
            second_image_name=second_image_name,
            second_caption=second_caption,
            align=align,
            two_column_layout=two_column_layout,
            compact_images=compact_images,
        )


# --------------------------------------------------------------------------------------------------
# Streamlit-приложение
# --------------------------------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="B2B РНП", layout="wide")
    st.title("B2B")
    if "data_loaded" not in st.session_state:
        st.session_state.data_loaded = False

    col_sales, col_turnover, col_finance = st.columns(3)

    # Столбец 2: Продажи
    with col_sales:
        _render_section_header_with_help(
            title="Продажи",
            image_name="sales.png",
            caption=(
                "Зайдите к Qlik под профилем User2.<br>"
                'В анализе продаж перейдите в закладку "АВТОМАТИЗАЦИЯ РНП B2B (Спец.розница/Традиция)".<br><br><br>'
                "Отберите необходимую неделю и скачайте отчёт без форматирования (не нажимайте галочку при скачивании).<br>"
                'Вставьте скачанный документ в контейнер "Продажи".'
            ),
            align="left",
        )
        sales_file = st.file_uploader(
            "Продажи",
            type=["xlsx", "xls"],
            key="sales_uploader",
        )

    # Столбец 3: Оборачиваемость
    with col_turnover:
        _render_section_header_with_help(
            title="Оборачиваемость",
            image_name="turnover.png",
            caption=(
                "Зайдите к Qlik под профилем User2.<br>"
                'В анализе запасов перейдите в закладку "АВТОМАТИЗАЦИЯ РНП B2B ( ОБОРАЧИВАЕМОСТЬ)".<br><br><br>'
                "Отберите необходимые периоды для расчёта оборачиваемости и скачайте отчёты.<br>"
                'Вставьте скачанные документы в контейнеры "Оборачиваемость 90 дней" и "Оборачиваемость 7 дней".'
            ),
            align="center",
        )
        turnover_90_file = st.file_uploader(
            "Оборачиваемость (90 дней)",
            type=["xlsx", "xls"],
            key="turnover_90_uploader",
        )

        turnover_7_file = st.file_uploader(
            "Оборачиваемость (7 дней)",
            type=["xlsx", "xls"],
            key="turnover_7_uploader",
        )

    # Столбец 4: Финансовые загрузки
    with col_finance:
        _render_section_header_with_help(
            title="ДЗ и ДС",
            image_name="receivables_62.png",
            caption=(
                "Зайдите в 1с Human и сформируйте ОСВ 62 счёта на конец периода.<br><br>"
                'В детализации отожмите галочку "По субсчетам", в поле оставьте только "Контрагенты".<br><br>'
                "Сформированный отчёт необходимо сохранить в формате XLSX!"
            ),
            second_image_name="cash_inflow_51_62.png",
            second_caption=(
                "Зайдите в 1с Human - отчёт по проводкам.<br><br>"
                "Отберите необходимый период. В настройках укажите 51 счёт в дебете и 62 счет в кредите.<br><br>"
                "Сформированный отчёт необходимо сохранить в формате XLSX!"
            ),
            align="right",
            two_column_layout=True,
            compact_images=True,
        )
        receivables_file = st.file_uploader(
            "Дебиторская задолженность (62 счёт)",
            type=["xlsx", "xls"],
            key="receivables_62_uploader",
        )
        cash_inflow_file = st.file_uploader(
            "Поступление ДС (51,62 счета)",
            type=["xlsx", "xls"],
            key="cash_inflow_51_62_uploader",
        )

    st.markdown(
        """
        <style>
        .help-popover {
            position: relative;
            display: inline-block;
            width: 100%;
            text-align: right;
            z-index: 10;
        }
        .help-popover__toggle {
            position: absolute;
            opacity: 0;
            pointer-events: none;
        }
        .help-popover__trigger {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 0.5rem;
            color: rgba(250, 250, 250, 0.95);
            cursor: pointer;
            user-select: none;
            font-size: 1.05rem;
            line-height: 1;
            background: rgba(255, 255, 255, 0.04);
            transition: background-color 0.15s ease, border-color 0.15s ease;
            position: relative;
            z-index: 1000;
        }
        .help-popover__trigger:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(255, 255, 255, 0.55);
        }
        .help-popover__backdrop {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 998;
            background: transparent;
        }
        .help-popover__panel {
            display: none;
            position: absolute;
            top: calc(100% + 0.5rem);
            width: min(68vw, 760px);
            min-width: min(92vw, 360px);
            max-width: 92vw;
            max-height: 72vh;
            overflow: auto;
            padding: 0.9rem;
            border-radius: 0.75rem;
            border: 1px solid rgba(250, 250, 250, 0.18);
            background: rgba(15, 15, 15, 0.98);
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.45);
            text-align: left;
            z-index: 999;
        }
        .help-popover--left .help-popover__panel {
            left: 0;
            right: auto;
        }
        .help-popover--center .help-popover__panel {
            left: 50%;
            right: auto;
            transform: translateX(-50%);
        }
        .help-popover--right .help-popover__panel {
            right: 0;
            left: auto;
        }
        .help-popover__toggle:checked ~ .help-popover__backdrop {
            display: block;
        }
        .help-popover__toggle:checked ~ .help-popover__panel {
            display: block;
        }
        .help-popover__caption {
            white-space: pre-line;
            font-size: 0.95rem;
            color: rgba(250, 250, 250, 0.86);
            margin-bottom: 0.75rem;
        }
        .help-popover__image-wrapper {
            margin-bottom: 1rem;
        }
        .help-popover__image {
            width: 100%;
            height: auto;
            border-radius: 0.5rem;
            border: 1px solid rgba(250, 250, 250, 0.16);
        }
        .help-popover--compact .help-popover__image {
            max-height: 280px;
            object-fit: contain;
            background: rgba(0, 0, 0, 0.15);
        }
        .help-popover__split {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.3rem;
        }
        .help-popover__split-text {
            display: block;
        }
        .help-popover__row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.3rem;
            margin-bottom: 0.75rem;
        }
        .help-popover__paragraph {
            white-space: pre-line;
            font-size: 0.95rem;
            color: rgba(250, 250, 250, 0.86);
            min-height: 1.45rem;
        }
        .help-popover__split-col {
            min-width: 0;
        }
        .help-popover__split-images .help-popover__split-col {
            display: flex;
            align-items: flex-start;
        }
        .help-popover__split-images .help-popover__image-wrapper {
            width: 100%;
        }
        @media (max-width: 1100px) {
            .help-popover__split {
                grid-template-columns: 1fr;
            }
        }
        .help-popover__download {
            display: inline-block;
            margin-top: 0.55rem;
            color: #d95f5f;
            text-decoration: none;
            font-weight: 600;
        }
        .help-popover__download:hover {
            text-decoration: underline;
        }
        .help-popover__warning {
            color: #ff8f8f;
            font-size: 0.92rem;
            margin-bottom: 0.85rem;
        }
        .st-key-load_data_btn button {
            background-color: #b23a3a !important;
            border: 1px solid #b23a3a !important;
            color: #ffffff !important;
            font-weight: 700 !important;
        }
        .st-key-load_data_btn button:hover {
            background-color: #9a3131 !important;
            border-color: #9a3131 !important;
        }
        .st-key-load_data_btn button:active,
        .st-key-load_data_btn button:focus,
        .st-key-load_data_btn button:focus-visible {
            background-color: #9a3131 !important;
            border-color: #9a3131 !important;
            color: #ffffff !important;
            box-shadow: none !important;
            outline: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("")
    if st.button("Загрузить данные", type="primary", key="load_data_btn"):
        st.session_state.data_loaded = True
        st.session_state.pop(CLIENT_BLOCK_WEEK_INPUT_KEY, None)

    if not st.session_state.data_loaded:
        return

    # Загружаем все файлы (необязательные)
    contractors_df = _read_excel(CONTRACTORS_PATH, "Справочник контрагентов")
    categories_df = _read_excel(CATEGORIES_PATH, "Категории товаров")
    sales_df = _read_excel(sales_file, "Продажи")
    orders_df = None
    turnover_90_df = _read_excel(turnover_90_file, "Оборачиваемость 90 дней")
    turnover_7_df = _read_excel(turnover_7_file, "Оборачиваемость 7 дней")
    receivables_df = _read_excel(receivables_file, "Дебиторская задолженность (62 счёт)")
    cash_inflow_df = _read_excel(cash_inflow_file, "Поступление ДС (51,62 счета)")

    # Если есть ошибки чтения файлов, останавливаемся
    if any(
        df is None and uploaded_file is not None
        for df, uploaded_file in (
            (sales_df, sales_file),
            (turnover_90_df, turnover_90_file),
            (turnover_7_df, turnover_7_file),
            (receivables_df, receivables_file),
            (cash_inflow_df, cash_inflow_file),
        )
    ):
        return

    # Проверяем базовые файлы для построения основного отчёта
    if sales_df is None:
        st.warning("⚠️ Без файла «Продажи» основной отчёт недоступен.")
        return

    if contractors_df is None:
        st.error(
            f"⚠️ Не удалось прочитать справочник контрагентов: {CONTRACTORS_PATH}"
        )
        return

    if categories_df is None:
        st.error(
            f"⚠️ Не удалось прочитать справочник категорий: {CATEGORIES_PATH}"
        )
        return

    # Store categories_df in session state for factor analysis (если загружен)
    if categories_df is not None:
        st.session_state.categories_df = categories_df

    st.markdown("---")
    render_special_retail_dashboard(
        sales_df=sales_df,
        contractors_df=contractors_df,
        categories_df=categories_df,
        orders_df=orders_df,
        turnover_90_df=turnover_90_df,
        turnover_7_df=turnover_7_df,
        receivables_df=receivables_df,
        cash_inflow_df=cash_inflow_df,
    )


if __name__ == "__main__":
    main()