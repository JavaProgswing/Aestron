"""Generated Minecraft-style battle visuals and shared equipment metadata."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ARMOR_RESISTANCE = {
    "Netherite": 70.0,
    "Diamond": 60.0,
    "Iron": 48.0,
    "Chainmail": 38.0,
    "Golden": 32.0,
    "Leather": 22.0,
}
SWORD_DAMAGE = {
    "Netherite": 12.0,
    "Diamond": 10.0,
    "Iron": 9.0,
    "Stone": 8.0,
    "Golden": 8.5,
    "Wooden": 5.0,
}
ASSET_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "resources" / "minecraft" / "items"
)
_ARMOR_FILES = {
    material: f"{material.casefold()}_chestplate.png" for material in ARMOR_RESISTANCE
}
_SWORD_FILES = {
    material: f"{material.casefold()}_sword.png" for material in SWORD_DAMAGE
}


@dataclass(frozen=True, slots=True)
class FighterVisual:
    """State required to draw one side of a PvP board."""

    name: str
    avatar: bytes
    health: float
    total_health: float
    armor: str
    sword: str
    shield_active: bool = False
    heal_available: bool = True


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _bounded_text(draw: ImageDraw.ImageDraw, text: str, width: int, font) -> str:
    value = " ".join(text.split()) or "Player"
    while value and draw.textbbox((0, 0), value, font=font)[2] > width:
        value = value[:-1]
    return f"{value.rstrip()}…" if value != text and value else value


def _avatar_image(data: bytes, name: str) -> Image.Image:
    try:
        source = Image.open(BytesIO(data)).convert("RGB")
        avatar = ImageOps.fit(source, (126, 126), method=Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        avatar = Image.new("RGB", (126, 126), (49, 68, 52))
        fallback = ImageDraw.Draw(avatar)
        initial = (name.strip()[:1] or "?").upper()
        fallback.text(
            (63, 63),
            initial,
            font=_font(58, bold=True),
            fill=(238, 244, 232),
            anchor="mm",
        )
    return avatar.resize((84, 84), Image.Resampling.NEAREST)


@lru_cache(maxsize=16)
def _item_sprite(filename: str, size: int = 76) -> Image.Image:
    """Load a bundled in-game item sprite without any runtime web request."""
    with Image.open(ASSET_DIRECTORY / filename) as source:
        sprite = source.convert("RGBA")
    return sprite.resize((size, size), Image.Resampling.NEAREST)


def _paste_item(
    canvas: Image.Image, origin: tuple[int, int], filename: str, *, size: int = 76
) -> None:
    sprite = _item_sprite(filename, size)
    canvas.paste(sprite, origin, sprite)


def _draw_fighter(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    fighter: FighterVisual,
    box: tuple[int, int, int, int],
    *,
    active: bool,
    side: str,
) -> None:
    x1, y1, x2, y2 = box
    accent = (91, 202, 91) if active else (69, 78, 71)
    draw.rounded_rectangle(box, radius=20, fill=(25, 31, 27), outline=accent, width=3)
    if active:
        strip = (x1, y1, x2, y1 + 8)
        draw.rounded_rectangle(strip, radius=6, fill=(91, 202, 91))
        turn_text = "YOUR MOVE"
        turn_x = x1 + 24 if side == "left" else x2 - 24
        draw.text(
            (turn_x, y1 + 24),
            turn_text,
            font=_font(13, bold=True),
            fill=(128, 237, 125),
            anchor="la" if side == "left" else "ra",
        )

    avatar = _avatar_image(fighter.avatar, fighter.name)
    avatar_x = x1 + 26 if side == "left" else x2 - 110
    canvas.paste(avatar, (avatar_x, y1 + 48))
    draw.rectangle(
        (avatar_x - 3, y1 + 45, avatar_x + 87, y1 + 135),
        outline=accent,
        width=3,
    )

    name_font = _font(25, bold=True)
    name = _bounded_text(draw, fighter.name, 220, name_font)
    text_x = avatar_x + 106 if side == "left" else avatar_x - 18
    anchor = "la" if side == "left" else "ra"
    draw.text(
        (text_x, y1 + 59),
        name,
        font=name_font,
        fill=(240, 244, 237),
        anchor=anchor,
    )
    health = max(0.0, min(fighter.health, fighter.total_health))
    ratio = health / max(1.0, fighter.total_health)
    bar_x1 = text_x if side == "left" else text_x - 218
    bar_x2 = bar_x1 + 218
    draw.rounded_rectangle(
        (bar_x1, y1 + 94, bar_x2, y1 + 112), radius=7, fill=(52, 57, 52)
    )
    fill_color = (82, 196, 85) if ratio > 0.45 else (235, 164, 52)
    if ratio <= 0.2:
        fill_color = (224, 76, 66)
    fill_width = max(0, int(218 * ratio))
    if fill_width:
        draw.rounded_rectangle(
            (bar_x1, y1 + 94, bar_x1 + fill_width, y1 + 112),
            radius=7,
            fill=fill_color,
        )
    draw.text(
        (bar_x1, y1 + 121),
        f"{health:.1f} / {fighter.total_health:.1f} HP",
        font=_font(13, bold=True),
        fill=(174, 185, 176),
    )

    equipment_y = y1 + 166
    armor_x = x1 + 40
    sword_x = x1 + 230
    _paste_item(canvas, (armor_x, equipment_y), _ARMOR_FILES[fighter.armor])
    _paste_item(canvas, (sword_x, equipment_y), _SWORD_FILES[fighter.sword])
    draw.text(
        (armor_x + 38, equipment_y + 82),
        f"{fighter.armor} armor",
        font=_font(15, bold=True),
        fill=(226, 230, 224),
        anchor="ma",
    )
    draw.text(
        (armor_x + 38, equipment_y + 104),
        f"{ARMOR_RESISTANCE.get(fighter.armor, 0):g}% resist",
        font=_font(12),
        fill=(142, 153, 144),
        anchor="ma",
    )
    draw.text(
        (sword_x + 38, equipment_y + 82),
        f"{fighter.sword} sword",
        font=_font(15, bold=True),
        fill=(226, 230, 224),
        anchor="ma",
    )
    draw.text(
        (sword_x + 38, equipment_y + 104),
        f"{SWORD_DAMAGE.get(fighter.sword, 0):g} attack",
        font=_font(12),
        fill=(142, 153, 144),
        anchor="ma",
    )

    chips = []
    if fighter.shield_active:
        chips.append(("SHIELD UP", (71, 137, 211)))
    chip_x = x1 + 28
    for label, color in chips:
        width = draw.textbbox((0, 0), label, font=_font(11, bold=True))[2] + 24
        draw.rounded_rectangle(
            (chip_x, y2 - 45, chip_x + width, y2 - 19),
            radius=8,
            fill=color,
        )
        draw.text(
            (chip_x + 12, y2 - 32),
            label,
            font=_font(11, bold=True),
            fill=(255, 255, 255),
            anchor="lm",
        )
        chip_x += width + 9
    apple = _item_sprite("golden_apple.png", 34).copy()
    if not fighter.heal_available:
        alpha = apple.getchannel("A").point(lambda value: int(value * 0.28))
        apple.putalpha(alpha)
    canvas.paste(apple, (x2 - 92, y2 - 50), apple)
    draw.text(
        (x2 - 52, y2 - 33),
        "READY" if fighter.heal_available else "USED",
        font=_font(10, bold=True),
        fill=(226, 190, 75) if fighter.heal_available else (104, 110, 104),
        anchor="lm",
    )


def _draw_action_effect(
    draw: ImageDraw.ImageDraw, action: str, left_box, right_box
) -> None:
    if action.startswith("attack_"):
        target = right_box if action == "attack_left" else left_box
        x1, y1, x2, y2 = target
        for offset in (0, 16, 32):
            draw.line(
                (x1 + 65 + offset, y1 + 158, x1 + 145 + offset, y1 + 82),
                fill=(255, 89, 72),
                width=7,
            )
    elif action.startswith("heal_"):
        target = left_box if action == "heal_left" else right_box
        x1, y1, _, _ = target
        for dx, dy in ((45, 150), (78, 172), (115, 145), (150, 178)):
            draw.ellipse(
                (x1 + dx, y1 + dy, x1 + dx + 10, y1 + dy + 10),
                fill=(105, 231, 114),
            )
    elif action.startswith("victory_"):
        target = left_box if action == "victory_left" else right_box
        draw.rounded_rectangle(target, radius=20, outline=(249, 196, 54), width=8)


def render_pvp_board(
    left: FighterVisual,
    right: FighterVisual,
    *,
    active_side: str | None,
    event: str,
    action: str = "idle",
) -> bytes:
    """Render the latest fight state as a Discord-ready PNG."""
    canvas = Image.new("RGB", (1100, 560), (13, 18, 14))
    backdrop = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    backdrop_draw = ImageDraw.Draw(backdrop)
    for y in range(0, 560, 44):
        for x in range(0, 1100, 44):
            shade = 28 + ((x // 44 + y // 44) % 2) * 5
            backdrop_draw.rectangle(
                (x, y, x + 43, y + 43), fill=(shade, shade + 8, shade, 90)
            )
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(1.5))
    canvas.paste(backdrop, (0, 0), backdrop)
    draw = ImageDraw.Draw(canvas)

    draw.text(
        (38, 34),
        "AESTRON // BLOCK ARENA",
        font=_font(15, bold=True),
        fill=(126, 227, 119),
    )
    draw.text(
        (1062, 34),
        "TURN-BASED PVP",
        font=_font(13, bold=True),
        fill=(119, 132, 121),
        anchor="ra",
    )
    left_box = (34, 72, 508, 458)
    right_box = (592, 72, 1066, 458)
    _draw_fighter(
        canvas, draw, left, left_box, active=active_side == "left", side="left"
    )
    _draw_fighter(
        canvas, draw, right, right_box, active=active_side == "right", side="right"
    )
    draw.rounded_rectangle((521, 210, 579, 268), radius=12, fill=(62, 76, 64))
    draw.text(
        (550, 239), "VS", font=_font(20, bold=True), fill=(240, 244, 237), anchor="mm"
    )
    _draw_action_effect(draw, action, left_box, right_box)

    draw.rounded_rectangle(
        (34, 482, 1066, 536), radius=14, fill=(20, 26, 22), outline=(58, 70, 60)
    )
    event_font = _font(17, bold=True)
    event_text = _bounded_text(draw, event, 965, event_font)
    draw.text(
        (550, 509),
        event_text,
        font=event_font,
        fill=(225, 231, 223),
        anchor="mm",
    )

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
