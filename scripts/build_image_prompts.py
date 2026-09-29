#!/usr/bin/env python3
"""
baoyu article-illustrator method, ported for wechat-publisher (text-free edition).

Type x Style x Palette  ->  outline  ->  per-image prompt files  ->  generate_image.py

Method and style/palette presets are adapted from baoyu-article-illustrator
(宝玉 / JimLiu, MIT) via the Hermes Agent port (Nous Research, MIT). See
references/illustrator/PORT_NOTES.md.

Unlike upstream, every image is TEXT-FREE: no labels, captions, numbers or
lettering. Each prompt ends with no_text_guard.NO_TEXT_CLAUSE and every style,
palette or template fragment passes through no_text_guard.strip_text_instructions.

Workflow (the agent edits outline.yaml between steps 1 and 2):

  1. outline   python3 scripts/build_image_prompts.py outline ARTICLE.md --out-dir DIR \
                   [--preset kids-picture-book | --type scene --style watercolor --palette warm]
               -> DIR/analysis.md + DIR/outline.yaml (one entry per image slot,
                  'visual' is a DRAFT the agent should rewrite in concrete English)
  2. prompts   python3 scripts/build_image_prompts.py prompts --outline DIR/outline.yaml
               -> DIR/prompts/NN-{type}-{slug}.md       (record: frontmatter + prompt)
                  DIR/prompts/NN-{type}-{slug}.prompt.txt (prompt only, fed to the generator)
  3. generate  python3 scripts/build_image_prompts.py generate --outline DIR/outline.yaml \
                   [--generator grok-build] [--jobs 3] [--only 1,3] [--dry-run]
               -> runs scripts/generate_image.py --promptfiles <prompt.txt> per image

  run = prompts + generate.   list = show types / styles / palettes / presets.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from no_text_guard import (  # noqa: E402
    NO_TEXT_CLAUSE,
    ensure_no_text_clause,
    find_text_instructions,
    strip_text_instructions,
)

REPO_ROOT = SCRIPT_DIR.parent
ILLUSTRATOR_DIR = REPO_ROOT / "references" / "illustrator"
STYLES_DIR = ILLUSTRATOR_DIR / "styles"
PALETTES_DIR = ILLUSTRATOR_DIR / "palettes"
GENERATE_IMAGE = SCRIPT_DIR / "generate_image.py"

DEFAULT_ASPECT = "4:3"

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

TYPES: Dict[str, str] = {
    "infographic": "Visual explainer: ideas shown as icons, objects and proportions",
    "scene": "Atmospheric narrative scene",
    "flowchart": "Process shown as a sequence of pictures joined by arrows",
    "comparison": "Side-by-side visual contrast",
    "framework": "Concept structure shown as connected visual nodes",
    "timeline": "Progression shown as a path of pictorial milestones",
}

# Type-specific structure lines (text-free versions of the upstream templates).
TYPE_STRUCTURE: Dict[str, List[str]] = {
    "infographic": [
        "LAYOUT: grid, radial or hierarchical arrangement of 3-5 pictorial zones.",
        "Each zone is a simple icon or object; show quantities by size, count of objects or bar length only.",
        "Semantic colors carry meaning (warm = attention, green = good, blue = calm).",
    ],
    "scene": [
        "FOCAL POINT: the main subject described above, clearly readable at a glance.",
        "ATMOSPHERE: lighting, environment and mood that support the story.",
        "COLOR TEMPERATURE: match the mood (warm for cozy, cool for calm).",
    ],
    "flowchart": [
        "LAYOUT: left-to-right (or top-down) sequence of 3-5 picture panels.",
        "Each step is shown as a small pictorial vignette; bold arrows connect the steps.",
        "Steps are distinguished by icon and color, never by words.",
    ],
    "comparison": [
        "LAYOUT: split composition, left side vs right side, with a clear visual divider.",
        "Each side shows its idea with contrasting pictures, colors or poses.",
        "The difference must be obvious from imagery alone.",
    ],
    "framework": [
        "STRUCTURE: hierarchical, network or layered arrangement of visual nodes.",
        "Nodes are simple icons or objects; relationships are shown with connecting lines and arrows.",
    ],
    "timeline": [
        "DIRECTION: a horizontal (or winding) path with 3-5 pictorial milestones.",
        "Progression is shown by changing scenery, size or color along the path.",
    ],
}

# Core style aliases (upstream "Core Styles").
CORE_STYLES: Dict[str, str] = {
    "vector": "vector-illustration",
    "minimal-flat": "notion",
    "sci-fi": "blueprint",
    "hand-drawn": "sketch",
    "editorial": "editorial",
    "scene": "warm",
    "poster": "screen-print",
}

# Presets: type + style + palette (upstream style-presets.md + fork additions).
PRESETS: Dict[str, Dict[str, Optional[str]]] = {
    "tech-explainer": {"type": "infographic", "style": "blueprint", "palette": None},
    "system-design": {"type": "framework", "style": "blueprint", "palette": None},
    "architecture": {"type": "framework", "style": "vector-illustration", "palette": None},
    "science-paper": {"type": "infographic", "style": "scientific", "palette": None},
    "knowledge-base": {"type": "infographic", "style": "vector-illustration", "palette": None},
    "saas-guide": {"type": "infographic", "style": "notion", "palette": None},
    "tutorial": {"type": "flowchart", "style": "vector-illustration", "palette": None},
    "process-flow": {"type": "flowchart", "style": "notion", "palette": None},
    "warm-knowledge": {"type": "infographic", "style": "vector-illustration", "palette": "warm"},
    "edu-visual": {"type": "infographic", "style": "vector-illustration", "palette": "macaron"},
    "hand-drawn-edu": {"type": "flowchart", "style": "sketch-notes", "palette": "macaron"},
    "ink-notes-compare": {"type": "comparison", "style": "ink-notes", "palette": "mono-ink"},
    "ink-notes-flow": {"type": "flowchart", "style": "ink-notes", "palette": "mono-ink"},
    "ink-notes-framework": {"type": "framework", "style": "ink-notes", "palette": "mono-ink"},
    "data-report": {"type": "infographic", "style": "editorial", "palette": None},
    "versus": {"type": "comparison", "style": "vector-illustration", "palette": None},
    "business-compare": {"type": "comparison", "style": "elegant", "palette": None},
    "storytelling": {"type": "scene", "style": "warm", "palette": None},
    "lifestyle": {"type": "scene", "style": "watercolor", "palette": None},
    "history": {"type": "timeline", "style": "elegant", "palette": None},
    "evolution": {"type": "timeline", "style": "warm", "palette": None},
    "opinion-piece": {"type": "scene", "style": "screen-print", "palette": None},
    "editorial-poster": {"type": "comparison", "style": "screen-print", "palette": None},
    "cinematic": {"type": "scene", "style": "screen-print", "palette": None},
    # --- fork additions (kids / family accounts) ---
    "kids-picture-book": {"type": "scene", "style": "watercolor", "palette": None},
    "kids-storybook": {"type": "scene", "style": "fantasy-animation", "palette": None},
    "kids-science": {"type": "comparison", "style": "flat-doodle", "palette": "macaron"},
}

DENSITY_LIMITS = {"minimal": 2, "balanced": 5, "per-section": None, "rich": None}

# wechat image-styles whose whole design is typography (punchline cards).
TEXT_ONLY_WECHAT_STYLES_PREFIX = ("marker-",)

COMPOSITION_CLAUSE = (
    "Clean composition with generous breathing room. Simple, uncluttered background. "
    "Main elements centered or positioned by content needs. "
    "Draw only what the visual content describes; do not add unrelated icons, props or objects."
)
COLOR_GUIDANCE_CLAUSE = (
    "Color values (#hex) and color names are rendering guidance only; "
    "do not display color names, hex codes or palette names in the image."
)
FIGURE_CLAUSE = "Human figures: simplified, stylized cartoon characters, not photorealistic."

# ---------------------------------------------------------------------------
# Markdown spec parsing
# ---------------------------------------------------------------------------


def _sections(md: str) -> Dict[str, str]:
    """Map lower-cased heading text -> body (for ## and ### headings)."""
    out: Dict[str, str] = {}
    current = "_intro"
    buf: List[str] = []
    for line in md.splitlines():
        m = re.match(r"^#{2,3}\s+(.*)$", line)
        if m:
            out[current] = "\n".join(buf).strip()
            current = m.group(1).strip().lower()
            buf = []
        else:
            buf.append(line)
    out[current] = "\n".join(buf).strip()
    return out


def _bullets(body: str) -> List[str]:
    return [re.sub(r"^\s*[-*+]\s+", "", l).strip() for l in body.splitlines() if re.match(r"^\s*[-*+]\s+", l)]


def _table_colors(body: str) -> List[str]:
    colors = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.match(r"#[0-9A-Fa-f]{3,8}", cells[2]):
            continue
        role, name, hexv = cells[0], cells[1], cells[2]
        usage = cells[3] if len(cells) > 3 else ""
        colors.append(f"{role}: {name} ({hexv})" + (f" for {usage.lower()}" if usage and usage != "—" else ""))
    return colors


def _first_paragraph(body: str) -> str:
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if para and not para.startswith(("|", "-", "#")):
            return " ".join(para.split())
    return ""


@dataclass
class StyleSpec:
    name: str
    summary: str = ""
    aesthetic: str = ""
    background: List[str] = field(default_factory=list)
    colors: List[str] = field(default_factory=list)
    elements: List[str] = field(default_factory=list)
    do: List[str] = field(default_factory=list)
    dont: List[str] = field(default_factory=list)


@dataclass
class PaletteSpec:
    name: str
    background: List[str] = field(default_factory=list)
    colors: List[str] = field(default_factory=list)
    constraint: str = ""


def list_styles() -> List[str]:
    return sorted(p.stem for p in STYLES_DIR.glob("*.md"))


def list_palettes() -> List[str]:
    return sorted(p.stem for p in PALETTES_DIR.glob("*.md"))


def resolve_style_name(name: str) -> str:
    name = CORE_STYLES.get(name, name)
    if name not in list_styles():
        raise SystemExit(f"未知 style: {name}. 可选: {', '.join(list_styles())}")
    return name


def load_style(name: str) -> StyleSpec:
    name = resolve_style_name(name)
    md = strip_text_instructions((STYLES_DIR / f"{name}.md").read_text(encoding="utf-8"))
    sec = _sections(md)
    intro_lines = [l for l in sec.get("_intro", "").splitlines() if l.strip() and not l.startswith("#")]
    return StyleSpec(
        name=name,
        summary=intro_lines[0].strip() if intro_lines else "",
        aesthetic=_first_paragraph(sec.get("design aesthetic", "")),
        background=_bullets(sec.get("background", "")),
        colors=_table_colors(sec.get("color palette", "")),
        elements=_bullets(sec.get("visual elements", "")),
        do=_bullets(sec.get("do", "")),
        dont=_bullets(sec.get("don't", "")),
    )


def load_palette(name: str) -> PaletteSpec:
    if name not in list_palettes():
        raise SystemExit(f"未知 palette: {name}. 可选: {', '.join(list_palettes())}")
    md = strip_text_instructions((PALETTES_DIR / f"{name}.md").read_text(encoding="utf-8"))
    sec = _sections(md)
    return PaletteSpec(
        name=name,
        background=_bullets(sec.get("background", "")),
        colors=_table_colors(sec.get("colors", "")),
        constraint=" ".join(
            x for x in (_first_paragraph(sec.get("accent", "")), _first_paragraph(sec.get("semantic constraint", ""))) if x
        ),
    )


# ---------------------------------------------------------------------------
# wechat assets/image-styles/*.json bridge (neutralized, JSON left untouched)
# ---------------------------------------------------------------------------


def wechat_style_fragment(style_name: str, subject: str) -> str:
    """Return a text-free version of an image-styles JSON article_inline template.

    The JSON files are NOT modified (newspic card mode still needs their text
    instructions); neutralization happens here, at prompt-build time.
    """
    if style_name.startswith(TEXT_ONLY_WECHAT_STYLES_PREFIX):
        raise SystemExit(
            f"image-style '{style_name}' 是纯文字卡片风格(整张图就是文字),不能用于无文字配图路径"
        )
    from config import get_image_style  # local import: config needs pyyaml only

    style = get_image_style(style_name)
    tmpl = (style.get("prompt_template") or {}).get("article_inline", "")
    t = tmpl.replace("{image_subject}", subject).replace("{card_main}", subject).replace("{topic}", subject)
    t = re.sub(r"\s+in Chinese\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bChinese\s+(?=[a-z-]*\s*(?:illustration|infographic|cartoon|scene|knowledge-card))", "", t, flags=re.IGNORECASE)
    t = re.sub(r"handwritten[- ]notebook", "notebook", t, flags=re.IGNORECASE)
    t = re.sub(r",?\s*\b(?:16:9|4:3|1:1|3:4|9:16)(?:\s+landscape)?\s*[,.]?", ".", t)
    t = re.sub(r"^\.\s*", "", re.sub(r"\.\s*\.", ".", t)).replace(". ,", ".")
    return strip_text_instructions(t).strip()


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _as_avoid(item: str) -> str:
    """'Use sharp geometric shapes' -> 'sharp geometric shapes' (reads well after AVOID:)."""
    return re.sub(r"^(?:use|create|add|include|make|leave|apply)\s+", "", item.strip(), flags=re.IGNORECASE)


def build_prompt(
    visual: str,
    type_name: str,
    style_name: str,
    palette_name: Optional[str] = None,
    aspect: str = DEFAULT_ASPECT,
    figures: bool = True,
    wechat_style: Optional[str] = None,
    extra: Optional[str] = None,
) -> str:
    if type_name not in TYPES:
        raise SystemExit(f"未知 type: {type_name}. 可选: {', '.join(TYPES)}")
    style = load_style(style_name)
    palette = load_palette(palette_name) if palette_name else None

    parts: List[str] = []
    parts.append(f"{TYPES[type_name]} — {style.name} style illustration.")
    if wechat_style:
        frag = wechat_style_fragment(wechat_style, visual)
        if frag:
            parts.append(f"HOUSE STYLE ({wechat_style}): {frag}")
    parts.append(f"VISUAL CONTENT:\n{visual.strip()}")
    parts.append("\n".join(TYPE_STRUCTURE[type_name]))

    style_lines = [x.rstrip(". ") + "." for x in (style.summary, style.aesthetic) if x]
    if style_lines:
        parts.append("STYLE: " + " ".join(style_lines))
    bg = palette.background if palette and palette.background else style.background
    if bg:
        parts.append("BACKGROUND: " + "; ".join(bg))
    if style.elements:
        parts.append(
            "STYLE ELEMENTS (rendering vocabulary; use only where they fit the visual content): "
            + "; ".join(style.elements)
        )
    if style.do:
        parts.append("DO: " + "; ".join(style.do))
    if style.dont:
        parts.append("AVOID: " + "; ".join(_as_avoid(x) for x in style.dont))
    colors = palette.colors if palette and palette.colors else style.colors
    if colors:
        head = f"COLORS (palette override: {palette.name}): " if palette else "COLORS: "
        parts.append(head + "; ".join(colors))
        if palette and palette.constraint:
            parts.append(palette.constraint)
        parts.append(COLOR_GUIDANCE_CLAUSE)
    parts.append(COMPOSITION_CLAUSE)
    if figures:
        parts.append(FIGURE_CLAUSE)
    if extra:
        parts.append(extra.strip())
    parts.append(f"ASPECT: {aspect}")

    body = strip_text_instructions("\n\n".join(parts))
    prompt = ensure_no_text_clause(body)
    leftovers = find_text_instructions(prompt)
    if leftovers:
        raise SystemExit("prompt 仍含文字类指令,已中止: " + " | ".join(leftovers))
    return prompt


# ---------------------------------------------------------------------------
# Article analysis & outline
# ---------------------------------------------------------------------------

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _read_article(path: Path) -> tuple[Dict, str]:
    text = path.read_text(encoding="utf-8")
    fm: Dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = yaml.safe_load(text[3:end]) or {}
            text = text[end + 4 :]
    return fm, text


def _slugify(value: str, fallback: str) -> str:
    value = re.sub(r"^\d+[-_]?", "", value)
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or fallback


def analyze_article(path: Path) -> Dict:
    fm, body = _read_article(path)
    title = fm.get("title") or ""
    sections: List[Dict] = []
    heading = "(intro)"
    slots: List[Dict] = []
    paragraph_buf: List[str] = []
    for line in body.splitlines():
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            if len(h.group(1)) == 1 and not title:
                title = h.group(2).strip()
            if len(h.group(1)) >= 2:
                heading = h.group(2).strip()
                sections.append({"heading": heading, "text": ""})
            paragraph_buf = []
            continue
        for m in _IMG_RE.finditer(line):
            slots.append(
                {
                    "position": heading,
                    "alt": m.group(1).strip(),
                    "existing": m.group(2),
                    "context": " ".join(paragraph_buf)[-300:],
                }
            )
        stripped = _IMG_RE.sub("", line).strip()
        if stripped:
            paragraph_buf.append(stripped)
            if sections:
                sections[-1]["text"] = (sections[-1]["text"] + " " + stripped).strip()
    return {"title": title, "frontmatter": fm, "sections": sections, "image_slots": slots}


def make_outline(
    article: Path,
    out_dir: Path,
    type_name: str,
    style_name: str,
    palette_name: Optional[str],
    preset: Optional[str],
    aspect: str,
    density: str,
    wechat_style: Optional[str] = None,
) -> Dict:
    info = analyze_article(article)
    slots = info["image_slots"]
    if not slots:  # no image refs: cover + one per section
        slots = [{"position": "cover", "alt": info["title"], "existing": None, "context": ""}]
        for s in info["sections"]:
            slots.append({"position": s["heading"], "alt": s["heading"], "existing": None, "context": s["text"][:300]})
    limit = DENSITY_LIMITS.get(density)
    if limit:
        slots = slots[:limit]

    items = []
    for i, s in enumerate(slots, 1):
        stem = Path(s["existing"]).stem if s.get("existing") else ("cover" if s["position"] == "cover" else "")
        slug = _slugify(stem, f"img{i}")
        items.append(
            {
                "id": i,
                "slug": slug,
                "type": type_name,
                "position": s["position"],
                "alt": s["alt"],
                "purpose": "illustrate this section for the reader",
                "context": s["context"],
                "visual": f"DRAFT: rewrite in concrete English. Picture for section '{s['position']}' ({s['alt']}).",
                "draft": True,
            }
        )
    outline = {
        "article": str(article.resolve()),
        "title": info["title"],
        "preset": preset,
        "type": type_name,
        "style": style_name,
        "palette": palette_name,
        "wechat_style": wechat_style,
        "aspect": aspect,
        "density": density,
        "image_count": len(items),
        "illustrations": items,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "outline.yaml").write_text(
        yaml.safe_dump(outline, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    lines = [
        f"# Analysis — {info['title']}",
        "",
        f"- Article: `{article}`",
        f"- Sections: {len(info['sections'])}",
        f"- Existing image slots: {len(info['image_slots'])}",
        f"- Settings: preset={preset or '-'} type={type_name} style={style_name} palette={palette_name or 'default'} aspect={aspect} density={density}",
        "",
        "## Sections",
        *[f"- {s['heading']}" for s in info["sections"]],
        "",
        "Next: edit `outline.yaml` — replace every DRAFT `visual` with a concrete English",
        "description of what to draw (subjects, action, setting, mood). Describe pictures only;",
        "never ask for words, labels or numbers. Then run `prompts` and `generate`.",
    ]
    (out_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return outline


# ---------------------------------------------------------------------------
# Prompt files & generation
# ---------------------------------------------------------------------------


def _load_outline(path: Path) -> Dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("illustrations"):
        raise SystemExit(f"{path} 没有 illustrations")
    return data


def _base_name(item: Dict, default_type: str) -> str:
    return f"{int(item['id']):02d}-{item.get('type') or default_type}-{item['slug']}"


def write_prompt_files(outline_path: Path) -> List[Dict]:
    outline = _load_outline(outline_path)
    out_dir = outline_path.parent
    pdir = out_dir / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    written = []
    for item in outline["illustrations"]:
        t = item.get("type") or outline["type"]
        visual = str(item.get("visual") or "").strip()
        if not visual:
            raise SystemExit(f"illustration {item['id']} 缺少 visual")
        if item.get("draft") or visual.startswith("DRAFT"):
            print(f"警告: illustration {item['id']} 的 visual 仍是草稿", file=sys.stderr)
        if _CJK_RE.search(visual):
            print(f"警告: illustration {item['id']} 的 visual 含中文,建议改用英文描述以免模型把字画进图里", file=sys.stderr)
        prompt = build_prompt(
            visual,
            t,
            item.get("style") or outline["style"],
            item.get("palette", outline.get("palette")),
            aspect=str(item.get("aspect") or outline.get("aspect") or DEFAULT_ASPECT),
            figures=item.get("figures", True),
            wechat_style=item.get("wechat_style", outline.get("wechat_style")),
            extra=item.get("extra"),
        )
        base = _base_name(item, outline["type"])
        output = item.get("output") or f"{base}.jpg"
        fm = {
            "illustration_id": int(item["id"]),
            "type": t,
            "style": resolve_style_name(item.get("style") or outline["style"]),
            "palette": item.get("palette", outline.get("palette")),
            "aspect": str(item.get("aspect") or outline.get("aspect") or DEFAULT_ASPECT),
            "position": item.get("position"),
            "alt": item.get("alt"),
            "output": output,
        }
        record = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + prompt
        (pdir / f"{base}.md").write_text(record, encoding="utf-8")
        (pdir / f"{base}.prompt.txt").write_text(prompt, encoding="utf-8")
        written.append(
            {
                "id": int(item["id"]),
                "prompt_file": str(pdir / f"{base}.prompt.txt"),
                "record": str(pdir / f"{base}.md"),
                "output": str((out_dir / output).resolve()),
                "aspect": fm["aspect"],
                "alt": item.get("alt"),
            }
        )
    return written


def generate_command(job: Dict, generator: Optional[str], account: Optional[str], dry_run: bool) -> List[str]:
    cmd = [sys.executable, str(GENERATE_IMAGE), "--promptfiles", job["prompt_file"], "--image", job["output"], "--ar", job["aspect"]]
    if generator:
        cmd += ["--generator", generator]
    if account:
        cmd += ["--account", account]
    if dry_run:
        cmd.append("--print-command")
    return cmd


def run_generation(
    jobs: List[Dict],
    generator: Optional[str] = None,
    account: Optional[str] = None,
    parallel: int = 1,
    dry_run: bool = False,
    retries: int = 1,
) -> List[Dict]:
    def _one(job: Dict) -> Dict:
        cmd = generate_command(job, generator, account, dry_run)
        last = None
        for attempt in range(retries + 1):
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            last = proc
            if proc.returncode == 0:
                break
            print(f"[illustrate] #{job['id']} attempt {attempt + 1} failed", file=sys.stderr)
        tail = ((last.stdout or "") + (last.stderr or ""))[-600:]
        return {**job, "returncode": last.returncode, "log_tail": tail, "command": cmd}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        results = list(ex.map(_one, jobs))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_dims(args) -> tuple[str, str, Optional[str], Optional[str]]:
    preset = getattr(args, "preset", None)
    t, s, p = "scene", "warm", None
    if preset:
        if preset not in PRESETS:
            raise SystemExit(f"未知 preset: {preset}. 可选: {', '.join(PRESETS)}")
        t, s, p = PRESETS[preset]["type"], PRESETS[preset]["style"], PRESETS[preset]["palette"]
    t = args.type or t
    s = resolve_style_name(args.style or s)
    p = args.palette if args.palette is not None else p
    if p in ("", "none", "default"):
        p = None
    if p:
        load_palette(p)
    return t, s, p, preset


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="baoyu article-illustrator (text-free) → generate_image.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("outline", help="analyze article and write outline.yaml")
    o.add_argument("article")
    o.add_argument("--out-dir", required=True)
    o.add_argument("--preset")
    o.add_argument("--type", choices=sorted(TYPES))
    o.add_argument("--style")
    o.add_argument("--palette")
    o.add_argument("--wechat-style", help="optionally blend an assets/image-styles/<name>.json template (neutralized)")
    o.add_argument("--aspect", default=DEFAULT_ASPECT)
    o.add_argument("--density", default="per-section", choices=sorted(DENSITY_LIMITS))

    for name in ("prompts", "generate", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--outline", required=True)
        if name in ("generate", "run"):
            sp.add_argument("--generator", help="override generator (default: wechat-publisher.yaml)")
            sp.add_argument("--account")
            sp.add_argument("--jobs", type=int, default=1, help="parallel generations")
            sp.add_argument("--only", help="comma-separated illustration ids")
            sp.add_argument("--dry-run", action="store_true", help="print generate_image commands only")

    sub.add_parser("list", help="list types / styles / palettes / presets")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        print("types:", ", ".join(TYPES))
        print("styles:", ", ".join(list_styles()))
        print("core styles:", ", ".join(f"{k}->{v}" for k, v in CORE_STYLES.items()))
        print("palettes:", ", ".join(list_palettes()))
        print("presets:")
        for k, v in PRESETS.items():
            print(f"  {k}: type={v['type']} style={v['style']} palette={v['palette'] or '-'}")
        return 0

    if args.cmd == "outline":
        t, s, p, preset = _resolve_dims(args)
        outline = make_outline(
            Path(args.article), Path(args.out_dir), t, s, p, preset, args.aspect, args.density, args.wechat_style
        )
        print(f"outline: {Path(args.out_dir) / 'outline.yaml'} ({outline['image_count']} illustrations)")
        return 0

    outline_path = Path(args.outline)
    jobs = write_prompt_files(outline_path)
    for j in jobs:
        print(f"prompt: {j['record']}")
    if args.cmd == "prompts":
        return 0

    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}
        jobs = [j for j in jobs if j["id"] in wanted]
    results = run_generation(jobs, args.generator, args.account, args.jobs, args.dry_run)
    failed = 0
    for r in results:
        status = "OK" if r["returncode"] == 0 else f"FAIL({r['returncode']})"
        failed += r["returncode"] != 0
        print(f"[{status}] #{r['id']} -> {r['output']}")
        if args.dry_run or r["returncode"] != 0:
            print("   " + r["log_tail"].strip().replace("\n", "\n   "))
    summary = out = outline_path.parent / "generation.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary: {summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
