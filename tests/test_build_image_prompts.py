"""Builder workflow tests: outline -> prompt files -> generate_image commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

import build_image_prompts as b
from no_text_guard import NO_TEXT_CLAUSE

ARTICLE = """---
title: 飞机飞过头顶，声音为什么会变？
author: 77爸爸
---

# 飞机飞过头顶，声音为什么会变？

你好呀！

![听飞机的声音](images/cover.jpg)

## 救护车也会这样

救护车开过来，声音尖尖的。

![救护车从身边开过](images/02-ambulance.jpg)

## 声音像小波浪

小波浪挤得紧紧的。

![挤紧和分开的小波浪](images/03-waves.jpg)
"""


@pytest.fixture
def article(tmp_path):
    p = tmp_path / "a" / "文章.md"
    p.parent.mkdir()
    p.write_text(ARTICLE, encoding="utf-8")
    return p


def test_analyze_finds_existing_image_slots(article):
    info = b.analyze_article(article)
    assert info["title"].startswith("飞机")
    assert [s["alt"] for s in info["image_slots"]] == ["听飞机的声音", "救护车从身边开过", "挤紧和分开的小波浪"]
    assert info["image_slots"][1]["position"] == "救护车也会这样"


def test_outline_uses_preset_and_density(article, tmp_path):
    out = tmp_path / "ill"
    assert b.main(["outline", str(article), "--out-dir", str(out), "--preset", "kids-picture-book", "--density", "minimal"]) == 0
    data = yaml.safe_load((out / "outline.yaml").read_text(encoding="utf-8"))
    assert (data["type"], data["style"], data["palette"]) == ("scene", "watercolor", None)
    assert [i["slug"] for i in data["illustrations"]] == ["cover", "ambulance"]
    assert all(i["draft"] for i in data["illustrations"])
    assert (out / "analysis.md").exists()


def test_outline_without_images_uses_cover_plus_sections(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("# T\n\n## One\n\ntext\n\n## Two\n\nmore\n", encoding="utf-8")
    outline = b.make_outline(p, tmp_path / "o", "scene", "warm", None, None, "4:3", "per-section")
    assert [i["position"] for i in outline["illustrations"]] == ["cover", "One", "Two"]


def test_style_alias_and_overrides(article, tmp_path):
    out = tmp_path / "ill"
    b.main(["outline", str(article), "--out-dir", str(out), "--type", "comparison", "--style", "vector", "--palette", "macaron"])
    data = yaml.safe_load((out / "outline.yaml").read_text(encoding="utf-8"))
    assert (data["type"], data["style"], data["palette"]) == ("comparison", "vector-illustration", "macaron")


def test_unknown_dimensions_rejected(article, tmp_path):
    with pytest.raises(SystemExit):
        b.main(["outline", str(article), "--out-dir", str(tmp_path), "--preset", "nope"])
    with pytest.raises(SystemExit):
        b.main(["outline", str(article), "--out-dir", str(tmp_path), "--style", "nope"])
    with pytest.raises(SystemExit):
        b.main(["outline", str(article), "--out-dir", str(tmp_path), "--palette", "nope"])


def _prepared_outline(article, tmp_path):
    out = tmp_path / "ill"
    b.main(["outline", str(article), "--out-dir", str(out), "--preset", "kids-picture-book"])
    op = out / "outline.yaml"
    data = yaml.safe_load(op.read_text(encoding="utf-8"))
    for item in data["illustrations"]:
        item["visual"] = f"A plain white airplane over a green hill, scene {item['id']}."
        item["draft"] = False
    data["illustrations"][2]["type"] = "comparison"
    data["illustrations"][2]["palette"] = "macaron"
    op.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return op


def test_prompt_files_record_and_body(article, tmp_path):
    op = _prepared_outline(article, tmp_path)
    jobs = b.write_prompt_files(op)
    assert len(jobs) == 3
    names = sorted(p.name for p in (op.parent / "prompts").iterdir())
    assert names == [
        "01-scene-cover.md", "01-scene-cover.prompt.txt",
        "02-scene-ambulance.md", "02-scene-ambulance.prompt.txt",
        "03-comparison-waves.md", "03-comparison-waves.prompt.txt",
    ]
    rec = (op.parent / "prompts" / "02-scene-ambulance.md").read_text(encoding="utf-8")
    fm = yaml.safe_load(rec.split("---")[1])
    assert fm["alt"] == "救护车从身边开过" and fm["output"] == "02-scene-ambulance.jpg"
    body = Path(jobs[1]["prompt_file"]).read_text(encoding="utf-8")
    assert body.rstrip().endswith(NO_TEXT_CLAUSE)
    assert "救护车" not in body  # Chinese alt never reaches the image model
    assert "palette override: macaron" in Path(jobs[2]["prompt_file"]).read_text(encoding="utf-8")


def test_generate_builds_generate_image_commands(article, tmp_path, monkeypatch):
    op = _prepared_outline(article, tmp_path)
    calls = []

    class P:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "ok", ""

    attempts = {}

    def fake_run(cmd, **kw):
        calls.append(cmd)
        key = cmd[cmd.index("--image") + 1]
        attempts[key] = attempts.get(key, 0) + 1
        # first image fails once, then succeeds (retry path)
        return P(1 if key.endswith("01-scene-cover.jpg") and attempts[key] == 1 else 0)

    monkeypatch.setattr(b.subprocess, "run", fake_run)
    rc = b.main(["run", "--outline", str(op), "--generator", "grok-build", "--only", "1,3"])
    assert rc == 0
    assert len(calls) == 3  # 2 images + 1 retry
    cmd = calls[0]
    assert cmd[0] == sys.executable and cmd[1].endswith("generate_image.py")
    assert cmd[cmd.index("--promptfiles") + 1].endswith("01-scene-cover.prompt.txt")
    assert cmd[cmd.index("--ar") + 1] == "4:3"
    assert cmd[cmd.index("--generator") + 1] == "grok-build"
    assert (op.parent / "generation.json").exists()


def test_dry_run_passes_print_command(article, tmp_path, monkeypatch):
    op = _prepared_outline(article, tmp_path)
    seen = []

    class P:
        returncode, stdout, stderr = 0, "generator: grok-build", ""

    monkeypatch.setattr(b.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or P())
    assert b.main(["generate", "--outline", str(op), "--dry-run"]) == 0
    assert all("--print-command" in c for c in seen) and len(seen) == 3


def test_generate_image_accepts_promptfiles_for_grok_build(tmp_path):
    import generate_image as gi

    pf = tmp_path / "p.prompt.txt"
    pf.write_text("A kite.\n\n" + NO_TEXT_CLAUSE, encoding="utf-8")
    args = gi.parse_args(["--generator", "grok-build", "--promptfiles", str(pf), "--image", str(tmp_path / "o.jpg"), "--ar", "4:3"])
    gen, cmd = gi.build_command(args)
    assert gen == "grok-build"
    assert cmd[1].endswith("grok_image_gen.py")
    assert NO_TEXT_CLAUSE in cmd[cmd.index("--prompt") + 1]
