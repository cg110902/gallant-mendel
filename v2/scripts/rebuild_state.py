#!/usr/bin/env python3
"""Rebuild or incrementally update a branch's derived SQLite projection."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from novel_kernel.events import EventLogError  # noqa: E402
from novel_kernel.projection import ProjectionError, ProjectionStore  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--book", required=True, type=Path, help="book workspace path")
    result.add_argument("--branch", default="main", help="branch to project (default: main)")
    result.add_argument("--update", action="store_true", help="apply only a verified lineage suffix")
    result.add_argument("--json", action="store_true", dest="json_mode", help="emit JSON report")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = ProjectionStore(args.book, branch_id=args.branch)
    try:
        report = store.update() if args.update else store.rebuild()
    except (ProjectionError, EventLogError) as exc:
        if args.json_mode:
            print(json.dumps({"ok": False, "exit_code": 6, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"projection error: {exc}", file=sys.stderr)
        return 6
    value = asdict(report)
    value["database_path"] = str(store.database_path)
    if args.json_mode:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"projection PASS branch={report.branch_id} events={report.applied_event_count} "
            f"head={report.last_applied_event_id or '-'} hash={report.state_hash}"
        )
        print(f"database: {store.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
