#!/usr/bin/env python3
"""
No-text guard for image prompts.

The illustrator path (``scripts/build_image_prompts.py``) must never ask the
image model to draw words. This module provides:

- ``NO_TEXT_CLAUSE``: the canonical clause appended to the END of every prompt.
- ``find_text_instructions(text)``: returns lines/sentences that *positively*
  ask for text, labels, captions, fonts, logos, watermarks, etc. Negated
  mentions ("no labels", "do not render hex codes as text") are allowed.
- ``strip_text_instructions(text)``: removes such instructions (line / sentence
  / table-cell / comma-item level) and drops text-only sections such as
  ``## Typography``. Used to sanitize ported baoyu presets and to neutralize
  ``assets/image-styles/*.json`` templates at prompt-build time (the JSON files
  themselves are left untouched so newspic card mode keeps its text).
- ``ensure_no_text_clause(prompt)``: strips any earlier copy of the clause and
  appends it once at the very end.
"""

from __future__ import annotations

import re
from typing import List

NO_TEXT_CLAUSE = (
    "ABSOLUTELY NO TEXT IN THE IMAGE: no letters, no words, no numbers or digits, "
    "no Chinese characters, no labels, no captions, no titles, no speech-bubble "
    "writing, no signs or signage, no logos, no watermarks, no signatures. "
    "Communicate everything purely through pictures, shapes, colors and composition."
)

# Keywords that indicate an instruction to render text. Word-bounded so that
# "texture", "context", "subtle" etc. do not match.
_KEYWORDS_EN = [
    r"text(?:s)?",
    r"text[- ]?box(?:es)?",
    r"label(?:s|ed|led|ing|ling)?",
    r"lettering",
    r"hand[- ]?letter(?:ed|ing)?",
    r"letters?",
    r"typograph(?:y|ic|ical)",
    r"fonts?",
    r"captions?",
    r"call[- ]?outs?",
    r"handwrit(?:ten|ing)",
    r"hand[- ]writ(?:ten|ing)",
    r"headings?",
    r"headlines?",
    r"titles?",
    r"subtitles?",
    r"quotes?",
    r"pull[- ]quotes?",
    r"numbered",
    r"numbers?",
    r"numerals?",
    r"digits?",
    r"annotat(?:e|ed|es|ion|ions)",
    r"taglines?",
    r"keywords?",
    r"slogans?",
    r"watermarks?",
    r"logos?",
    r"signage",
    r"signatures?",
    r"bilingual",
    r"speech[- ]bubbles?",
    r"word(?:s|ing)?",
    r"monospace",
    r"sans[- ]serif",
    r"serif",
    r"punchlines?",
    r"calligraph(?:y|ic)",
    r"in chinese",
    r"in english",
    r"chinese (?:type|script|characters?|glyphs?)",
    r"glyphs?",
]
_KEYWORDS_ZH = ["文字", "标签", "标注", "字体", "手写", "标题", "中文字", "汉字", "水印", "字样"]

KEYWORD_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(_KEYWORDS_EN) + r")(?![A-Za-z])|" + "|".join(_KEYWORDS_ZH),
    re.IGNORECASE,
)

# Negation cues. A keyword preceded (in the same sentence/clause) by one of these
# is treated as a prohibition, which is allowed.
NEGATION_RE = re.compile(
    r"(?<![A-Za-z])(?:no|not|never|without|avoid|avoids|avoiding|free of|zero|none|"
    r"don't|do not|does not|must not|nor|instead of|rather than)(?![A-Za-z])|不要|禁止|不得|无|没有",
    re.IGNORECASE,
)

_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?;。！？；])\s+|\n")


def _is_negated(segment: str, match_start: int) -> bool:
    return bool(NEGATION_RE.search(segment[:match_start]))


def segment_has_text_instruction(segment: str) -> bool:
    """True if ``segment`` contains a non-negated text keyword."""
    for m in KEYWORD_RE.finditer(segment):
        if not _is_negated(segment, m.start()):
            return True
    return False


def find_text_instructions(text: str) -> List[str]:
    """Return offending sentences (positive requests for text-like content)."""
    offenders: List[str] = []
    body = text.replace(NO_TEXT_CLAUSE, "")
    for seg in _CLAUSE_SPLIT_RE.split(body):
        seg = seg.strip()
        if seg and segment_has_text_instruction(seg):
            offenders.append(seg)
    return offenders


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TEXT_SECTION_RE = re.compile(r"typograph|text style|lettering|fonts?\b|labels?\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$")
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")
_PAREN_RE = re.compile(r"\s*[(（][^()（）]*[)）]")


def _split_items(content: str) -> List[str]:
    """Split on commas that are not inside parentheses."""
    items, depth, buf = [], 0, []
    for ch in content:
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return items


def _strip_items(content: str) -> str:
    """Drop comma-separated items that ask for text; keep the rest."""
    items = _split_items(content)
    kept = [i for i in items if not segment_has_text_instruction(i)]
    if len(kept) == len(items):
        return content
    return ", ".join(k.strip() for k in kept if k.strip())


def _strip_table_row(line: str) -> str:
    cells = line.strip().strip("|").split("|")
    if re.fullmatch(r"\s*:?-{2,}:?\s*", cells[0] or "") or all(
        re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells
    ):
        return line
    if cells and re.search(r"(?<![A-Za-z])text(?![A-Za-z])|label", cells[0], re.IGNORECASE):
        return ""  # e.g. "| Primary Text | Near Black | #1A1A1A | Headlines |"
    new_cells = []
    for c in cells:
        if segment_has_text_instruction(c):
            c2 = _strip_items(c)
            new_cells.append(f" {c2.strip()} " if c2.strip() else " — ")
        else:
            new_cells.append(c)
    return "|" + "|".join(new_cells) + "|"


def strip_text_instructions(text: str) -> str:
    """Remove every positive instruction to render text; keep everything else."""
    out: List[str] = []
    skip_level = 0
    for line in text.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and _TEXT_SECTION_RE.search(h.group(2)):
                skip_level = level
                continue
            if not skip_level:
                out.append(line)
            continue
        if skip_level:
            continue
        stripped = line.strip()
        if not stripped or NO_TEXT_CLAUSE in line:
            out.append(line)
            continue
        if stripped.startswith("|"):
            row = _strip_table_row(line)
            if row:
                out.append(row)
            continue
        b = _BULLET_RE.match(line)
        if b:
            content = b.group(2)
            if segment_has_text_instruction(content):
                content = _strip_items(content)
                if not content.strip() or segment_has_text_instruction(content):
                    continue
            out.append(b.group(1) + content)
            continue
        # Drop parentheticals that ask for text, e.g. "(hand-written, not printed)".
        line = _PAREN_RE.sub(
            lambda m: "" if segment_has_text_instruction(m.group(0)) else m.group(0), line
        )
        sentences = _SENTENCE_RE.split(line)
        kept = []
        for s in sentences:
            if not segment_has_text_instruction(s):
                kept.append(s)
                continue
            s2 = _strip_items(s)
            if s2.strip() and not segment_has_text_instruction(s2):
                kept.append(s2 if s2.rstrip().endswith((".", "。")) else s2.rstrip() + ".")
        if kept:
            out.append(" ".join(kept))
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


def ensure_no_text_clause(prompt: str) -> str:
    """Remove earlier copies of the clause and append it once at the end."""
    body = prompt.replace(NO_TEXT_CLAUSE, "").rstrip()
    return f"{body}\n\n{NO_TEXT_CLAUSE}\n"
