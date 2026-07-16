"""Reusable image renderer for Aestron's interactive social and fun commands."""

from __future__ import annotations

import re
import textwrap
from io import BytesIO

import discord
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1000
HEIGHT = 620
BACKGROUND = (11, 15, 21)
PANEL = (25, 32, 42)
PANEL_ALT = (31, 40, 52)
TEXT = (241, 243, 247)
MUTED = (155, 166, 181)
ACCENT = (255, 70, 85)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _plain(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"<@!?\d+>", "member", text)
    text = re.sub(r"[`*_~#]", "", text)
    return " ".join(text.split())


def _lines(value: object, width: int, maximum: int) -> list[str]:
    text = _plain(value)
    wrapped = textwrap.wrap(text, width=width) or [""]
    if len(wrapped) > maximum:
        wrapped = wrapped[:maximum]
        wrapped[-1] = f"{wrapped[-1][:-1]}…"
    return wrapped


def _panel(draw: ImageDraw.ImageDraw, box, *, alt: bool = False) -> None:
    draw.rounded_rectangle(
        box,
        radius=16,
        fill=PANEL_ALT if alt else PANEL,
        outline=(48, 59, 73),
        width=2,
    )


def render_fun_dashboard(embed: discord.Embed) -> bytes:
    """Render an embed's structured content as a polished Discord dashboard."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 9, HEIGHT), fill=ACCENT)
    draw.text((38, 30), "AESTRON // PLAY", font=_font(12, bold=True), fill=ACCENT)
    draw.text(
        (38, 59),
        _plain(embed.title or "Interactive command")[:48],
        font=_font(31, bold=True),
        fill=TEXT,
    )
    draw.line((38, 105, 962, 105), fill=(48, 59, 73), width=2)

    description = _lines(embed.description, 92, 5)
    description_height = max(76, len(description) * 27 + 26)
    _panel(draw, (38, 128, 962, 128 + description_height))
    for index, line in enumerate(description):
        draw.text(
            (62, 150 + index * 27),
            line,
            font=_font(17, bold=index == 0),
            fill=TEXT if index == 0 else (214, 221, 229),
        )

    fields = list(embed.fields)[:6]
    field_top = 128 + description_height + 22
    remaining_height = 560 - field_top
    columns = 3 if len(fields) >= 3 else max(1, len(fields))
    rows = max(1, (len(fields) + columns - 1) // columns)
    gap = 14
    cell_width = int((924 - gap * (columns - 1)) / columns)
    cell_height = min(190, max(112, int((remaining_height - gap * (rows - 1)) / rows)))
    for index, field in enumerate(fields):
        row, column = divmod(index, columns)
        x = 38 + column * (cell_width + gap)
        y = field_top + row * (cell_height + gap)
        _panel(draw, (x, y, x + cell_width, y + cell_height), alt=index % 2 == 1)
        draw.text(
            (x + 18, y + 15),
            _plain(field.name)[:32].upper(),
            font=_font(10, bold=True),
            fill=MUTED,
        )
        for line_index, line in enumerate(_lines(field.value, 31, 4)):
            draw.text(
                (x + 18, y + 52 + line_index * 30),
                line,
                font=_font(23 if line_index == 0 else 14, bold=line_index == 0),
                fill=TEXT if line_index == 0 else MUTED,
            )

    footer = _plain(embed.footer.text if embed.footer else "")
    if footer:
        draw.text((38, 590), footer[:110], font=_font(10), fill=MUTED)
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
