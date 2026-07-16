"""Image-first VALORANT dashboards rendered from official completed-match data."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .valorant_analytics import MatchPerformance, PlayerSummary, coaching_notes
from .valorant_assets import EquipmentArtwork, MapArtwork, ValorantArtwork

WIDTH = 1200
HEIGHT = 760
BACKGROUND = (10, 17, 24)
PANEL = (20, 31, 42)
PANEL_ALT = (27, 42, 56)
TEXT = (239, 243, 247)
MUTED = (148, 165, 181)
RED = (255, 70, 85)
MINT = (31, 215, 180)
GOLD = (244, 190, 74)
BLUE = (77, 151, 255)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: object,
    *,
    size: int = 18,
    color=TEXT,
    bold: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(xy, str(value), font=_font(size, bold=bold), fill=color, anchor=anchor)


def _fit(value: object, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _asset(data: bytes) -> Image.Image | None:
    """Decode one optional cached artwork response without breaking a command."""
    if not data:
        return None
    try:
        return Image.open(BytesIO(data)).convert("RGBA")
    except (OSError, ValueError):
        return None


def _panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill=PANEL,
    outline=(40, 57, 71),
) -> None:
    draw.rounded_rectangle(box, radius=15, fill=fill, outline=outline, width=2)


def _header(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    account: dict,
    title: str,
    subtitle: str,
    *,
    banner: bytes = b"",
) -> None:
    banner_image = _asset(banner)
    if banner_image is not None:
        banner_image = ImageOps.fit(
            banner_image, (WIDTH, 100), method=Image.Resampling.LANCZOS
        )
        banner_image = ImageEnhance.Brightness(banner_image).enhance(0.32)
        canvas.paste(banner_image, (0, 0), banner_image)
    _text(draw, (42, 28), "AESTRON // VALORANT LAB", size=13, color=RED, bold=True)
    riot_id = f"{account.get('accountname', 'Player')}#{account.get('accounttag', '')}"
    _text(draw, (42, 57), _fit(riot_id, 34), size=30, bold=True)
    _text(draw, (1158, 42), title.upper(), size=15, color=MUTED, bold=True, anchor="ra")
    _text(draw, (1158, 69), _fit(subtitle, 62), size=13, color=MUTED, anchor="ra")
    draw.line((42, 100, 1158, 100), fill=(42, 57, 70), width=2)


def _metric(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    detail: str,
    *,
    accent=MINT,
) -> None:
    _panel(draw, box)
    x1, y1, x2, _ = box
    draw.rectangle((x1, y1, x1 + 5, box[3]), fill=accent)
    _text(draw, (x1 + 20, y1 + 18), label.upper(), size=11, color=MUTED, bold=True)
    _text(draw, (x1 + 20, y1 + 47), value, size=27, bold=True)
    _text(draw, (x1 + 20, y1 + 82), _fit(detail, 30), size=12, color=MUTED)


def _bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    ratio: float,
    *,
    color=MINT,
) -> None:
    x1, y1, x2, y2 = box
    ratio = max(0.0, min(1.0, ratio))
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=(45, 58, 69))
    if ratio:
        draw.rounded_rectangle(
            (x1, y1, x1 + max(y2 - y1, int((x2 - x1) * ratio)), y2),
            radius=(y2 - y1) // 2,
            fill=color,
        )


def _sparkline(
    draw: ImageDraw.ImageDraw,
    values: list[float],
    box: tuple[int, int, int, int],
    *,
    color=MINT,
) -> None:
    x1, y1, x2, y2 = box
    if not values:
        return
    low, high = min(values), max(values)
    spread = max(1.0, high - low)
    step = (x2 - x1) / max(1, len(values) - 1)
    points = [
        (x1 + index * step, y2 - ((value - low) / spread) * (y2 - y1))
        for index, value in enumerate(values)
    ]
    if len(points) > 1:
        draw.line(points, fill=color, width=4, joint="curve")
    for x, y in points:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)


def _equipment_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    equipment: EquipmentArtwork | None,
    fallback: str,
) -> None:
    """Draw one weapon or shield card with current public store metadata."""
    x1, y1, x2, y2 = box
    _panel(draw, box, fill=(17, 28, 38))
    name = equipment.display_name if equipment else fallback
    detail = (
        f"{equipment.cost:,} credits · {equipment.category}"
        if equipment and equipment.cost
        else "Store metadata unavailable"
    )
    icon = _asset(equipment.display_icon) if equipment else None
    if icon is not None:
        icon.thumbnail((x2 - x1 - 32, 60), Image.Resampling.LANCZOS)
        icon_x = x1 + (x2 - x1 - icon.width) // 2
        canvas.paste(icon, (icon_x, y1 + 30), icon)
    card_draw = ImageDraw.Draw(canvas)
    _text(card_draw, (x1 + 14, y1 + 12), label, size=9, color=MUTED, bold=True)
    _text(
        card_draw,
        ((x1 + x2) // 2, y2 - 39),
        _fit(name, 25),
        size=16,
        bold=True,
        anchor="ma",
    )
    _text(
        card_draw, ((x1 + x2) // 2, y2 - 15), detail, size=9, color=MUTED, anchor="ma"
    )


def _equipment_fallback(identifier: str, label: str) -> str:
    """Avoid displaying opaque Riot UUIDs when artwork metadata is unavailable."""
    candidate = identifier.rstrip("/").rsplit("/", maxsplit=1)[-1].strip()
    return candidate if candidate and len(candidate) <= 24 else f"Unknown {label}"


def _map_plot(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchPerformance,
    artwork: MapArtwork | None,
    box: tuple[int, int, int, int],
    *,
    round_number: int | None = None,
) -> None:
    """Plot player kill/death locations on a cached minimap."""
    x1, y1, x2, y2 = box
    _panel(draw, box, fill=(13, 23, 31))
    if artwork is None:
        _text(
            draw,
            ((x1 + x2) // 2, (y1 + y2) // 2),
            "Map artwork unavailable",
            size=16,
            color=MUTED,
            anchor="mm",
        )
        return
    minimap = _asset(artwork.display_icon)
    if minimap is None:
        return
    target_width = x2 - x1 - 26
    target_height = y2 - y1 - 42
    minimap.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
    map_x = x1 + (x2 - x1 - minimap.width) // 2
    map_y = y1 + 28 + (target_height - minimap.height) // 2
    faded = ImageEnhance.Brightness(minimap).enhance(0.68)
    canvas.paste(faded, (map_x, map_y), faded)
    for event in match.kill_locations:
        if round_number is not None and event.round_number != round_number:
            continue
        normalized_x = event.y * artwork.x_multiplier + artwork.x_scalar
        normalized_y = event.x * artwork.y_multiplier + artwork.y_scalar
        if not 0 <= normalized_x <= 1 or not 0 <= normalized_y <= 1:
            continue
        marker_x = map_x + normalized_x * minimap.width
        marker_y = map_y + normalized_y * minimap.height
        color = MINT if event.outcome == "kill" else RED
        draw.ellipse(
            (marker_x - 8, marker_y - 8, marker_x + 8, marker_y + 8),
            fill=color,
            outline=TEXT,
            width=2,
        )
        _text(
            draw,
            (int(marker_x), int(marker_y)),
            event.round_number,
            size=8,
            color=BACKGROUND,
            bold=True,
            anchor="mm",
        )
    _text(draw, (x1 + 14, y1 + 13), "KILL MAP", size=10, color=MUTED, bold=True)
    _text(
        draw,
        (x2 - 14, y1 + 13),
        "MINT KILL · RED DEATH",
        size=9,
        color=MUTED,
        anchor="ra",
    )


def _round_detail(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchPerformance,
    artwork: ValorantArtwork,
    round_number: int,
) -> None:
    """Render one round with its event map, economy, and weapon evidence."""
    detail = next(
        (item for item in match.round_details if item.number == round_number), None
    )
    if detail is None:
        _text(
            draw,
            (600, 300),
            "Round data unavailable",
            size=26,
            color=MUTED,
            anchor="mm",
        )
        return
    _map_plot(
        canvas,
        draw,
        match,
        artwork.maps.get(match.map_id),
        (42, 125, 650, 718),
        round_number=round_number,
    )
    _panel(draw, (675, 125, 1158, 718))
    result = "WIN" if detail.won else "LOSS" if detail.won is False else "RESULT"
    result_color = MINT if detail.won else RED if detail.won is False else MUTED
    _text(
        draw, (700, 153), f"ROUND {detail.number:02}", size=13, color=MUTED, bold=True
    )
    _text(
        draw, (1132, 153), result, size=13, color=result_color, bold=True, anchor="ra"
    )
    _text(draw, (700, 194), detail.result.title(), size=27, bold=True)
    _metric(
        draw,
        (700, 235, 906, 345),
        "K / D / A",
        f"{detail.kills}/{detail.deaths}/{detail.assists}",
        "round contribution",
        accent=result_color,
    )
    _metric(
        draw,
        (926, 235, 1132, 345),
        "Damage",
        str(detail.damage),
        detail.opening_result
        and f"opener {detail.opening_result}"
        or "no opening duel",
        accent=GOLD,
    )
    weapon_art = artwork.weapons.get(detail.weapon)
    armor_art = artwork.gear.get(detail.armor)
    _equipment_card(
        canvas,
        draw,
        (700, 373, 910, 515),
        "PRIMARY WEAPON",
        weapon_art,
        _equipment_fallback(detail.weapon, "weapon"),
    )
    _equipment_card(
        canvas,
        draw,
        (922, 373, 1132, 515),
        "SHIELD",
        armor_art,
        _equipment_fallback(detail.armor, "shield"),
    )
    draw = ImageDraw.Draw(canvas)
    for index, (label, value, accent) in enumerate(
        (
            ("LOADOUT", f"{detail.loadout_value:,}", BLUE),
            ("SPENT", f"{detail.spent:,}", GOLD),
            ("BANK", f"{detail.remaining:,}", MINT),
            (
                "DAMAGE DIFF",
                f"{detail.damage_delta:+d}",
                RED if detail.damage_delta < 0 else MINT,
            ),
        )
    ):
        x = 700 + index * 108
        _text(draw, (x, 541), label, size=8, color=MUTED, bold=True)
        _text(draw, (x, 567), value, size=17, color=accent, bold=True)
    _text(
        draw,
        (700, 604),
        "HIT PROFILE",
        size=10,
        color=MUTED,
        bold=True,
    )
    _text(
        draw,
        (1132, 604),
        f"{detail.headshot_rate:.1f}% HEADSHOT HITS",
        size=10,
        color=GOLD,
        bold=True,
        anchor="ra",
    )
    total_hits = detail.headshots + detail.bodyshots + detail.legshots
    _bar(
        draw,
        (700, 621, 1132, 632),
        detail.headshots / max(1, total_hits),
        color=RED,
    )
    _text(
        draw,
        (700, 648),
        f"{detail.headshots} head · {detail.bodyshots} body · {detail.legshots} leg",
        size=10,
        color=MUTED,
    )
    _text(
        draw,
        (1132, 648),
        f"{detail.damage_received} received · opener {detail.opening_result or 'none'}",
        size=10,
        color=MUTED,
        anchor="ra",
    )
    weapon_events = [
        item
        for item in match.kill_locations
        if item.round_number == round_number and item.weapon_id in artwork.weapons
    ]
    for index, event in enumerate(weapon_events[:3]):
        item_art = artwork.weapons[event.weapon_id]
        weapon = _asset(item_art.kill_stream_icon or item_art.display_icon)
        if weapon is None:
            continue
        weapon.thumbnail((105, 35), Image.Resampling.LANCZOS)
        x = 700 + index * 142
        canvas.paste(weapon, (x, 668), weapon)
        _text(
            ImageDraw.Draw(canvas),
            (x + 112, 685),
            "K" if event.outcome == "kill" else "D",
            size=8,
            color=MINT if event.outcome == "kill" else RED,
            bold=True,
            anchor="lm",
        )


def _overview(draw: ImageDraw.ImageDraw, summary: PlayerSummary) -> None:
    cards = (
        (
            "Recent form",
            f"{summary.wins}W · {summary.losses}L",
            f"{summary.win_rate:.0f}% win rate",
            MINT,
        ),
        (
            "K / D / A",
            f"{summary.kills}/{summary.deaths}/{summary.assists}",
            f"{summary.kd_ratio:.2f} K/D",
            BLUE,
        ),
        ("Round impact", f"{summary.acs:.0f} ACS", f"{summary.adr:.0f} ADR", RED),
        ("Damage delta", f"{summary.damage_delta:+.0f}", "per played round", GOLD),
    )
    for index, (label, value, detail, accent) in enumerate(cards):
        x = 42 + index * 279
        _metric(draw, (x, 125, x + 259, 235), label, value, detail, accent=accent)

    _panel(draw, (42, 258, 763, 474))
    _text(draw, (64, 279), "RECENT MATCH ACTIVITY", size=12, color=MUTED, bold=True)
    performances = list(summary.performances[:10])
    for index, match in enumerate(performances):
        x1 = 64 + index * 67
        color = MINT if match.won else RED
        draw.rounded_rectangle((x1, 316, x1 + 52, 374), radius=8, fill=color)
        _text(
            draw,
            (x1 + 26, 337),
            "W" if match.won else "L",
            size=18,
            bold=True,
            anchor="mm",
        )
        _text(
            draw,
            (x1 + 26, 391),
            _fit(match.map_name, 7),
            size=9,
            color=MUTED,
            anchor="ma",
        )
        _text(
            draw,
            (x1 + 26, 412),
            f"{match.kd_ratio:.1f}",
            size=13,
            bold=True,
            anchor="ma",
        )
    _text(draw, (64, 444), "ACS TREND", size=10, color=MUTED, bold=True)
    _sparkline(
        draw, [item.acs for item in performances], (152, 430, 735, 457), color=BLUE
    )

    _panel(draw, (783, 258, 1158, 474))
    _text(draw, (805, 279), "ROUND PROFILE", size=12, color=MUTED, bold=True)
    rows = (
        ("Headshot hits", summary.headshot_rate / 100, f"{summary.headshot_rate:.1f}%"),
        (
            "Round survival",
            summary.survival_rate / 100,
            f"{summary.survival_rate:.1f}%",
        ),
        (
            "Opening duels",
            summary.opening_duel_rate / 100,
            f"{summary.first_kills}-{summary.first_deaths}",
        ),
    )
    for index, (label, ratio, value) in enumerate(rows):
        y = 316 + index * 48
        _text(draw, (805, y), label, size=12, color=MUTED)
        _text(draw, (1136, y), value, size=12, bold=True, anchor="ra")
        _bar(draw, (805, y + 20, 1136, y + 31), ratio)

    _panel(draw, (42, 498, 1158, 718), fill=(15, 25, 34))
    _text(draw, (64, 519), "POST-MATCH REVIEW SIGNALS", size=12, color=RED, bold=True)
    notes = coaching_notes(summary)[:3]
    for index, note in enumerate(notes, start=1):
        y = 552 + (index - 1) * 51
        draw.rounded_rectangle((64, y, 98, y + 34), radius=8, fill=PANEL_ALT)
        _text(draw, (81, y + 17), index, size=14, bold=True, anchor="mm")
        _text(draw, (114, y + 5), _fit(note, 132), size=13, color=(211, 220, 228))


def _matches(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    summary: PlayerSummary,
    artwork: ValorantArtwork,
) -> None:
    _text(draw, (42, 125), "RECENT COMPLETED MATCHES", size=14, color=MUTED, bold=True)
    for index, match in enumerate(summary.performances[:8], start=1):
        y = 156 + (index - 1) * 67
        color = MINT if match.won else RED
        _panel(draw, (42, y, 1158, y + 55), fill=PANEL if index % 2 else PANEL_ALT)
        draw.rectangle((42, y, 48, y + 55), fill=color)
        _text(
            draw,
            (67, y + 27),
            f"{index:02}",
            size=13,
            color=MUTED,
            bold=True,
            anchor="lm",
        )
        agent = _asset(artwork.agents.get(match.agent_id, b""))
        text_x = 112
        if agent is not None:
            agent = ImageOps.fit(agent, (48, 48), method=Image.Resampling.LANCZOS)
            canvas.paste(agent, (105, y + 3), agent)
            text_x = 166
        _text(draw, (text_x, y + 17), match.map_name, size=17, bold=True)
        _text(
            draw,
            (text_x, y + 38),
            f"{match.agent_name} · {match.queue.title()}",
            size=11,
            color=MUTED,
        )
        _text(
            draw,
            (465, y + 27),
            match.scoreline,
            size=21,
            color=color,
            bold=True,
            anchor="mm",
        )
        _text(draw, (590, y + 17), "K / D / A", size=10, color=MUTED, bold=True)
        _text(
            draw,
            (590, y + 38),
            f"{match.kills} / {match.deaths} / {match.assists}",
            size=15,
            bold=True,
        )
        for x, label, value in (
            (790, "ACS", f"{match.acs:.0f}"),
            (900, "ADR", f"{match.adr:.0f}"),
            (1010, "DMG +/-", f"{match.damage_delta:+.0f}"),
        ):
            _text(draw, (x, y + 17), label, size=10, color=MUTED, bold=True)
            _text(draw, (x, y + 39), value, size=15, bold=True)
    _text(
        draw,
        (42, 715),
        "Select a numbered match in Discord to open its dashboard.",
        size=12,
        color=MUTED,
    )


def _match_summary(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchPerformance,
    artwork: ValorantArtwork,
) -> None:
    result_color = MINT if match.won else RED
    _panel(draw, (42, 125, 1158, 252), fill=(24, 34, 44))
    agent = _asset(artwork.agents.get(match.agent_id, b""))
    if agent is not None:
        agent.thumbnail((260, 150), Image.Resampling.LANCZOS)
        agent = ImageEnhance.Brightness(agent).enhance(0.7)
        canvas.paste(agent, (690, 108), agent)
    _text(
        draw,
        (66, 151),
        "VICTORY" if match.won else "DEFEAT",
        size=13,
        color=result_color,
        bold=True,
    )
    _text(draw, (66, 180), match.map_name, size=34, bold=True)
    _text(
        draw,
        (66, 222),
        f"{match.agent_name} · {match.queue.title()}",
        size=14,
        color=MUTED,
    )
    _text(
        draw,
        (540, 188),
        match.scoreline,
        size=42,
        color=result_color,
        bold=True,
        anchor="mm",
    )
    _text(
        draw,
        (1118, 163),
        f"{match.kills} / {match.deaths} / {match.assists}",
        size=25,
        bold=True,
        anchor="ra",
    )
    _text(
        draw,
        (1118, 204),
        f"{match.kd_ratio:.2f} K/D · {match.headshot_rate:.1f}% HS",
        size=14,
        color=MUTED,
        anchor="ra",
    )
    metrics = (
        ("ACS", f"{match.acs:.0f}", RED),
        ("ADR", f"{match.adr:.0f}", GOLD),
        ("DAMAGE DELTA", f"{match.damage_delta:+.0f}", BLUE),
        ("SURVIVAL", f"{match.survival_rate:.0f}%", MINT),
    )
    for index, (label, value, color) in enumerate(metrics):
        x = 42 + index * 279
        _metric(
            draw,
            (x, 276, x + 259, 386),
            label,
            value,
            "per-round context",
            accent=color,
        )

    _map_plot(canvas, draw, match, artwork.maps.get(match.map_id), (42, 410, 548, 718))
    _panel(draw, (568, 410, 1158, 718))
    _text(draw, (590, 432), "ROUND TIMELINE", size=12, color=MUTED, bold=True)
    details = match.round_details[:26]
    for index, item in enumerate(details):
        row, column = divmod(index, 13)
        x = 590 + column * 41
        y = 468 + row * 78
        color = MINT if item.won else RED if item.won is False else (91, 105, 117)
        draw.rounded_rectangle((x, y, x + 39, y + 62), radius=5, fill=PANEL_ALT)
        draw.rectangle((x, y + 56, x + 39, y + 62), fill=color)
        _text(draw, (x + 19.5, y + 14), item.number, size=9, color=MUTED, anchor="ma")
        _text(draw, (x + 19.5, y + 39), item.kills, size=15, bold=True, anchor="mm")
    _text(draw, (590, 637), "OPENERS", size=10, color=MUTED, bold=True)
    _text(
        draw,
        (590, 662),
        f"{match.first_kills} won · {match.first_deaths} lost",
        size=17,
        bold=True,
    )
    _text(draw, (805, 637), "MULTIKILLS", size=10, color=MUTED, bold=True)
    _text(draw, (805, 662), match.multi_kill_rounds, size=17, bold=True)
    _text(draw, (970, 637), "OBJECTIVES", size=10, color=MUTED, bold=True)
    _text(draw, (970, 662), f"{match.plants}P · {match.defuses}D", size=17, bold=True)


def _rounds(draw: ImageDraw.ImageDraw, match: MatchPerformance) -> None:
    _text(draw, (42, 125), "ROUND-BY-ROUND REVIEW", size=14, color=MUTED, bold=True)
    for index, item in enumerate(match.round_details[:24]):
        column = index % 4
        row = index // 4
        x, y = 42 + column * 279, 156 + row * 91
        color = MINT if item.won else RED if item.won is False else MUTED
        _panel(draw, (x, y, x + 259, y + 76), fill=PANEL_ALT if row % 2 else PANEL)
        _text(
            draw,
            (x + 15, y + 15),
            f"R{item.number:02}",
            size=12,
            color=color,
            bold=True,
        )
        _text(
            draw,
            (x + 15, y + 43),
            f"{item.kills}/{item.deaths}/{item.assists}",
            size=19,
            bold=True,
        )
        _text(
            draw,
            (x + 104, y + 47),
            f"{item.damage} dmg · diff {item.damage_delta:+d}",
            size=11,
            color=MUTED,
        )
        if item.opening_result:
            _text(
                draw,
                (x + 244, y + 17),
                f"opener {item.opening_result}",
                size=9,
                color=color,
                anchor="ra",
            )


def _economy(draw: ImageDraw.ImageDraw, match: MatchPerformance) -> None:
    recorded = [item for item in match.round_details if item.loadout_value]
    _text(draw, (42, 125), "PERSONAL ECONOMY", size=14, color=MUTED, bold=True)
    if not recorded:
        _panel(draw, (42, 156, 1158, 310))
        _text(
            draw,
            (600, 220),
            "Riot returned no per-round economy for this match.",
            size=22,
            color=MUTED,
            anchor="mm",
        )
        return
    average = sum(item.loadout_value for item in recorded) / len(recorded)
    _metric(
        draw,
        (42, 156, 355, 266),
        "Average loadout",
        f"{average:,.0f}",
        f"{len(recorded)}/{match.rounds} rounds",
        accent=MINT,
    )
    _metric(
        draw,
        (375, 156, 688, 266),
        "Damage efficiency",
        f"{match.economy_efficiency:.1f}",
        "damage per 1k loadout",
        accent=GOLD,
    )
    best = max(recorded, key=lambda item: item.damage / max(1, item.loadout_value))
    _metric(
        draw,
        (708, 156, 1158, 266),
        "Best value round",
        f"R{best.number:02} · {best.damage} dmg",
        f"{best.loadout_value:,} credit loadout",
        accent=BLUE,
    )
    _panel(draw, (42, 290, 1158, 718))
    _text(draw, (64, 315), "LOADOUT VALUE BY ROUND", size=12, color=MUTED, bold=True)
    maximum = max(item.loadout_value for item in recorded) or 1
    bar_width = min(38, 1020 // len(recorded))
    for index, item in enumerate(recorded):
        x = 70 + index * bar_width
        height = int(270 * item.loadout_value / maximum)
        color = MINT if item.damage >= match.adr else PANEL_ALT
        draw.rounded_rectangle(
            (x, 625 - height, x + bar_width - 6, 625), radius=4, fill=color
        )
        _text(
            draw,
            (x + (bar_width - 6) / 2, 643),
            item.number,
            size=9,
            color=MUTED,
            anchor="ma",
        )
    _text(
        draw,
        (64, 686),
        "Mint bars met or exceeded the match's average damage per round.",
        size=11,
        color=MUTED,
    )


def _duels(draw: ImageDraw.ImageDraw, match: MatchPerformance) -> None:
    _text(draw, (42, 125), "OPPONENT DUEL MATRIX", size=14, color=MUTED, bold=True)
    if not match.duels:
        _panel(draw, (42, 156, 1158, 310))
        _text(
            draw,
            (600, 220),
            "No opponent kill events were returned.",
            size=22,
            color=MUTED,
            anchor="mm",
        )
        return
    for index, duel in enumerate(match.duels[:10]):
        column, row = index % 2, index // 2
        x, y = 42 + column * 568, 156 + row * 104
        color = (
            MINT if duel.differential > 0 else RED if duel.differential < 0 else GOLD
        )
        _panel(draw, (x, y, x + 548, y + 88), fill=PANEL_ALT if row % 2 else PANEL)
        _text(draw, (x + 18, y + 18), _fit(duel.opponent, 30), size=17, bold=True)
        _text(draw, (x + 18, y + 52), "kills vs deaths", size=10, color=MUTED)
        _text(
            draw,
            (x + 440, y + 37),
            f"{duel.kills} – {duel.deaths}",
            size=25,
            color=color,
            bold=True,
            anchor="mm",
        )
        _text(
            draw,
            (x + 526, y + 37),
            f"{duel.differential:+d}",
            size=13,
            color=color,
            bold=True,
            anchor="rm",
        )


def _trends(draw: ImageDraw.ImageDraw, summary: PlayerSummary) -> None:
    _panel(draw, (42, 125, 560, 446))
    _text(draw, (64, 149), "AGENT SAMPLE", size=12, color=MUTED, bold=True)
    maximum = max(summary.agents.values(), default=1)
    for index, (name, count) in enumerate(summary.agents.most_common(5)):
        y = 190 + index * 47
        _text(draw, (64, y), _fit(name, 22), size=14, bold=True)
        _bar(draw, (240, y + 3, 510, y + 16), count / maximum, color=RED)
        _text(draw, (530, y + 10), count, size=12, color=MUTED, anchor="rm")
    _panel(draw, (580, 125, 1158, 446))
    _text(draw, (602, 149), "MAP SAMPLE", size=12, color=MUTED, bold=True)
    maximum = max(summary.maps.values(), default=1)
    for index, (name, count) in enumerate(summary.maps.most_common(5)):
        y = 190 + index * 47
        _text(draw, (602, y), _fit(name, 22), size=14, bold=True)
        _bar(draw, (780, y + 3, 1080, y + 16), count / maximum, color=BLUE)
        _text(draw, (1125, y + 10), count, size=12, color=MUTED, anchor="rm")
    _panel(draw, (42, 470, 1158, 718))
    _text(draw, (64, 494), "RECENT ACS / ADR", size=12, color=MUTED, bold=True)
    performances = list(reversed(summary.performances[:10]))
    _sparkline(
        draw, [item.acs for item in performances], (82, 540, 1118, 620), color=RED
    )
    _sparkline(
        draw, [item.adr for item in performances], (82, 625, 1118, 686), color=GOLD
    )
    _text(draw, (64, 548), "ACS", size=10, color=RED, bold=True)
    _text(draw, (64, 634), "ADR", size=10, color=GOLD, bold=True)


def _notes(draw: ImageDraw.ImageDraw, summary: PlayerSummary, *, guide: bool) -> None:
    if guide:
        notes = [
            "ACS is Riot's combat score divided by rounds played.",
            "ADR is recorded damage dealt divided by rounds played.",
            "Damage delta is dealt minus received damage per round.",
            "Opening duels count the first kill or first death in each round.",
            "No hidden MMR, ELO, or third-party skill score is estimated.",
        ]
        heading = "HOW TO READ THE DASHBOARD"
    else:
        notes = coaching_notes(summary)
        heading = "POST-MATCH REVIEW PLAN"
    _text(draw, (42, 125), heading, size=14, color=MUTED, bold=True)
    for index, note in enumerate(notes[:5], start=1):
        y = 160 + (index - 1) * 105
        _panel(draw, (42, y, 1158, y + 86), fill=PANEL_ALT if index % 2 == 0 else PANEL)
        draw.rounded_rectangle((62, y + 19, 110, y + 67), radius=12, fill=(35, 50, 63))
        _text(
            draw,
            (86, y + 43),
            f"{index:02}",
            size=16,
            color=RED,
            bold=True,
            anchor="mm",
        )
        _text(draw, (132, y + 17), _fit(note, 142), size=15, color=(215, 224, 231))


def render_valorant_dashboard(
    account: dict,
    summary: PlayerSummary,
    *,
    page: str,
    artwork: ValorantArtwork | None = None,
) -> bytes:
    """Render a Discord-ready dashboard for an aggregate or match-specific page."""
    artwork = artwork or ValorantArtwork()
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    parts = page.split(":")
    focused_match = None
    if page.startswith("match:") and len(parts) > 1:
        try:
            focused_match = summary.performances[int(parts[1])]
        except (IndexError, ValueError):
            focused_match = None
    if focused_match is None and summary.performances:
        focused_match = summary.performances[0]
    if len(parts) == 4 and parts[2] == "round":
        title = f"match review · round {parts[3]}"
    elif page.startswith("match:"):
        section = parts[2] if len(parts) > 2 else "summary"
        title = f"match review · {section}"
    else:
        title = page.replace(":", " · ").replace("match", "match review")
    banner = b""
    if focused_match is not None:
        banner = artwork.cards.get(focused_match.player_card_id, b"")
        map_artwork = artwork.maps.get(focused_match.map_id)
        if not banner and map_artwork is not None:
            banner = map_artwork.splash
    if page == "matches":
        _matches(canvas, draw, summary, artwork)
    elif page == "breakdown":
        _trends(draw, summary)
    elif page == "coaching":
        _notes(draw, summary, guide=False)
    elif page == "metrics":
        _notes(draw, summary, guide=True)
    elif page.startswith("match:"):
        index = int(parts[1])
        match = summary.performances[index]
        section = parts[2] if len(parts) > 2 else "summary"
        if section == "round" and len(parts) > 3:
            _round_detail(canvas, draw, match, artwork, int(parts[3]))
        elif section == "rounds":
            _rounds(draw, match)
        elif section == "economy":
            _economy(draw, match)
        elif section == "duels":
            _duels(draw, match)
        else:
            _match_summary(canvas, draw, match, artwork)
    else:
        _overview(draw, summary)
    # Composite the banner last because page renderers paste transparent Riot
    # artwork into the same PIL image. Drawing the header after those composites
    # guarantees its labels remain crisp with every Pillow backend.
    _header(
        canvas,
        ImageDraw.Draw(canvas),
        account,
        title,
        f"{summary.matches} matches · {summary.rounds} rounds · completed data only",
        banner=banner,
    )
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
