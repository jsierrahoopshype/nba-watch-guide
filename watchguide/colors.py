"""Contrast maths for the team color accents (data/team_colors.json).

A team color is only ever a ring or an edge, never text, so the bar it has
to clear is WCAG 1.4.11 non-text contrast: 3:1 against the white card. A
light primary (the Spurs' silver) is darkened until it does.
"""

from __future__ import annotations

SURFACE = "#FFFFFF"
NON_TEXT_MIN = 3.0


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def accent(hex_color: str, against: str = SURFACE, minimum: float = NON_TEXT_MIN) -> str:
    """The color itself when it clears `minimum` against `against`, otherwise
    the same hue darkened in 5% steps until it does."""
    color = hex_color.upper()
    r, g, b = _rgb(color)
    factor = 1.0
    while contrast(color, against) < minimum and factor > 0:
        factor = round(factor - 0.05, 2)
        color = "#{:02X}{:02X}{:02X}".format(int(r * factor), int(g * factor), int(b * factor))
    return color
