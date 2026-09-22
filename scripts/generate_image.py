#!/usr/bin/env python3
"""
统一生图入口。

默认走项目内置 baoyu_image_gen.ts。可选后端:

    image_generation:
      generator: baoyu-image-gen            # 默认
      # generator: baoyu-danger-gemini-web  # Gemini Web 登录版
      # generator: grok-build               # 云机 grok + Imagine (需 PATH 上有 grok)

"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from config import ConfigError, get_config, get_global_image_generator, load_env


DEFAULT_GENERATOR = "baoyu-image-gen"
GENERATORS = {"baoyu-image-gen", "baoyu-danger-gemini-web", "grok-build"}


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _resolve_generator(account: Optional[str], cli_value: Optional[str]) -> str:
    if cli_value:
        generator = cli_value
    else:
        generator = ""
        try:
            generator = get_config(account).get("image_generator", "") or ""
        except ConfigError:
            generator = ""
        if not generator:
            generator = get_global_image_generator()

    generator = generator.strip() or DEFAULT_GENERATOR
    if generator not in GENERATORS:
        raise SystemExit(
            f"未知 image generator: {generator}. 可选: {', '.join(sorted(GENERATORS))}"
        )
    return generator


def _base_args(args: argparse.Namespace) -> List[str]:
    cmd: List[str] = []
    if args.prompt:
        cmd += ["--prompt", args.prompt]
    if args.promptfiles:
        cmd += ["--promptfiles", *args.promptfiles]
    if args.image:
        cmd += ["--image", args.image]
    if args.model:
        cmd += ["--model", args.model]
    if args.ref:
        cmd += ["--ref", *args.ref]
    if args.json:
        cmd.append("--json")
    return cmd


def _baoyu_image_gen_args(args: argparse.Namespace) -> List[str]:
    cmd = _base_args(args)
    if args.provider:
        cmd += ["--provider", args.provider]
    if args.ar:
        cmd += ["--ar", args.ar]
    if args.size:
        cmd += ["--size", args.size]
    if args.quality:
        cmd += ["--quality", args.quality]
    if args.n:
        cmd += ["--n", str(args.n)]
    return cmd


def _danger_gemini_web_args(args: argparse.Namespace) -> List[str]:
    unsupported = []
    for name in ("provider", "ar", "size", "quality", "n"):
        if getattr(args, name):
            unsupported.append(f"--{name}")
    if unsupported:
        raise SystemExit(
            "baoyu-danger-gemini-web 不支持这些 baoyu-image-gen 专属参数: "
            + ", ".join(unsupported)
        )
    return _base_args(args)



def _grok_build_args(args: argparse.Namespace) -> List[str]:
    """Args for scripts/grok_image_gen.py."""
    if not args.prompt and not args.promptfiles:
        raise SystemExit("grok-build 需要 --prompt 或 --promptfiles")
    prompt = args.prompt or ""
    if args.promptfiles:
        parts = [Path(fp).read_text(encoding="utf-8") for fp in args.promptfiles]
        joined = "\n\n".join(parts).strip()
        prompt = f"{prompt}\n\n{joined}".strip() if prompt else joined
    cmd: List[str] = ["--prompt", prompt, "--image", args.image]
    if args.ar:
        cmd += ["--ar", args.ar]
    if args.size:
        cmd += ["--size", args.size]
    if args.quality:
        cmd += ["--quality", args.quality]
    unsupported = []
    for name in ("provider", "model", "n", "ref"):
        if getattr(args, name, None):
            unsupported.append(f"--{name}")
    if unsupported:
        print(
            "警告: grok-build 忽略这些参数: " + ", ".join(unsupported),
            file=sys.stderr,
        )
    return cmd


def build_command(args: argparse.Namespace) -> tuple[str, List[str]]:
    load_env()
    generator = _resolve_generator(args.account, args.generator)
    scripts = _script_dir()

    if generator == "baoyu-danger-gemini-web":
        return generator, [
            "bun",
            str(scripts / "baoyu_danger_gemini_web" / "main.ts"),
            *_danger_gemini_web_args(args),
        ]

    if generator == "grok-build":
        return generator, [
            sys.executable,
            str(scripts / "grok_image_gen.py"),
            *_grok_build_args(args),
        ]

    return generator, [
        "bun",
        str(scripts / "baoyu_image_gen.ts"),
        *_baoyu_image_gen_args(args),
    ]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统一生图入口")
    parser.add_argument("--account", help="用于读取 wechat-publisher.yaml 中的 image_generator")
    parser.add_argument(
        "--generator",
        choices=sorted(GENERATORS),
        help="覆盖配置中的生图后端",
    )
    parser.add_argument("-p", "--prompt")
    parser.add_argument("--promptfiles", nargs="+")
    parser.add_argument("--image", required=True)
    parser.add_argument("-m", "--model")
    parser.add_argument("--ref", nargs="+")
    parser.add_argument("--provider")
    parser.add_argument("--ar")
    parser.add_argument("--size")
    parser.add_argument("--quality")
    parser.add_argument("--n", type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    generator, cmd = build_command(args)

    if args.print_command:
        print("generator:", generator)
        print(" ".join(cmd))
        return 0

    env = os.environ.copy()
    env["WECHAT_PUBLISHER_IMAGE_GENERATOR_USED"] = generator
    return subprocess.run(cmd, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
