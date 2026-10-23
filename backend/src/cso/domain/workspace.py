"""Workspace settings: the constants, the rules and the logo sanitiser.

Pure functions, no I/O. A workspace is the instance's public face (name, tagline, accent colour,
logo, the paragraph for communities) and a few switches. None of it touches the invariants: the
words are checked against the same banned list as drafts, the accent has to be readable on both
canvases, and a logo is reduced to plain shapes before it is stored.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from cso.domain.config import Tone
from cso.domain.draft_validation import contains_banned_word

DEFAULT_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_SLUG = "default"

# The seed row. The web app keeps the same sentences in `web/src/landing/copy.ts` as its fallback.
DEFAULT_NAME = "Changeset Second Opinion"
DEFAULT_TAGLINE = "Evidence first; a human posts."
DEFAULT_ACCENT = "#4E5BD8"
DEFAULT_PARAGRAPH = (
    "Every community looks after the map in its own way. Pick a pack that fits yours, such as a "
    "warmer welcome for newcomers or closer scrutiny, and adjust it from your own reviewers' "
    "decisions. Nothing changes unless an admin applies it."
)

NAME_MAX = 48
TAGLINE_MAX = 120
PARAGRAPH_MAX = 400
LOGO_MAX_BYTES = 32 * 1024
MIN_CONTRAST = 4.5
LIGHT_CANVAS = "#F6F5F2"
DARK_CANVAS = "#0F1012"

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SVG_NS = "http://www.w3.org/2000/svg"
# Elements a logo may use: plain shapes and text-free structure, nothing that can run or fetch.
_ALLOWED_TAGS = frozenset(
    (
        "svg g path rect circle ellipse line polyline polygon title desc "
        "defs clipPath linearGradient radialGradient stop"
    ).split()
)
_FORBIDDEN_TAGS = frozenset({"script", "foreignObject", "style", "use", "image", "a", "iframe"})


@dataclass(frozen=True)
class FieldProblem:
    """One failed field, named so the form can point at it. Never carries the offending text."""

    field: str
    message: str


class LogoRejected(ValueError):
    """The logo cannot be stored; the message says why without repeating the file."""


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG 2.x relative luminance of `#rrggbb`."""
    if not _HEX.match(color):
        raise ValueError("not a #rrggbb colour")
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio of two `#rrggbb` colours (1 to 21)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def derive_dark_accent(accent: str) -> str:
    """The accent as it is drawn on the dark canvas: the same colour lightened until it reads at
    4.5:1 there. (No single colour reaches 4.5:1 on both canvases: that would need a luminance of
    at most 0.164 on the light one and at least 0.202 on the dark one.)"""
    r, g, b = (int(accent[i : i + 2], 16) for i in (1, 3, 5))
    for step in range(0, 101, 2):
        mix = step / 100
        rgb = tuple(round(c + (255 - c) * mix) for c in (r, g, b))
        candidate = "#{:02X}{:02X}{:02X}".format(*rgb)
        if contrast_ratio(candidate, DARK_CANVAS) >= MIN_CONTRAST:
            return candidate
    return "#FFFFFF"


def accent_contrast(accent: str) -> tuple[float, float]:
    """The accent's contrast on the light canvas, and its dark variant's on the dark canvas."""
    return (
        contrast_ratio(accent, LIGHT_CANVAS),
        contrast_ratio(derive_dark_accent(accent), DARK_CANVAS),
    )


def check_text(field: str, value: str, limit: int, tone: Tone) -> list[FieldProblem]:
    """Length and wording rules for one free-text field."""
    problems: list[FieldProblem] = []
    if not value.strip():
        problems.append(FieldProblem(field, "This cannot be empty."))
    if len(value) > limit:
        problems.append(FieldProblem(field, f"This is longer than {limit} characters."))
    if contains_banned_word(value, tone):
        problems.append(FieldProblem(field, "This uses a word the tool does not use."))
    return problems


def check_accent(value: str) -> list[FieldProblem]:
    """`#rrggbb` that reads at 4.5:1 on the light canvas; the dark variant is derived from it."""
    if not _HEX.match(value):
        return [FieldProblem("accent_hex", "Use a colour written as #rrggbb.")]
    light, _dark = accent_contrast(value)
    if light < MIN_CONTRAST:
        return [
            FieldProblem(
                "accent_hex",
                f"Contrast on the light canvas is {light:.2f}; at least {MIN_CONTRAST} is needed. "
                "Pick a darker colour; the dark theme gets a lightened copy automatically.",
            )
        ]
    return []


def sanitize_logo(svg: str) -> str:
    """The logo as safe SVG text, or `LogoRejected`.

    Parsed with defusedxml (no DTDs, no entities, no external resources). Rejected when it holds a
    script, a foreignObject, a style, `use`, `image` or link element, any `on*` attribute, any
    `href` that does not start with `#`, or an element outside the allow-list. Rendering is by
    `<img>`, so the page's CSP applies as well; this is the second lock.
    """
    if len(svg.encode("utf-8")) > LOGO_MAX_BYTES:
        raise LogoRejected(f"The logo is larger than {LOGO_MAX_BYTES // 1024} KB.")
    try:
        root = SafeET.fromstring(svg.encode("utf-8"))
    except DefusedXmlException as exc:
        raise LogoRejected("The logo uses an XML feature that is not allowed.") from exc
    except SafeET.ParseError as exc:
        raise LogoRejected("The logo is not valid SVG.") from exc
    if root.tag != f"{{{_SVG_NS}}}svg":
        raise LogoRejected("The logo must be an SVG document.")
    for node in root.iter():
        tag = node.tag.split("}", 1)[-1] if isinstance(node.tag, str) else ""
        if tag in _FORBIDDEN_TAGS:
            raise LogoRejected(f"The logo contains a <{tag}> element, which is not allowed.")
        if tag not in _ALLOWED_TAGS:
            raise LogoRejected("The logo contains an element that is not allowed.")
        for name, value in node.attrib.items():
            local = name.split("}", 1)[-1].lower()
            if local.startswith("on"):
                raise LogoRejected("The logo contains an event handler, which is not allowed.")
            if local == "href" and not value.strip().startswith("#"):
                raise LogoRejected("The logo links to something outside itself.")
            if "javascript:" in value.lower() or "data:" in value.lower():
                raise LogoRejected("The logo contains a script or data address.")
    return svg


def settings_hash(values: dict[str, Any]) -> str:
    """A short stable fingerprint of the settings, for the audit trail (never the logo bytes)."""
    clean = {k: v for k, v in sorted(values.items()) if k != "logo_svg"}
    clean["logo_sha"] = (
        hashlib.sha256(str(values.get("logo_svg") or "").encode("utf-8")).hexdigest()[:12]
        if values.get("logo_svg")
        else None
    )
    text = json.dumps(clean, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def manifest_for(name: str, accent: str) -> dict[str, Any]:
    """The web app manifest, following the workspace name and accent."""
    short = name if len(name) <= 12 else name[:12].rstrip()
    return {
        "name": name,
        "short_name": short,
        "description": f"{DEFAULT_NAME}: a second opinion on flagged OpenStreetMap edits.",
        "start_url": "/queue",
        "scope": "/",
        "display": "standalone",
        "background_color": LIGHT_CANVAS,
        "theme_color": accent,
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {
                "src": "/icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
