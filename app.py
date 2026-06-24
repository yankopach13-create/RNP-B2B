from pathlib import Path
import sys

import pandas as pd
import streamlit as st

# --- подготовка путей -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
# src — в начало: иначе корневая папка data/reference/ перекрывает пакет src/data/
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# --- собственные модули ----------------------------------------------------------------------------
from data.references import (  # noqa: E402
    REF_CATEGORIES,
    REF_CONTRACTORS,
    clear_session_references,
    get_reference_label,
    preload_references,
    sheets_configured,
)
from features.dashboard import (  # noqa: E402
    CLIENT_BLOCK_WEEK_INPUT_KEY,
    render_special_retail_dashboard,
)
from features.upload_help import (  # noqa: E402
    INSTRUCTIONS_DIR,
    render_section_header_with_help,
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


# --------------------------------------------------------------------------------------------------
# Streamlit-приложение
# --------------------------------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="B2B РНП", page_icon="📊", layout="wide")
    st.title("B2B")
    st.markdown(
        '<a href="https://docs.google.com/spreadsheets/d/1mQiNJ_3XAimSraS3Wf5pWIFhkr8UWqJ7NlIoQvXoPkM/edit?hl=ru&gid=37260786#gid=37260786" '
        'target="_blank" rel="noopener noreferrer">База данных</a>',
        unsafe_allow_html=True,
    )
    if "data_loaded" not in st.session_state:
        st.session_state.data_loaded = False

    col_sales, col_turnover, col_finance = st.columns(3)

    # Столбец 2: Продажи
    with col_sales:
        render_section_header_with_help(
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
        render_section_header_with_help(
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
        render_section_header_with_help(
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
        .help-popover--inline {
            width: auto;
            text-align: left;
            flex-shrink: 0;
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
        clear_session_references()

    if not st.session_state.data_loaded:
        return

    # Загружаем справочники один раз в session_state (без лишних запросов к API)
    try:
        refs = preload_references()
        contractors_df = refs[REF_CONTRACTORS]
        categories_df = refs[REF_CATEGORIES]
    except Exception as exc:  # noqa: BLE001
        source = "Google Sheets" if sheets_configured() else "локальных файлов"
        st.error(f"Не удалось загрузить справочники из {source}: {exc}")
        return
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

    if contractors_df.empty or "Контрагент" not in contractors_df.columns:
        st.error(
            f"⚠️ Справочник контрагентов пуст или некорректен: {get_reference_label(REF_CONTRACTORS)}"
        )
        return

    if categories_df.empty or "Категория:" not in categories_df.columns:
        st.error(
            f"⚠️ Справочник категорий пуст или некорректен: {get_reference_label(REF_CATEGORIES)}"
        )
        return

    # Store reference dfs in session state for reuse across reruns
    st.session_state.contractors_df = contractors_df
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