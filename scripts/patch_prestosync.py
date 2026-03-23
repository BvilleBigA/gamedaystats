#!/usr/bin/env python3
"""
Patch a packaged PrestoSync.app to use your Gameday Stats API instead of PrestoSports.

  python3 scripts/patch_prestosync.py /path/to/PrestoSync.app
  python3 scripts/patch_prestosync.py /path/to/PrestoSync.app --url https://stats.bvillebiga.com/api

Requires: Node.js + npx (uses @electron/asar to extract/repack app.asar).

Steps:
  1. Backup Contents/Resources/app.asar
  2. Extract ASAR, replace https://gameday-api.prestosports.com/api in bundled JS/HTML/JSON
  3. Repack app.asar
  4. Remove AsarIntegrity / ElectronAsarIntegrity from Info.plist (checksum no longer matches
     after repack; without these keys, integrity validation is skipped for that metadata)

Code signing: the bundle is no longer validly signed. On macOS you may need:
  xattr -cr PrestoSync.app
  open PrestoSync.app   # or right-click → Open the first time
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OLD_DEFAULT = "https://gameday-api.prestosports.com/api"
NEW_DEFAULT = "https://stats.bvillebiga.com/api"

TEXT_SUFFIXES = {".js", ".json", ".html", ".htm", ".map", ".css"}


def _run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _replace_in_tree(root: Path, old: str, new: str) -> int:
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if old not in text:
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        count += 1
    return count


def _strip_asar_integrity_plist(plist_path: Path) -> None:
    with plist_path.open("rb") as f:
        pl = plistlib.load(f)
    changed = False
    for key in ("AsarIntegrity", "ElectronAsarIntegrity"):
        if key in pl:
            del pl[key]
            changed = True
            print(f"Removed Info.plist key: {key}")
    if not changed:
        print("(No AsarIntegrity / ElectronAsarIntegrity keys in Info.plist — OK)")
        return
    with plist_path.open("wb") as f:
        plistlib.dump(pl, f, fmt=plistlib.FMT_XML)
    print(f"Updated {plist_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch PrestoSync.app API base URL")
    ap.add_argument(
        "app",
        type=Path,
        help="Path to PrestoSync.app",
    )
    ap.add_argument(
        "--url",
        default=NEW_DEFAULT,
        help=f"New API base URL (default: {NEW_DEFAULT})",
    )
    ap.add_argument(
        "--old-url",
        default=OLD_DEFAULT,
        help=f"String to replace (default: {OLD_DEFAULT})",
    )
    args = ap.parse_args()

    app: Path = args.app.expanduser().resolve()
    asar = app / "Contents" / "Resources" / "app.asar"
    plist_path = app / "Contents" / "Info.plist"
    old_u: str = args.old_url
    new_u: str = args.url.rstrip("/")

    if not app.is_dir() or not app.name.endswith(".app"):
        print("Error: first argument must be a .app bundle directory", file=sys.stderr)
        return 1
    if not asar.is_file():
        print(f"Error: missing {asar}", file=sys.stderr)
        return 1
    if not plist_path.is_file():
        print(f"Error: missing {plist_path}", file=sys.stderr)
        return 1
    if old_u == new_u:
        print("Old and new URL are the same; nothing to do.")
        return 0

    backup = asar.with_suffix(f".asar.bak-{Path(__file__).stem}")
    if not backup.exists():
        shutil.copy2(asar, backup)
        print(f"Backup: {backup}")

    with tempfile.TemporaryDirectory(prefix="prestosync-patch-") as tmp:
        tdir = Path(tmp)
        extracted = tdir / "extracted"
        packed = tdir / "app.asar.new"
        _run(
            [
                "npx",
                "--yes",
                "@electron/asar",
                "extract",
                str(asar),
                str(extracted),
            ]
        )
        n = _replace_in_tree(extracted, old_u, new_u)
        if n == 0:
            print(
                f"Error: did not find {old_u!r} in any bundled text files. "
                "Wrong app version or URL already patched?",
                file=sys.stderr,
            )
            return 1
        print(f"Replaced URL in {n} file(s).")
        _run(
            [
                "npx",
                "--yes",
                "@electron/asar",
                "pack",
                str(extracted),
                str(packed),
            ]
        )
        shutil.copy2(packed, asar)
        print(f"Wrote {asar}")

    _strip_asar_integrity_plist(plist_path)

    print()
    print("Done. Launch the app once via right-click → Open if Gatekeeper complains.")
    print("If it still will not start, try: xattr -cr", str(app))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
