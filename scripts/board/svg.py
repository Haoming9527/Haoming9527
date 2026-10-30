"""The SVG writer, the light/dark palettes and logo embedding."""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
import re

from .formatting import fit


ROOT = Path(__file__).resolve().parents[2]


LOGOS = ROOT / "assets/logos"


FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"


THEMES = {
    "light": dict(bg="#ffffff", card="#f6f8fa", fg="#1f2328", muted="#59636e", faint="#d8dee4",
                  grid="#eaeef2", up="#1a7f37", up_fill="#2da44e", down="#cf222e", down_fill="#e5484d",
                  flat="#8c959f", ring="#d0d7de", pill="#eaeef2", ma=("#bf8700", "#8250df")),
    "dark": dict(bg="#0d1117", card="#151b23", fg="#f0f6fc", muted="#9198a1", faint="#2a313c",
                 grid="#1f2630", up="#3fb950", up_fill="#2ea043", down="#f85149", down_fill="#da3633",
                 flat="#6e7681", ring="#0d1117", pill="#262c36", ma=("#e3b341", "#a371f7")),
}


GENERIC_LOGO = "M8 7 L3 12 L8 17 M16 7 L21 12 L16 17 M14 5 L10 19"


class SVG:
    def __init__(self, width: float, height: float, theme: str, label: str, extra_css: str = ""):
        self.w, self.h, self.theme, self.p = width, height, theme, THEMES[theme]
        self.uid = 0
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
            f'viewBox="0 0 {width:g} {height:g}" role="img" aria-label="{escape(label)}">',
            f'<style>text{{font-family:{FONT};font-variant-numeric:tabular-nums}}'
            '.draw{stroke-dasharray:1;animation:draw 1.4s cubic-bezier(.3,.7,.2,1) both}'
            '@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}'
            '.pulse{transform-box:fill-box;transform-origin:center;animation:pulse 2.6s ease-out infinite}'
            '@keyframes pulse{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(3.2);opacity:0}}'
            f'{extra_css}'
            '@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>',
        ]
        self.rect(0, 0, width, height, "bg")

    def color(self, value: str) -> str:
        return self.p.get(value, value)

    def add(self, markup: str):
        self.parts.append(markup)

    def next_id(self) -> str:
        self.uid += 1
        return f"u{self.uid}"

    def rect(self, x, y, w, h, fill, r=0, **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" rx="{r:g}" '
                 f'fill="{self.color(fill)}"{extra}/>')

    def text(self, x, y, value, size=16, fill="fg", weight=400, anchor="start", **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:g}" font-weight="{weight}" '
                 f'fill="{self.color(fill)}" text-anchor="{anchor}"{extra}>{escape(str(value))}</text>')

    def line(self, x1, y1, x2, y2, stroke="faint", width=1, **attrs):
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{self.color(stroke)}" stroke-width="{width:g}"{extra}/>')

    def sparkline(self, values, x, y, w, h, stroke, fill=True, dot=True, width=2):
        values = list(values) or [0]
        if len(values) == 1:
            values *= 2
        lo, hi = min(values), max(values)
        span = hi - lo
        points = [(x + i / (len(values) - 1) * w, y + h / 2 if not span else y + h - (v - lo) / span * h)
                  for i, v in enumerate(values)]
        path = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points)
        color = self.color(stroke)
        if fill:
            gid = self.next_id()
            self.add(f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                     f'<stop offset="0" stop-color="{color}" stop-opacity=".16"/>'
                     f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>')
            self.add(f'<path d="{path} L{x + w:.1f} {y + h:.1f} L{x:.1f} {y + h:.1f} Z" fill="url(#{gid})"/>')
        self.add(f'<path class="draw" pathLength="1" d="{path}" fill="none" stroke="{color}" '
                 f'stroke-width="{width:g}" stroke-linejoin="round" stroke-linecap="round"/>')
        if dot:
            px, py = points[-1]
            self.add(f'<circle class="pulse" cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>'
                     f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>')

    def image(self, filename: str, x, y, w, h, aspect="xMidYMid meet", clip: str | None = None):
        source = LOGOS / filename
        mime = "image/png" if source.suffix == ".png" else "image/jpeg"
        data = base64.b64encode(source.read_bytes()).decode()
        clip_attr = f' clip-path="url(#{clip})"' if clip else ""
        self.add(f'<image href="data:{mime};base64,{data}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'preserveAspectRatio="{aspect}"{clip_attr}/>')

    def vector(self, markup: str, x, y, side):
        view_box = re.search(r'viewBox="([^"]+)"', markup)
        attrs = re.search(r"<svg\b([^>]*)>", markup)
        fill = re.search(r'\sfill="([^"]+)"', attrs.group(1)) if attrs else None
        inner = re.sub(r"(?s)^.*?<svg[^>]*>|</svg>\s*$|<title>.*?</title>", "", markup)
        prefix = self.next_id()
        inner = re.sub(r'id="([^"]+)"', lambda m: f'id="{prefix}{m.group(1)}"', inner)
        inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{prefix}{m.group(1)})", inner)
        fill_attr = f' fill="{fill.group(1)}"' if fill and fill.group(1) != "currentColor" else ""
        self.add(f'<svg x="{x:.1f}" y="{y:.1f}" width="{side:.1f}" height="{side:.1f}" '
                 f'viewBox="{view_box.group(1) if view_box else "0 0 24 24"}"{fill_attr}>{inner}</svg>')

    def logo(self, cx, cy, r, spec: dict, square: bool = False):
        """A real logo in a white disc (or rounded tile), the way brokerage apps show tickers."""
        clip = self.next_id()
        shape = (f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" rx="{r * .32:.1f}"'
                 if square else f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}"')
        self.add(f'{shape} fill="#ffffff" stroke="{self.color("ring")}" stroke-width="1"/>'
                 f'<clipPath id="{clip}">{shape}/></clipPath>')
        scale = spec.get("scale", .6)
        if "file" in spec and not spec["file"].endswith(".svg"):
            cover = spec.get("fit") == "cover"
            side = 2 * r if cover else 2 * r * scale
            self.image(spec["file"], cx - side / 2, cy - side / 2, side, side,
                       "xMidYMid slice" if cover else "xMidYMid meet", clip)
        elif "file" in spec or "svg" in spec:
            markup = spec["svg"] if "svg" in spec else (LOGOS / spec["file"]).read_text(encoding="utf-8")
            side = 2 * r * scale
            self.vector(markup, cx - side / 2, cy - side / 2, side)
        else:
            side = 2 * r * .56
            self.add(f'<path d="{GENERIC_LOGO}" transform="translate({cx - side / 2:.1f} {cy - side / 2:.1f}) '
                     f'scale({side / 24:.3f})" fill="none" stroke="#59636e" stroke-width="2.2" '
                     'stroke-linecap="round" stroke-linejoin="round"/>')

    def chevron(self, x, y, size=9, stroke="muted"):
        self.add(f'<path d="M{x:.1f} {y - size:.1f} L{x + size * .62:.1f} {y:.1f} L{x:.1f} {y + size:.1f}" fill="none" '
                 f'stroke="{self.color(stroke)}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')

    def badge(self, x, y, w, h, value: float, label: str, size: float):
        fill = "up_fill" if value > 0 else "down_fill" if value < 0 else "flat"
        self.rect(x, y, w, h, fill, 6)
        self.text(x + w / 2, y + h / 2 + size * .36, fit(label, size, w - 8, 700), size, "#ffffff", 700, "middle")

    def svg(self) -> str:
        return "\n".join(self.parts + ["</svg>"]) + "\n"
