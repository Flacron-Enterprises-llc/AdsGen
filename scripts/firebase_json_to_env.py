#!/usr/bin/env python3
"""
Print FIREBASE_CREDENTIALS_JSON in a form suitable for .env or hosting dashboards.

Usage:  python scripts/firebase_json_to_env.py path/to/serviceAccountKey.json

- Copy the "one-line JSON" line into Render/Railway/etc. as the value of FIREBASE_CREDENTIALS_JSON.
- Or append the "FIREBASE_CREDENTIALS_JSON=..." line to .env (do not commit .env).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/firebase_json_to_env.py path/to/serviceAccountKey.json", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        sys.exit(1)
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    one_line = json.dumps(data, separators=(",", ":"))

    # .env double-quoted value (python-dotenv compatible)
    escaped = one_line.replace("\\", "\\\\").replace('"', '\\"')
    env_line = f'FIREBASE_CREDENTIALS_JSON="{escaped}"'

    print("--- One-line JSON (paste as secret value only, key = FIREBASE_CREDENTIALS_JSON) ---")
    print(one_line)
    print()
    print("--- Full line for .env (omit FIREBASE_CREDENTIALS_PATH when using this) ---")
    print(env_line)
    print()
    print("On deploy: add FIREBASE_CREDENTIALS_JSON in the host's environment variables; do not commit the JSON.")


if __name__ == "__main__":
    main()
