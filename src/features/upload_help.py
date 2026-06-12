# src/features/upload_help.py
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTRUCTIONS_DIR = PROJECT_ROOT / "assets" / "instructions"


def _resolve_instruction_image_path(image_name: str) -> Path:
    image_path = INSTRUCTIONS_DIR / image_name
    if image_path.exists():
        return image_path

    stem = Path(image_name).stem
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        candidate = INSTRUCTIONS_DIR / f"{stem}{suffix}"
        if candidate.exists():
            return candidate

    return image_path


def _build_instruction_image_html(image_name: str) -> str:
    image_path = _resolve_instruction_image_path(image_name)
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


def _build_help_popover_html(
    popover_key: str,
    caption: str,
    image_name: str | None = None,
    second_image_name: str | None = None,
    second_caption: str = "",
    trigger_label: str = "ℹ️",
    align: str = "right",
    two_column_layout: bool = False,
    compact_images: bool = False,
    inline: bool = False,
) -> str:
    parts: list[str] = []
    if two_column_layout and second_image_name and image_name:
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
        if image_name:
            parts.append(_build_instruction_image_html(image_name))

        if second_image_name:
            if second_caption:
                parts.append(f"<div class='help-popover__caption'>{second_caption}</div>")
            parts.append(_build_instruction_image_html(second_image_name))

    compact_class = " help-popover--compact" if compact_images else ""
    inline_class = " help-popover--inline" if inline else ""

    return (
        f"<div class='help-popover help-popover--{align}{compact_class}{inline_class}' "
        f"id='help-popover-{popover_key}'>"
        f"<input type='checkbox' id='help-toggle-{popover_key}' class='help-popover__toggle' />"
        f"<label for='help-toggle-{popover_key}' class='help-popover__trigger'>{trigger_label}</label>"
        f"<label for='help-toggle-{popover_key}' class='help-popover__backdrop' aria-hidden='true'></label>"
        f"<div class='help-popover__panel'>{''.join(parts)}</div>"
        "</div>"
    )


def render_custom_help_popover(
    popover_key: str,
    caption: str,
    image_name: str | None = None,
    second_image_name: str | None = None,
    second_caption: str = "",
    trigger_label: str = "ℹ️",
    align: str = "right",
    two_column_layout: bool = False,
    compact_images: bool = False,
) -> None:
    st.markdown(
        _build_help_popover_html(
            popover_key=popover_key,
            caption=caption,
            image_name=image_name,
            second_image_name=second_image_name,
            second_caption=second_caption,
            trigger_label=trigger_label,
            align=align,
            two_column_layout=two_column_layout,
            compact_images=compact_images,
        ),
        unsafe_allow_html=True,
    )


def render_section_header_with_help(
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
        render_custom_help_popover(
            popover_key=title.lower().replace(" ", "-"),
            caption=caption,
            image_name=image_name,
            second_image_name=second_image_name,
            second_caption=second_caption,
            align=align,
            two_column_layout=two_column_layout,
            compact_images=compact_images,
        )


def render_block_title_with_help(
    title: str,
    popover_key: str,
    caption: str,
    image_name: str | None = None,
    align: str = "left",
    title_color: str = "#ffffff",
) -> None:
    popover_html = _build_help_popover_html(
        popover_key=popover_key,
        caption=caption,
        image_name=image_name,
        align=align,
        inline=True,
    )
    st.markdown(
        (
            "<div style='display:flex; align-items:center; gap:0.4rem; "
            "flex-wrap:wrap; margin-bottom:0.2rem;'>"
            f"<h2 style='color:{title_color}; margin:0;'>{title}</h2>"
            f"{popover_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_compact_uploader_header_with_help(
    title: str,
    popover_key: str,
    caption: str,
    image_name: str | None = None,
    align: str = "right",
) -> None:
    title_col, help_col = st.columns([0.82, 0.18], gap="small")
    with title_col:
        st.markdown(f"**{title}**")
    with help_col:
        st.markdown("<div style='height:2px;'></div>", unsafe_allow_html=True)
        render_custom_help_popover(
            popover_key=popover_key,
            caption=caption,
            image_name=image_name,
            align=align,
        )
