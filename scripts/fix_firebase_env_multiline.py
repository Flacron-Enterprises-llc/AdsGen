"""Rewrite .env: multiline FIREBASE_CREDENTIALS_JSON -> single line (python-dotenv compatible)."""
from pathlib import Path
import json
import sys

def main() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    text = path.read_text(encoding="utf-8")
    marker = "FIREBASE_CREDENTIALS_JSON="
    start = text.find(marker)
    if start == -1:
        print("No FIREBASE_CREDENTIALS_JSON in .env", file=sys.stderr)
        sys.exit(1)
    brace = text.find("{", start)
    if brace == -1:
        print("No opening brace", file=sys.stderr)
        sys.exit(1)
    depth = 0
    end = None
    for i in range(brace, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        print("Unbalanced braces", file=sys.stderr)
        sys.exit(1)
    obj = json.loads(text[brace:end])
    one = json.dumps(obj, separators=(",", ":"))
    escaped = one.replace("\\", "\\\\").replace('"', '\\"')
    line = f'FIREBASE_CREDENTIALS_JSON="{escaped}"'
    before = text[: text.find(marker)].rstrip()
    after = text[end:]
    while after and after[0] in " \r\n":
        after = after[1:]
    new_text = before + "\n" + line + "\n\n" + after.lstrip()
    path.write_text(new_text, encoding="utf-8", newline="\n")
    print("OK: wrote single-line FIREBASE_CREDENTIALS_JSON to .env")


if __name__ == "__main__":
    main()
