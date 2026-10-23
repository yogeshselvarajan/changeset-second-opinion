"""Neutralize untrusted evidence text before it is rendered for the Decider, drafts or the UI.

Evidence text (comments, tag values, display names) is attacker-controlled data. The sanitizer keeps
it readable for reviewers but inert: no markup, no invisible or direction-changing characters, no
live URLs, bounded length. Nothing is dropped silently; shortened text ends in `...` and the result
reports `truncated`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEFAULT_MAX_LEN = 200
ELLIPSIS = "..."  # ASCII on purpose: NFKC rewrites U+2026, which would break idempotence

# Whitespace-like controls become a space; other control/format/surrogate/private/unassigned
# characters are removed. Category Cf covers the zero-width (U+200B-U+200F, U+FEFF) and bidi
# (U+202A-U+202E, U+2066-U+2069) ranges; Cc covers C0/C1.
_SPACE_LIKE = frozenset("\t\n\r\x0b\x0c\x85  ")
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
# Invisible characters outside the categories above (filler / grapheme joiner).
_INVISIBLE = frozenset("͏ᅟᅠㅤﾠ")

# Quote-like characters other than the ASCII `"` that a reader (or a model) can take for the end of
# a quoted span: curly and low double quotes, guillemets, primes, corner and ornamental quotes.
# They become an apostrophe, which is inert inside the `"..."` spans evidence is rendered in. The
# single angle marks U+2039/U+203A are not listed: they are what `<` and `>` become, and mapping
# them would break idempotence. Fullwidth `＂` is handled by NFKC.
_QUOTE_LIKE = "“”„‟«»″‶❝❞〝〞〟ʺ״ˮ⹂"
_REPLACEMENTS = str.maketrans({"<": "‹", ">": "›", "`": "'", **{ch: "'" for ch in _QUOTE_LIKE}})
# No word boundary: a scheme glued to a preceding word ("xhttp://") must be defanged too.
_URL_SCHEME = re.compile(r"(https?|ftp)://", re.IGNORECASE)
_SCHEME_DEFANG = {"http": "hxxp", "https": "hxxps", "ftp": "fxp"}
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SanitizedText:
    """Sanitized text and whether the per-field cap shortened it."""

    text: str
    truncated: bool = False


def _defang(match: re.Match[str]) -> str:
    return _SCHEME_DEFANG[match.group(1).lower()] + "://"


def sanitize(text: str | None, *, max_len: int = DEFAULT_MAX_LEN) -> SanitizedText:
    """Return `text` normalized, stripped of hidden characters, de-fanged and capped to `max_len`.

    Steps: NFKC; space-like controls to a space; drop control/format/bidi/zero-width characters;
    `<`, `>` and backtick replaced; curly quotes, guillemets and similar quote-like characters
    become an apostrophe; `http(s)://` and `ftp://` rewritten to `hxxp(s)://` and `fxp://`;
    whitespace collapsed; cap with a trailing `...`. Idempotent.
    """
    if max_len <= len(ELLIPSIS):
        raise ValueError(f"max_len must exceed {len(ELLIPSIS)}")
    if not text:
        return SanitizedText("")
    kept: list[str] = []
    for ch in unicodedata.normalize("NFKC", text):
        if ch in _SPACE_LIKE or unicodedata.category(ch) in ("Zl", "Zp"):
            kept.append(" ")
        elif ch in _INVISIBLE or unicodedata.category(ch) in _DROP_CATEGORIES:
            continue
        else:
            kept.append(ch)
    # Re-normalize: removing an invisible character can make a base letter and a combining mark
    # adjacent, which NFKC would compose; the result must be stable under a second pass.
    cleaned = unicodedata.normalize("NFKC", "".join(kept)).translate(_REPLACEMENTS)
    cleaned = _URL_SCHEME.sub(_defang, cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if len(cleaned) > max_len:
        return SanitizedText(cleaned[: max_len - len(ELLIPSIS)].rstrip() + ELLIPSIS, True)
    return SanitizedText(cleaned)


def quoted(value: SanitizedText) -> str:
    """Wrap sanitized text in double quotes, escaping backslashes and quotes."""
    escaped = value.text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
