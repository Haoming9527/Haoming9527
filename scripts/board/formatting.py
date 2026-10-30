"""Number and text formatting shared by every widget."""
from __future__ import annotations



MINUS = "\u2212"


def num(value: float) -> str:
    return (MINUS if value < 0 else "") + f"{abs(round(value)):,}"


def compact(value: float) -> str:
    sign, value = (MINUS if value < 0 else ""), abs(value)
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.1f}m"
    if value >= 10_000:
        return f"{sign}{value / 1000:.1f}k"
    return f"{sign}{round(value):,}"


def kilo(value: float) -> str:
    return f"{value / 1000:.1f}k" if abs(value) >= 1000 else f"{round(value)}"


def signed(value: float, short: bool = False) -> str:
    if not value:
        return "0"
    return ("+" if value > 0 else MINUS) + (compact(abs(value)) if short else f"{abs(round(value)):,}")


def percent(delta: float, base: float) -> str:
    if not base:
        return ""
    value = delta / abs(base) * 100
    return ("+" if value > 0 else MINUS if value < 0 else "") + f"{abs(value):.2f}%"


def size_label(size: int) -> str:
    return f"{size / 1_048_576:.1f} MB" if size >= 1_048_576 else f"{max(size / 1024, .1):.0f} KB"


def text_width(value: str, size: float, weight: int = 400) -> float:
    """Generous width estimate for system sans fonts, used only for layout."""
    width = 0.0
    for char in value:
        if char == " ":
            width += .28
        elif char in ".,:;'|!il":
            width += .3
        elif char.isdigit():
            width += .6
        elif char.isupper() or char in "%&@MW":
            width += .68
        elif char.isascii():
            width += .54
        else:
            width += .8
    return width * size * (1.06 if weight >= 600 else 1)


def fit(value: str, size: float, room: float, weight: int = 400) -> str:
    if text_width(value, size, weight) <= room:
        return value
    while value and text_width(value + "…", size, weight) > room:
        value = value[:-1]
    return value.rstrip() + "…"


def wrap(value: str, size: float, room: float, weight: int = 400) -> list[str]:
    lines, line = [], ""
    for word in value.split():
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, size, weight) > room:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line else lines


def tone(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"
