"""Standalone PLT layout primitives extracted from the validated Chengda layout.

Original module: chengda_management_callouts.py; SHA file readers and project data are excluded.
The retained definitions preserve the source implementation.
"""
from __future__ import annotations



MANAGEMENT_FONT_FAMILY = "SimHei, Microsoft YaHei, Arial, sans-serif"


MANAGEMENT_FONT_HEIGHT = 88.0


MANAGEMENT_TEXT_PADDING_X = 18.0


MANAGEMENT_TEXT_PADDING_Y = 12.0


SPOOL_FONT_HEIGHT = 64.0


SPOOL_INNER_FRAME_GAP = 14.0


def label_box(number: str, kind: str = "") -> tuple[float, float]:
    font_height = SPOOL_FONT_HEIGHT if kind == "spool" else MANAGEMENT_FONT_HEIGHT
    if kind == "spool":
        character_em = sum(
            0.34 if char in "-_." else 0.56 if char.isdigit() else 0.62
            for char in number
        )
        text_width = font_height * character_em
    else:
        text_width = font_height * 0.68 * len(number)
    width = max(font_height * 0.7, text_width)
    width += 2 * MANAGEMENT_TEXT_PADDING_X
    height = font_height + 2 * MANAGEMENT_TEXT_PADDING_Y
    if kind == "spool":
        width += 2 * SPOOL_INNER_FRAME_GAP
        height += 2 * SPOOL_INNER_FRAME_GAP
    return width, height
