#!/usr/bin/env python3
"""
Grok Build image generator via cloud-box `grok` + Imagine (image_gen).

Requires:
  - `grok` on PATH
  - OAuth session at ~/.grok/auth.json (already present on Grok Bot boxes)

Invocation pattern (same as Shepherd fingerprint art):
  grok --always-approve --cwd <workdir> -p "Use image_gen ... save to <path>"

Optional WeChat-friendly JPEG compression: Pillow if available, else ffmpeg,
else leave the generated PNG/JPEG as-is.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _normalize_ar(ar: Optional[str]) -> str:
    if not ar:
        return "auto"
    ar = ar.strip()
    aliases = {
        "square": "1:1",
        "landscape": "16:9",
        "portrait": "9:16",
        "4x3": "4:3",
        "3x2": "3:2",
        "2x3": "2:3",
        "16x9": "16:9",
        "9x16": "9:16",
    }
    return aliases.get(ar.lower(), ar)


def _agent_prompt(
    prompt: str,
    out_path: Path,
    ar: str,
    size: Optional[str],
    quality: Optional[str],
) -> str:
    hints: list[str] = []
    if size:
        hints.append(
            f"Preferred pixel size hint: {size} (best-effort; Imagine may ignore exact pixels)."
        )
    if quality:
        hints.append(f"Quality preference: {quality}.")
    hint_block = ("\n".join(hints) + "\n") if hints else ""
    return (
        "Use the image_gen tool (Imagine skill) once.\n\n"
        f"Prompt for image_gen:\n{prompt.strip()}\n\n"
        f"aspect_ratio: {ar}\n"
        f"{hint_block}"
        "After the image is generated, copy or move the resulting image file to exactly:\n"
        f"{out_path.resolve()}\n\n"
        "Then print only: GEN_OK path=<absolute path> size=<bytes>\n"
        "If image_gen is unavailable, print only: GEN_FAIL reason=<exact error>\n"
    )


def _run_grok(prompt: str, workdir: Path, timeout: int) -> Tuple[int, str]:
    grok = _which("grok")
    if not grok:
        raise SystemExit(
            "grok not found on PATH. Install Grok Build CLI and complete OAuth "
            "(~/.grok/auth.json). See README / SKILL.md (grok-build)."
        )
    cmd = [
        grok,
        "--always-approve",
        "--cwd",
        str(workdir),
        "-p",
        prompt,
    ]
    print(
        f"[grok-build] running: grok --always-approve --cwd {workdir} -p <prompt>",
        file=sys.stderr,
    )
    proc = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out


def _jpeg_compress(src: Path, dest: Path, quality: int = 85) -> bool:
    try:
        from PIL import Image  # type: ignore

        with Image.open(src) as im:
            rgb = im.convert("RGB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            rgb.save(dest, format="JPEG", quality=quality, optimize=True)
        return True
    except Exception as exc:
        print(f"[grok-build] Pillow compress skipped: {exc}", file=sys.stderr)

    ffmpeg = _which("ffmpeg")
    if ffmpeg:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Map 1-100 JPEG quality roughly onto ffmpeg -q:v (2=best … 31=worst)
        qv = max(2, min(31, int((100 - quality) / 3) + 2))
        cmd = [ffmpeg, "-y", "-i", str(src), "-q:v", str(qv), str(dest)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return True
        print(
            f"[grok-build] ffmpeg compress failed: {(proc.stderr or '')[-400:]}",
            file=sys.stderr,
        )
    return False


def _ensure_output(requested: Path, workdir: Path) -> Path:
    if requested.exists() and requested.stat().st_size > 0:
        return requested
    candidates: list[Path] = []
    for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        candidates.extend(workdir.glob(pat))
        candidates.extend(workdir.rglob(pat))
    candidates = [
        p
        for p in candidates
        if p.is_file() and p.stat().st_size > 0 and p.resolve() != requested.resolve()
    ]
    if not candidates:
        raise SystemExit(
            f"grok-build: no image at {requested} and none under {workdir}"
        )
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    requested.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(newest, requested)
    return requested


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grok Build Imagine image generator")
    p.add_argument("-p", "--prompt", required=True, help="Image prompt")
    p.add_argument("--image", required=True, help="Output image path")
    p.add_argument("--ar", help="Aspect ratio, e.g. 16:9 / 4:3 / 1:1")
    p.add_argument("--size", help="Soft size hint, e.g. 1024x768")
    p.add_argument("--quality", help="Soft quality hint: normal|2k|…")
    p.add_argument(
        "--jpeg-quality",
        type=int,
        default=85,
        help="JPEG compression quality when converting (default 85)",
    )
    p.add_argument(
        "--no-jpeg",
        action="store_true",
        help="Keep PNG/original; skip WeChat JPEG compression",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for grok (default 300)",
    )
    p.add_argument(
        "--print-command",
        action="store_true",
        help="Print the grok invocation and exit without running",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out = Path(args.image).expanduser().resolve()
    ar = _normalize_ar(args.ar)
    workdir = out.parent
    workdir.mkdir(parents=True, exist_ok=True)

    want_jpeg = (not args.no_jpeg) and out.suffix.lower() in {".jpg", ".jpeg"}
    tmp_dir: Optional[str] = None
    stage = out
    if want_jpeg:
        tmp_dir = tempfile.mkdtemp(prefix="grok-img-")
        stage = Path(tmp_dir) / "generated.png"

    agent_prompt = _agent_prompt(args.prompt, stage, ar, args.size, args.quality)
    grok_cwd = stage.parent

    if args.print_command:
        print("generator: grok-build")
        print(f"grok --always-approve --cwd {grok_cwd} -p {agent_prompt!r}")
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return 0

    try:
        code, combined = _run_grok(agent_prompt, workdir=grok_cwd, timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise SystemExit(f"grok-build: grok timed out after {args.timeout}s") from exc

    # Surface grok output (trimmed) for debugging
    print(combined[-4000:] if len(combined) > 4000 else combined)

    if "GEN_FAIL" in combined:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        for line in combined.splitlines():
            if "GEN_FAIL" in line:
                raise SystemExit(line.strip())
        raise SystemExit("grok-build: GEN_FAIL (see grok output above)")

    try:
        produced = _ensure_output(stage, workdir)
    except SystemExit:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if code != 0:
            raise SystemExit(f"grok-build: grok exit={code}; no image produced") from None
        raise

    final = out
    if want_jpeg:
        ok = _jpeg_compress(produced, final, quality=args.jpeg_quality)
        if not ok:
            final.parent.mkdir(parents=True, exist_ok=True)
            if produced.resolve() != final.resolve():
                shutil.copy2(produced, final)
            print(f"[grok-build] left uncompressed at {final}", file=sys.stderr)
    else:
        final.parent.mkdir(parents=True, exist_ok=True)
        if produced.resolve() != final.resolve():
            shutil.copy2(produced, final)

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    size = final.stat().st_size
    print(f"GEN_OK path={final} size={size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
