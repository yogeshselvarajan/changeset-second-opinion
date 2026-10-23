"""Workspace rules: contrast, wording, the logo sanitiser and the manifest."""

from __future__ import annotations

import pytest

from cso.domain.config import CommunityConfig
from cso.domain.workspace import (
    DARK_CANVAS,
    LIGHT_CANVAS,
    LOGO_MAX_BYTES,
    LogoRejected,
    accent_contrast,
    check_accent,
    check_text,
    contrast_ratio,
    derive_dark_accent,
    manifest_for,
    sanitize_logo,
    settings_hash,
)

SVG = 'xmlns="http://www.w3.org/2000/svg"'
GOOD = (
    f'<svg {SVG} viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8" fill="#4E5BD8"/></svg>'
)


def test_contrast_follows_the_wcag_definition() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert contrast_ratio("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)


def test_the_brand_accent_passes_and_its_dark_variant_is_derived() -> None:
    light, dark = accent_contrast("#4E5BD8")
    assert light >= 4.5 and dark >= 4.5
    assert check_accent("#4E5BD8") == []
    assert derive_dark_accent("#4E5BD8") != "#4E5BD8"
    assert contrast_ratio(LIGHT_CANVAS, DARK_CANVAS) > 15


def test_no_single_colour_reads_at_4_5_on_both_canvases() -> None:
    """Why the rule asks for the light canvas only: scan every grey, it cannot be met twice."""
    both = [
        v
        for v in range(256)
        if contrast_ratio(f"#{v:02X}{v:02X}{v:02X}", LIGHT_CANVAS) >= 4.5
        and contrast_ratio(f"#{v:02X}{v:02X}{v:02X}", DARK_CANVAS) >= 4.5
    ]
    assert both == []


@pytest.mark.parametrize("value", ["", "red", "#12", "#GGGGGG", "4E5BD8", "#4E5BD8FF"])
def test_a_malformed_accent_is_refused(value: str) -> None:
    assert [p.field for p in check_accent(value)] == ["accent_hex"]


def test_an_accent_too_pale_for_the_light_canvas_is_refused() -> None:
    for pale in ("#F0F0F0", "#808080", "#8E98F2"):
        problems = check_accent(pale)
        assert problems and "light canvas" in problems[0].message
    assert check_accent("#101010") == []  # very dark is fine: the dark theme lightens it


def test_the_derived_dark_variant_always_reads_on_the_dark_canvas() -> None:
    for colour in ("#000000", "#101010", "#4E5BD8", "#B30000", "#006400", "#7A3E00"):
        assert contrast_ratio(derive_dark_accent(colour), DARK_CANVAS) >= 4.5, colour


def test_text_rules_name_the_field_and_never_repeat_the_text() -> None:
    tone = CommunityConfig.load().tone
    assert check_text("name", "A fine name", 48, tone) == []
    long = check_text("name", "x" * 49, 48, tone)
    assert long and long[0].field == "name" and "48" in long[0].message
    assert check_text("tagline", "   ", 120, tone)[0].message == "This cannot be empty."
    banned = check_text("tagline", "We stop vandalism", 120, tone)
    assert banned and all("vandalism" not in p.message for p in banned)


def test_a_plain_logo_is_kept_as_it_was() -> None:
    assert sanitize_logo(GOOD) == GOOD


@pytest.mark.parametrize(
    ("name", "svg", "needle"),
    [
        ("script", f"<svg {SVG}><script>alert(1)</script></svg>", "script"),
        ("onload", f'<svg {SVG} onload="alert(1)"><rect/></svg>', "event handler"),
        ("onclick", f'<svg {SVG}><rect onclick="x()"/></svg>', "event handler"),
        (
            "foreignObject",
            f"<svg {SVG}><foreignObject><div/></foreignObject></svg>",
            "foreignObject",
        ),
        (
            "nested foreignObject",
            f"<svg {SVG}><g><g><foreignObject/></g></g></svg>",
            "foreignObject",
        ),
        ("style element", f"<svg {SVG}><style>*{{fill:red}}</style></svg>", "style"),
        ("use", f"<svg {SVG}><use href='#a'/></svg>", "use"),
        ("image", f"<svg {SVG}><image href='https://x.test/a.png'/></svg>", "image"),
        ("external href", f"<svg {SVG}><a href='https://x.test'><rect/></a></svg>", "<a>"),
        (
            "xlink href",
            f'<svg {SVG} xmlns:xlink="http://www.w3.org/1999/xlink">'
            "<path xlink:href='https://x.test/s.svg'/></svg>",
            "outside itself",
        ),
        ("javascript url", f'<svg {SVG}><rect fill="url(javascript:alert(1))"/></svg>', "script"),
        ("data url", f'<svg {SVG}><rect fill="url(data:text/html,x)"/></svg>', "data"),
        ("unknown element", f"<svg {SVG}><animate attributeName='x'/></svg>", "not allowed"),
        ("not svg", "<html><body/></html>", "SVG"),
        ("not xml", "<svg", "not valid"),
        ("empty", "", "not valid"),
    ],
)
def test_hostile_logos_are_refused(name: str, svg: str, needle: str) -> None:
    with pytest.raises(LogoRejected) as caught:
        sanitize_logo(svg)
    assert needle.lower() in str(caught.value).lower(), name


def test_entity_expansion_and_external_entities_are_refused() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        f"<svg {SVG}><title>&b;&b;&b;&b;</title></svg>"
    )
    external = (
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        f"<svg {SVG}><title>&x;</title></svg>"
    )
    for text in (bomb, external):
        with pytest.raises(LogoRejected) as caught:
            sanitize_logo(text)
        assert "XML feature" in str(caught.value)


def test_a_logo_over_the_size_limit_is_refused() -> None:
    padding = "<!--" + "x" * LOGO_MAX_BYTES + "-->"
    with pytest.raises(LogoRejected, match="larger"):
        sanitize_logo(f"<svg {SVG}>{padding}</svg>")


def test_the_manifest_follows_the_workspace() -> None:
    manifest = manifest_for("Second Opinion Lyon", "#123456")
    assert manifest["name"] == "Second Opinion Lyon"
    assert manifest["short_name"] == "Second Opini"
    assert manifest["theme_color"] == "#123456"
    assert manifest["start_url"] == "/queue"
    assert manifest_for("Short", "#4E5BD8")["short_name"] == "Short"


def test_the_audit_hash_changes_with_the_settings_but_never_holds_the_logo() -> None:
    base = {"name": "A", "logo_svg": GOOD}
    assert settings_hash(base) == settings_hash(dict(base))
    assert settings_hash(base) != settings_hash({**base, "name": "B"})
    assert settings_hash(base) != settings_hash({**base, "logo_svg": GOOD.replace("#4E", "#4F")})
    assert settings_hash({"name": "A", "logo_svg": None}) != settings_hash(base)
    assert GOOD not in settings_hash(base)
