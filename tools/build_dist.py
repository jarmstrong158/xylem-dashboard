#!/usr/bin/env python3
"""Assemble the exact set of files that may be published, and nothing else.

An ALLOWLIST, not an exclusion list. This directory also holds `vault/` — 433
markdown files of full entry prose from every named project — and a deploy that
worked by excluding known-bad paths would ship it the first time someone added a
new artifact and forgot to exclude it. The same reasoning as CAMBIUM_PROJECTS:
a thing travels because it was named, never because nothing stopped it.

    python tools/build_dist.py          # -> dist/
    python tools/build_dist.py --check  # verify only, write nothing
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

# Everything that may be published. Adding a file here is a deliberate act.
FILES = [
    "index.html",
    "app.css",
    "app.js",
    "sw.js",
    "manifest.webmanifest",
    "snapshot.json",
    "icons/icon-192.png",
    "icons/icon-512.png",
]

# Nothing matching these may EVER appear in dist, whatever FILES says.
FORBIDDEN_DIRS = {"vault", ".git", "tools", "node_modules"}


def active_files():
    """--no-data builds the app with no snapshot at all.

    A new Pages project is publicly reachable at its *.pages.dev address until
    an Access policy is attached. The first deploy therefore ships the shell
    only: it renders its own "No snapshot" state, which is exactly what an
    unauthenticated visitor should see, and there is no window in which the
    corpus sits on an open URL."""
    if "--no-data" in sys.argv:
        return [f for f in FILES if f != "snapshot.json"]
    return FILES


def check():
    missing = [f for f in active_files()
               if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        print("MISSING (refusing to build):")
        for m in missing:
            print("   ", m)
        if "snapshot.json" in missing:
            print("\n  Generate it first:")
            print("    cambium-mcp refresh --out snapshot.json --vault vault")
        return False
    return True


def build():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    files = active_files()
    for rel in files:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(DIST, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    # Prove the promise rather than asserting it: walk what was actually
    # written and refuse to hand over a tree containing anything unnamed.
    written = []
    for base, dirs, found in os.walk(DIST):   # `found`, not `files` — the walk
        dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIRS]   # shadowed the
        for f in found:                                          # allowlist
            written.append(os.path.relpath(os.path.join(base, f), DIST)
                           .replace("\\", "/"))
    unexpected = sorted(set(written) - set(files))
    if unexpected:
        shutil.rmtree(DIST)
        print("REFUSING: dist contained files not on the allowlist:")
        for u in unexpected:
            print("   ", u)
        return False

    total = sum(os.path.getsize(os.path.join(DIST, f)) for f in written)
    print("dist/ built — %d files, %.0f KB" % (len(written), total / 1024))
    for f in sorted(written):
        print("   ", f)
    print("\nvault/ excluded:", "yes" if not os.path.isdir(
        os.path.join(DIST, "vault")) else "NO — ABORT")
    return True


if __name__ == "__main__":
    if not check():
        sys.exit(1)
    if "--check" in sys.argv:
        print("all publishable files present")
        sys.exit(0)
    sys.exit(0 if build() else 1)
