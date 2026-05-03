"""
sync_docs.py — ChronoCaster PWA publish helper
================================================
Copies the contents of pwa/ into docs/ (the GitHub Pages source folder)
and prints a reminder to push.

Usage:
    python sync_docs.py

After running:
    git add docs/
    git commit -m "release: update PWA"
    git push
"""

import shutil
import sys
from pathlib import Path

SRC  = Path(__file__).parent / 'pwa'
DEST = Path(__file__).parent / 'docs'

if not SRC.exists():
    sys.exit(f"ERROR: source folder not found: {SRC}")

print(f"Syncing  {SRC}  →  {DEST} ...")

if DEST.exists():
    shutil.rmtree(DEST)

shutil.copytree(SRC, DEST)

print(f"Done. {sum(1 for _ in DEST.rglob('*') if _.is_file())} files copied.")
print()
print("Next steps:")
print("  git add docs/")
print('  git commit -m "release: update PWA"')
print("  git push")
print()
print("Make sure GitHub Pages is set to publish from the  docs/  folder")
print("(Settings → Pages → Source → Branch: main, Folder: /docs)")
