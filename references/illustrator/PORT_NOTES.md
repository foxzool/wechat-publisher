# Port Notes — illustrator (baoyu method → wechat-publisher)

## Provenance

- Upstream: [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) —
  `skills/baoyu-article-illustrator` v1.57.0, author 宝玉 (JimLiu), license MIT
  (per upstream SKILL.md frontmatter).
- Intermediate: Hermes Agent port (`optional-skills/creative/baoyu-article-illustrator`,
  Nous Research, MIT). Its PORT_NOTES states the 23 style and 4 palette files are verbatim
  upstream copies.
- This fork: copied from the Hermes port on 2026-09-29.

## What was ported

| Upstream / Hermes | Here | Treatment |
|-------------------|------|-----------|
| `references/styles/*.md` (23) | `styles/*.md` | Sanitized with `no_text_guard.strip_text_instructions()` + manual fixes (see below) |
| `references/palettes/*.md` (4) | `palettes/*.md` | Sanitized; "Text" color roles removed |
| `references/styles.md` | `styles.md` | Sanitized (typography / label bullets removed) |
| `references/style-presets.md` | `style-presets.md` | Sanitized + fork kids presets |
| `references/prompt-construction.md` | `prompt-construction.md` | Rewritten: text-free type templates, NO_TEXT_CLAUSE last |
| `SKILL.md`, `references/workflow.md`, `references/usage.md` | `README.md` | Condensed into one guide wired to `scripts/build_image_prompts.py` |
| `prompts/system.md` | — | Dropped (its "Text Style" / language rules conflict with the no-text rule; remaining guidance lives in the builder clauses) |
| Step 6 `image_generate` / `baoyu-imagine` | `scripts/generate_image.py` | Any configured backend; grok-build by default on the box |
| Step 3 interactive questions | CLI flags / outline.yaml | The calling agent decides settings |

## Text removal (fork policy)

Upstream deliberately puts labels, numbers, quotes and hand-lettered titles into images
("Labels use article data"). This fork forbids any text in images, so:

- Color-table rows whose role is Text / Primary Text / Label Text / Alt Text were removed.
- Bullets / sentences asking for labels, lettering, typography, callouts, captions,
  annotations, speech bubbles, numbered sequences, taglines or watermarks were removed.
- `## Typography` sections (chalkboard) were removed.
- Manual fixes: outline color rows restored for chalkboard / elegant / macaron (their
  removed Text rows also defined outline color); quoted words that could be rendered
  (`"Before" | "After"`, `"coming next"`, `"Mindset shift"`, `"after" state`) rephrased;
  a few sentence fragments left by the sanitizer were rewritten (ink-notes,
  screen-print, scientific).
- `tests/test_illustrator_no_text.py` scans every ported asset plus builder output.

## Syncing with upstream

Re-copy a style/palette file, run it through `strip_text_instructions()`, review the diff
by hand, then run `.venv/bin/python -m pytest tests/test_illustrator_no_text.py`.
