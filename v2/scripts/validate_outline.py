#!/usr/bin/env python3
"""Validate an Outline Package v1 layout and manifest without compiling it."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novel_kernel.outline import OutlineError, OutlinePackageValidator  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument("--outline", type=Path, help="path to the outline/ directory")
    source.add_argument("--book", help="book ID below workspace/")
    result.add_argument("--json", action="store_true", dest="json_mode")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    outline = args.outline if args.outline is not None else ROOT / "workspace" / args.book / "outline"
    expected = args.book if args.book is not None else None
    try:
        report = OutlinePackageValidator().validate(outline, expected_book_id=expected)
    except OutlineError as exc:
        if args.json_mode:
            print(json.dumps({"ok": False, "exit_code": exc.exit_code, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"outline validation error: {exc}", file=sys.stderr)
        return exc.exit_code
    value = asdict(report)
    if args.json_mode:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"outline PASS book={report.book_id} schema={report.schema_version} "
            f"structured={report.structured_document_count} sources={report.source_file_count}"
        )
        print(f"package hash: {report.package_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
