#!/usr/bin/env python3
"""Fail when source files contain common credential or local-path leaks."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

PATTERNS = {
    "Canvas bearer token": re.compile(r"Bearer\s+[A-Za-z0-9_-]{20,}"),
    "assigned Canvas token": re.compile(r"CANVAS_ACCESS_TOKEN\s*=\s*['\"][^'\"]+['\"]"),
    "Canvas calendar secret": re.compile(r"/feeds/calendars/user_[A-Za-z0-9]{20,}"),
    "macOS user path": re.compile(r"/" + r"Users/[^/\s]+/"),
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
    "export profile identifier": re.compile(r'"(?:primary_email|sis_user_id|login_id)"\s*:\s*"(?!private@example\.com)[^\"]+"'),
}


def is_skipped(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        any(part in SKIP_PARTS or part.startswith("canvas-export-") for part in relative.parts)
        or path.name.startswith(".env")
    )


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or is_skipped(path) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: {label}")

    if findings:
        print("Privacy check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print("Privacy check passed: no common source-code leaks found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
