#!/usr/bin/env python3
"""Create, validate, or non-destructively restore a snapshot.v1 package."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novel_kernel.snapshots import SnapshotError, SnapshotManager  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create")
    create.add_argument("--book", required=True, type=Path)
    create.add_argument("--label", required=True)
    create.add_argument("--branch", default="main")
    create.add_argument("--artifact", action="append", default=[], type=Path)
    create.add_argument("--json", action="store_true", dest="json_mode")
    validate = subcommands.add_parser("validate")
    validate.add_argument("--snapshot", required=True, type=Path)
    validate.add_argument("--json", action="store_true", dest="json_mode")
    restore = subcommands.add_parser("restore")
    restore.add_argument("--snapshot", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    restore.add_argument("--json", action="store_true", dest="json_mode")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "create":
            report = SnapshotManager(args.book).create(
                label=args.label, branch_id=args.branch, artifact_paths=args.artifact
            )
        elif args.command == "validate":
            report = SnapshotManager.validate(args.snapshot)
        else:
            report = SnapshotManager.restore(args.snapshot, args.target)
    except SnapshotError as exc:
        if args.json_mode:
            print(json.dumps({"ok": False, "exit_code": 6, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"snapshot error: {exc}", file=sys.stderr)
        return 6
    value = asdict(report)
    value["ok"] = True
    if args.json_mode:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
