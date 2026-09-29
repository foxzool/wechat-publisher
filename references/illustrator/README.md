# Article Illustrator (baoyu method, no text in images, grok-build ready)

Ported from **baoyu-article-illustrator** by 宝玉 (JimLiu), MIT —
<https://github.com/JimLiu/baoyu-skills#baoyu-article-illustrator>, via the Hermes Agent
port (Nous Research, MIT). See [PORT_NOTES.md](PORT_NOTES.md) and [LICENSE.md](LICENSE.md).

Analyze an article, pick illustration slots, write one **prompt file per image**, then
generate each image through `scripts/generate_image.py` (default backend from
`wechat-publisher.yaml`, e.g. `grok-build` — no OpenAI/Gemini key needed).

**House rule for this fork: images contain NO text.** No letters, words, numbers,
Chinese characters, labels, captions, titles, logos, watermarks or signatures. Every
prompt ends with `NO_TEXT_CLAUSE` (`scripts/no_text_guard.py`), and all style /
palette / template fragments are passed through `strip_text_instructions()`.
Put the words in the article; let the picture carry the idea.

## Three dimensions

| Dimension | Controls | Values |
|-----------|----------|--------|
| **Type** | Information structure | `infographic`, `scene`, `flowchart`, `comparison`, `framework`, `timeline` |
| **Style** | Rendering approach | 23 styles in [styles/](styles/) — gallery + Type×Style matrix in [styles.md](styles.md) |
| **Palette** | Color override (optional) | `macaron`, `warm`, `neon`, `mono-ink` in [palettes/](palettes/) |

Or use a **preset** (type + style + palette) from [style-presets.md](style-presets.md),
e.g. `kids-picture-book`, `kids-science`, `edu-visual`, `storytelling`.

Types are text-free here: an *infographic* shows quantities by size / count / bar
length; a *flowchart* is a row of picture panels joined by arrows; a *comparison* is a
split composition whose difference is obvious from imagery alone.

## Workflow

```
1. Analyze   → analysis.md            (content type, sections, existing image slots)
2. Settings  → preset or type/style/palette, density, aspect (default 4:3)
3. Outline   → outline.yaml           (one entry per image: position, alt, visual)
4. Prompts   → prompts/NN-{type}-{slug}.md        record: frontmatter + prompt
               prompts/NN-{type}-{slug}.prompt.txt prompt only (fed to generator)
5. Generate  → generate_image.py --promptfiles … --image DIR/NN-{type}-{slug}.jpg --ar …
6. Finalize  → insert ![中文alt](path) in the article; check each image for stray text
```

Prompt files are the reproducibility record: never generate without one; to change an
image, edit `outline.yaml` (or the prompt), re-run `prompts`, regenerate.

### Commands

```bash
cd /workspace/wechat-publisher
PY=.venv/bin/python

# 1-3: analyze + draft outline (slots = existing ![alt](…) refs, else cover + one per H2)
$PY scripts/build_image_prompts.py outline path/to/article.md \
    --out-dir path/to/illustrations --preset kids-picture-book --density balanced

# Agent step: edit illustrations/outline.yaml — replace each DRAFT `visual` with a
# concrete ENGLISH description of what to draw (subjects, action, setting, mood).
# Describe pictures only. Optional per-item overrides: type, style, palette, aspect,
# output, figures (false = no people), extra, wechat_style.

# 4: prompt files only
$PY scripts/build_image_prompts.py prompts --outline path/to/illustrations/outline.yaml

# 4+5: prompt files + generation (dry-run prints the generate_image.py commands)
$PY scripts/build_image_prompts.py run --outline path/to/illustrations/outline.yaml --dry-run
$PY scripts/build_image_prompts.py run --outline path/to/illustrations/outline.yaml \
    --generator grok-build --jobs 3 [--only 1,3]

$PY scripts/build_image_prompts.py list     # types / styles / palettes / presets
```

`generate` writes `generation.json` (per-image return code + log tail) next to the outline
and retries each failed image once.

### Blending a house style

`--wechat-style <name>` (or `wechat_style:` in the outline) mixes in an
`assets/image-styles/<name>.json` `article_inline` template. The JSON files are **not**
edited (newspic card mode still uses their text instructions); the template is
neutralized at build time (label / lettering / "in Chinese" instructions removed).
`marker-*` styles are pure typography cards and are rejected on this path.

## Core principles (from upstream, adapted)

- **Visualize concepts, not metaphors** — draw the underlying idea, not a literal figure of speech.
- **Pictures, not words** — show relationships with arrows, size, color, grouping and pose.
- **Prompt files are mandatory** — they let you regenerate or switch backends later.
- **Strip secrets** — never copy API keys, tokens or credentials from source text into prompts.
- **Check the output** — even with the clause, models sometimes scribble glyphs; inspect
  every image and regenerate if any text-like marks appear.

## Backend notes (grok-build)

- One agent run per image (~20-45 s); `--jobs 3-6` works in practice.
- No reference-image input, no `n>1`; aspect ratio is a hint (4:3 → 1152×864 observed).
- Content moderation can reject a prompt (e.g. children in a bathtub) — reword and retry.
