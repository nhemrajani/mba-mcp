#!/usr/bin/env python3
"""Build the one-click Claude Desktop bundle (``dist/mba-mcp.mcpb``).

A .mcpb is a zip of the server plus its dependencies and a manifest describing
the settings Desktop should collect from the user. Because pydantic ships a
compiled core, a bundle is only portable to the platform it was built for —
pass ``--platform`` to cross-build wheels for another one.

    python scripts/build_mcpb.py
    python scripts/build_mcpb.py --platform win_amd64 --out dist/mba-mcp-win.mcpb
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "mcpb"
DEPENDENCIES = ["fastmcp>=2.0", "httpx>=0.27", "pydantic>=2.6"]
GMAIL_DEPENDENCIES = ["google-api-python-client>=2.120", "google-auth-oauthlib>=1.2"]

ENTRY_POINT = '''"""Entry point for the packaged Claude Desktop bundle."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from mba_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
'''


def build(out: Path, platform: str | None, python_version: str, with_gmail: bool) -> Path:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    if BUILD.exists():
        shutil.rmtree(BUILD)
    lib = BUILD / "server" / "lib"
    lib.mkdir(parents=True)

    shutil.copytree(
        ROOT / "src" / "mba_mcp",
        lib / "mba_mcp",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (BUILD / "server" / "main.py").write_text(ENTRY_POINT, encoding="utf-8")
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name in ("README.md", "LICENSE"):
        shutil.copy(ROOT / name, BUILD / name)

    requirements = DEPENDENCIES + (GMAIL_DEPENDENCIES if with_gmail else [])
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(lib), *requirements]
    if platform:
        # Cross-building needs pure wheels only; no source builds for the host.
        command += ["--platform", platform, "--python-version", python_version, "--only-binary=:all:"]
    subprocess.run(command, check=True)

    # Keep .dist-info: fastmcp reads its own version through importlib.metadata
    # at import time and refuses to start without it.
    for junk in lib.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(BUILD))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "mba-mcp.mcpb")
    parser.add_argument("--platform", help="wheel platform tag, e.g. win_amd64, macosx_11_0_arm64")
    parser.add_argument("--python-version", default="3.12")
    parser.add_argument("--no-gmail", action="store_true", help="omit the Gmail sending libraries")
    args = parser.parse_args()

    bundle = build(args.out, args.platform, args.python_version, not args.no_gmail)
    size = bundle.stat().st_size / 1_000_000
    print(f"built {bundle} ({size:.1f} MB)")
    print("Install it by dragging it onto Claude Desktop, or double-clicking it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
