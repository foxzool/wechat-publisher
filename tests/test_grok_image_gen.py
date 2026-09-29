"""Regression tests for scripts/grok_image_gen.py output resolution.

grok itself is never executed: ``_run_grok`` is monkeypatched to simulate what
the agent does inside its work dir.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import grok_image_gen as g

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def _write_png(path: Path, payload: bytes = PNG_1PX) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "article" / "images"
    d.mkdir(parents=True)
    return d


def _fake_grok(action):
    calls = {}

    def _run(prompt, workdir, timeout):
        calls["workdir"] = Path(workdir)
        calls["prompt"] = prompt
        return action(Path(workdir))

    return _run, calls


def test_happy_path_writes_output_from_stage(monkeypatch, out_dir):
    def act(workdir):
        _write_png(workdir / "generated.png")
        return 0, "GEN_OK path=x size=1"

    run, calls = _fake_grok(act)
    monkeypatch.setattr(g, "_run_grok", run)
    out = out_dir / "01.png"
    assert g.main(["-p", "a cat", "--image", str(out), "--no-jpeg"]) == 0
    assert out.read_bytes() == PNG_1PX
    # grok never runs in the output directory
    assert calls["workdir"].resolve() != out_dir.resolve()
    assert out_dir.resolve() not in calls["workdir"].resolve().parents
    # temp work dir cleaned up
    assert not calls["workdir"].exists()


def test_fallback_picks_file_grok_saved_under_other_name_in_workdir(monkeypatch, out_dir):
    payload = PNG_1PX + b"other-name"

    def act(workdir):
        _write_png(workdir / "sub" / "imagine_123.png", payload)
        return 0, "saved somewhere else"

    run, _ = _fake_grok(act)
    monkeypatch.setattr(g, "_run_grok", run)
    out = out_dir / "02.png"
    assert g.main(["-p", "a dog", "--image", str(out), "--no-jpeg"]) == 0
    assert out.read_bytes() == payload


@pytest.mark.parametrize("suffix,extra", [(".png", ["--no-jpeg"]), (".jpg", [])])
def test_newer_sibling_in_output_dir_is_never_copied(monkeypatch, out_dir, suffix, extra):
    """Regression: the old fallback globbed out.parent and copied the newest sibling."""
    sibling_payload = PNG_1PX + b"SIBLING"

    def act(workdir):
        # grok produced nothing, but a brand-new sibling appears in the output dir
        _write_png(out_dir / "05-hug.png", sibling_payload)
        future = time.time() + 60
        os.utime(out_dir / "05-hug.png", (future, future))
        return 0, "done (but no file)"

    run, _ = _fake_grok(act)
    monkeypatch.setattr(g, "_run_grok", run)
    out = out_dir / f"03{suffix}"
    with pytest.raises(SystemExit) as exc:
        g.main(["-p", "a bird", "--image", str(out), *extra])
    assert "no image produced" in str(exc.value)
    assert not out.exists()
    assert (out_dir / "05-hug.png").read_bytes() == sibling_payload


def test_nonzero_exit_without_image_fails_loudly(monkeypatch, out_dir):
    run, _ = _fake_grok(lambda wd: (2, "boom"))
    monkeypatch.setattr(g, "_run_grok", run)
    with pytest.raises(SystemExit) as exc:
        g.main(["-p", "x", "--image", str(out_dir / "04.png"), "--no-jpeg"])
    assert "exit=2" in str(exc.value)


def test_gen_fail_is_reported(monkeypatch, out_dir):
    run, _ = _fake_grok(lambda wd: (0, "GEN_FAIL reason=content-moderated"))
    monkeypatch.setattr(g, "_run_grok", run)
    with pytest.raises(SystemExit) as exc:
        g.main(["-p", "x", "--image", str(out_dir / "05.png"), "--no-jpeg"])
    assert "content-moderated" in str(exc.value)
    assert not (out_dir / "05.png").exists()


def test_ensure_output_ignores_files_older_than_run_start(tmp_path):
    work = tmp_path / "work"
    stale = _write_png(work / "old.png")
    past = time.time() - 3600
    os.utime(stale, (past, past))
    with pytest.raises(SystemExit):
        g._ensure_output(work / "generated.png", work, since=time.time())


def test_ensure_output_only_searches_given_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _write_png(tmp_path / "outside.png")  # fresh, but outside the work dir
    with pytest.raises(SystemExit):
        g._ensure_output(work / "generated.png", work, since=time.time() - 5)


def test_run_grok_uses_workdir_as_cwd(monkeypatch, tmp_path):
    seen = {}

    class P:
        returncode = 0
        stdout = "GEN_OK"
        stderr = ""

    def fake_run(cmd, cwd, **kw):
        seen["cmd"], seen["cwd"] = cmd, cwd
        return P()

    monkeypatch.setattr(g, "_which", lambda name: "/usr/bin/grok")
    monkeypatch.setattr(g.subprocess, "run", fake_run)
    code, out = g._run_grok("prompt", tmp_path, 10)
    assert code == 0 and seen["cwd"] == str(tmp_path)
    assert seen["cmd"][seen["cmd"].index("--cwd") + 1] == str(tmp_path)
