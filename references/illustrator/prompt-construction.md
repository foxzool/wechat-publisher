# Prompt Construction (no-text edition)

Adapted from baoyu-article-illustrator `references/prompt-construction.md` (MIT).
Implemented by `scripts/build_image_prompts.py::build_prompt()`.

## Prompt file format

```yaml
---
illustration_id: 1
type: scene
style: watercolor
palette: null
aspect: '4:3'
position: 救护车也会这样
alt: 救护车从身边开过
output: 02-scene-ambulance.jpg
---

[assembled prompt — also saved alone as NN-{type}-{slug}.prompt.txt]
```

Only the `.prompt.txt` body is sent to the generator, so frontmatter (which may contain
the Chinese alt) never reaches the image model.

## Assembly order

1. Header — type description + style name
2. `HOUSE STYLE` — optional neutralized `assets/image-styles` template
3. `VISUAL CONTENT` — the outline's `visual` (concrete English description)
4. Type structure (below)
5. `STYLE` — style summary + design aesthetic
6. `BACKGROUND` — palette background if a palette is set, else the style's
7. `STYLE ELEMENTS` (use only where relevant), `DO`, `AVOID` — from the style file
8. `COLORS` — palette colors replace the style's colors (palette override rule)
9. Color guidance clause, composition clause, human-figure clause
10. `ASPECT`
11. **`NO_TEXT_CLAUSE` — always last**

Every fragment is sanitized by the no-text guard (`scripts/no_text_guard.py`); the final
prompt is re-checked by the same guard and the build aborts if anything slips through.

## Type structures (visual-only)

| Type | Structure |
|------|-----------|
| infographic | Grid / radial / hierarchical arrangement of 3-5 pictorial zones; each zone an icon or object; quantities by size, object count or bar length; semantic colors |
| scene | Focal point, atmosphere (lighting, environment), color temperature matching the mood |
| flowchart | Left-to-right or top-down row of 3-5 picture panels joined by bold arrows; steps differ by icon and color |
| comparison | Split composition with a clear divider; contrasting pictures, colors or poses on each side |
| framework | Hierarchical / network / layered visual nodes joined by lines and arrows |
| timeline | Horizontal or winding path of 3-5 pictorial milestones; progression by changing scenery, size or color |

## Default clauses

- Composition: *Clean composition with generous breathing room. Simple, uncluttered background. Main elements centered or positioned by content needs. Draw only what the visual content describes; do not add unrelated icons, props or objects.*
- Colors: *Color values (#hex) and color names are rendering guidance only; do not display color names, hex codes or palette names in the image.*
- Figures: *Human figures: simplified, stylized cartoon characters, not photorealistic.* (set `figures: false` to omit)
- No text (always last): see `NO_TEXT_CLAUSE` in `scripts/no_text_guard.py`.

## Writing the `visual`

- English, concrete: who / what, doing what, where, mood. One focal idea per image.
- Describe pictures only. Avoid anything that implies writing: signs, books with visible pages, screens with UI, posters, badges, jerseys with numbers, brand names, vehicle markings (say "plain white airplane without markings", "ambulance without writing").
- Physical ideas (sound waves, growth, flow) → shapes, ripples, arrows, color gradients.

## What to avoid

- Vague descriptions ("a nice image")
- Literal metaphor illustrations
- No requests for labels, captions, numbers, callouts, speech-bubble text or watermarks
