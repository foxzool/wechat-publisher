"""No-text enforcement for the illustrator path (ported baoyu assets + builder)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import build_image_prompts as b
from no_text_guard import (
    NO_TEXT_CLAUSE,
    ensure_no_text_clause,
    find_text_instructions,
    segment_has_text_instruction,
    strip_text_instructions,
)

REPO = Path(__file__).resolve().parent.parent
ILL = REPO / "references" / "illustrator"
PROMPT_ASSETS = sorted(
    [*(ILL / "styles").glob("*.md"), *(ILL / "palettes").glob("*.md"),
     ILL / "styles.md", ILL / "style-presets.md", ILL / "prompt-construction.md"]
)
IMAGE_STYLE_JSON = sorted((REPO / "assets" / "image-styles").glob("*.json"))


# --- guard unit behaviour -------------------------------------------------

@pytest.mark.parametrize("s", [
    "Clear visual hierarchy with icons and labels",
    "Bilingual callout labels (English + Chinese)",
    "Hand-drawn chalk lettering style",
    "Bold hand-lettered headings",
    "Add a bottom tagline summarizing the takeaway",
    "Include a subtle watermark in the corner",
    "Numbered step sequences",
    "Generate an infographic in Chinese",
    "画面加上中文标签",
])
def test_positive_text_requests_are_detected(s):
    assert segment_has_text_instruction(s)


@pytest.mark.parametrize("s", [
    "Subtle paper texture with visible grain",
    "No text, no letters, no numbers",
    "Do NOT render color names, hex codes, or role labels as visible text in the image.",
    "Soft watercolor washes and organic shapes",
    NO_TEXT_CLAUSE,
])
def test_negated_or_unrelated_is_allowed(s):
    assert not segment_has_text_instruction(s)


def test_strip_removes_rows_bullets_sections_and_parentheticals():
    md = (
        "## Typography\n\nHand-drawn chalk lettering.\n\n## Colors\n\n"
        "| Role | Color | Hex | Usage |\n|---|---|---|---|\n"
        "| Primary Text | Black | #000 | Headlines |\n"
        "| Primary | Near Black | #111 | All lines, text, figures |\n\n"
        "- Handwritten labels and notes\n- Soft shading\n"
        "Bold headings (hand-written, not printed sans-serif). Calm mood.\n"
    )
    out = strip_text_instructions(md)
    assert "Typography" not in out and "lettering" not in out
    assert "Primary Text" not in out
    assert "| All lines, figures |" in out
    assert "Handwritten" not in out and "- Soft shading" in out
    assert "sans-serif" not in out and "Calm mood." in out
    assert find_text_instructions(out) == []


def test_ensure_clause_appends_once_at_end():
    p = ensure_no_text_clause(f"hello\n\n{NO_TEXT_CLAUSE}\n\nworld")
    assert p.count(NO_TEXT_CLAUSE) == 1
    assert p.rstrip().endswith(NO_TEXT_CLAUSE)


# --- ported assets --------------------------------------------------------

@pytest.mark.parametrize("path", PROMPT_ASSETS, ids=lambda p: p.relative_to(ILL).as_posix())
def test_ported_prompt_assets_contain_no_text_instructions(path):
    offenders = find_text_instructions(path.read_text(encoding="utf-8"))
    assert offenders == [], f"{path.name}: {offenders}"


def test_all_upstream_styles_and_palettes_ported():
    assert len(list((ILL / "styles").glob("*.md"))) == 23
    assert {p.stem for p in (ILL / "palettes").glob("*.md")} == {"macaron", "warm", "neon", "mono-ink"}


def test_attribution_present():
    notes = (ILL / "PORT_NOTES.md").read_text(encoding="utf-8")
    lic = (ILL / "LICENSE.md").read_text(encoding="utf-8")
    assert "JimLiu" in notes and "MIT" in notes
    assert "Nous Research" in lic and "Permission is hereby granted" in lic


def test_presets_doc_matches_builder():
    doc = (ILL / "style-presets.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z0-9-]+)` \| `", doc, flags=re.M))
    assert documented == set(b.PRESETS)
    for name, p in b.PRESETS.items():
        assert p["type"] in b.TYPES
        b.resolve_style_name(p["style"])
        if p["palette"]:
            b.load_palette(p["palette"])


# --- builder output -------------------------------------------------------

def _check_prompt(prompt: str):
    assert prompt.rstrip().endswith(NO_TEXT_CLAUSE)
    assert find_text_instructions(prompt) == [], find_text_instructions(prompt)


@pytest.mark.parametrize("style", b.list_styles())
@pytest.mark.parametrize("type_name", sorted(b.TYPES))
def test_every_type_style_combo_is_text_free(style, type_name):
    _check_prompt(b.build_prompt("A child watching a kite in the park.", type_name, style))


@pytest.mark.parametrize("palette", b.list_palettes())
def test_palette_override_is_text_free_and_applied(palette):
    p = b.build_prompt("Two jars side by side.", "comparison", "vector-illustration", palette)
    _check_prompt(p)
    assert f"palette override: {palette}" in p


@pytest.mark.parametrize("path", IMAGE_STYLE_JSON, ids=lambda p: p.stem)
def test_wechat_image_styles_are_neutralized_on_new_path(path):
    name = path.stem
    if name.startswith("marker-"):
        with pytest.raises(SystemExit):
            b.wechat_style_fragment(name, "subject")
        return
    frag = b.wechat_style_fragment(name, "a toy car on a road")
    assert find_text_instructions(frag) == [], (name, find_text_instructions(frag))
    _check_prompt(b.build_prompt("a toy car on a road", "scene", "warm", wechat_style=name))


def test_image_style_json_untouched_for_newspic_mode():
    # neutralization happens at build time; newspic templates keep their text on purpose
    hdb = json.loads((REPO / "assets/image-styles/hand-drawn-blue.json").read_text(encoding="utf-8"))
    assert "Chinese labels" in hdb["prompt_template"]["newspic_card"]


def test_text_requests_inside_visual_are_stripped():
    p = b.build_prompt("A girl reading under a tree. Add labels under each item.", "scene", "warm")
    _check_prompt(p)
    assert "A girl reading under a tree." in p
    assert "labels under" not in p
