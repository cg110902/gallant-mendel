#!/usr/bin/env python3
"""Novel Production OS M0 deterministic command-line entry point."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from novel_kernel.version import VERSION_INFO

SUCCESS = 0
INPUT_OR_CONFIG_ERROR = 1
SCHEMA_FORMAT_ERROR = 2
ENVIRONMENT_ERROR = 5

ROOT = Path(__file__).resolve().parent
PYTHON_MIN = tuple(int(part) for part in VERSION_INFO["python_min"].split("."))
BASE_DIRECTORIES = (
    "novel_kernel",
    "schemas",
    "scripts",
    "tests",
    "workspace",
    "verification",
    "施工状态",
)
INIT_DIRECTORIES = (
    "outline",
    "state",
    "ledger",
    "production",
    "chapters",
    "runs",
    "audits",
    "snapshots",
    "branches",
    "exports",
)
FIXTURE_REQUIRED_FIELDS = {
    "schema_version": str,
    "project": str,
    "kind": str,
    "fixture_id": str,
}


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    exit_code_if_failed: int
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "exit_code_if_failed": self.exit_code_if_failed,
            "message": self.message,
        }


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = INPUT_OR_CONFIG_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse_flags(args: Sequence[str], allowed: set[str]) -> set[str]:
    flags = set(args)
    unknown = flags - allowed
    if unknown or len(flags) != len(args):
        item = sorted(unknown)[0] if unknown else "duplicate option"
        raise CliError(f"unsupported option: {item}")
    return flags


def _version(args: Sequence[str]) -> int:
    flags = _parse_flags(args, {"--json"})
    if "--json" in flags:
        print(_json_dump(VERSION_INFO))
    else:
        print(
            "Novel Production OS "
            f"{VERSION_INFO['version']} | phase {VERSION_INFO['phase']} | "
            f"Python >= {VERSION_INFO['python_min']} | API key required: no"
        )
    return SUCCESS


def _help(args: Sequence[str]) -> int:
    if len(args) > 1:
        raise CliError("help accepts at most one command name")
    topic = args[0] if args else None
    help_text = {
        None: """Novel Production OS — deterministic CLI

Usage:
  python studio.py <command> [options]

Available commands:
  version [--json]                  Show engineering version metadata
  help [command]                    Show this help or command help
  doctor [--no-api-key] [--json]    Diagnose the M0 environment
         [--fixture PATH] [--write-probe PATH]
  init --path PATH [--force]        Create an M0 workspace skeleton
  outline validate (--book ID | --path PATH) [--json]
                                      Validate M2.1–M2.3 outline contracts
  outline compile (--book ID | --path PATH) [--json]
                                      Publish an M2.4 compiled generation
  outline bootstrap (--book ID | --path PATH) [--json]
                                      Commit an approved M2.5 initial authority batch
  outline readiness (--book ID | --path PATH) [--json]
                                      Assess M2.6 first-chapter prerequisites
  state query (--book ID | --path PATH) --as-of SELECTOR
              [--valid-at STORY_TIME] [--branch ID] [--json]
                                      Query M3.1 bitemporal authority state

Examples:
  python studio.py version --json
  python studio.py doctor --no-api-key
  python studio.py init --path workspace/book_demo
  python studio.py outline validate --book book_demo
  python studio.py outline compile --book book_demo
  python studio.py outline bootstrap --book book_demo
  python studio.py outline readiness --book book_demo
  python studio.py state query --book book_demo --as-of ch_001

M3.1 state query is read-only and keeps recorded, world, and narrative time separate.
""",
        "version": "Usage: python studio.py version [--json]",
        "help": "Usage: python studio.py help [version|help|doctor|init|outline|state]",
        "doctor": (
            "Usage: python studio.py doctor [--no-api-key] [--json] "
            "[--fixture PATH] [--write-probe PATH]"
        ),
        "init": "Usage: python studio.py init --path PATH [--force]",
        "outline": "Usage: python studio.py outline (validate|compile|bootstrap|readiness) (--book ID | --path PATH) [--json]",
        "state": "Usage: python studio.py state query (--book ID | --path PATH) --as-of SELECTOR [--valid-at STORY_TIME] [--branch ID] [--json]",
    }
    if topic not in help_text:
        raise CliError(f"unknown help topic: {topic}")
    print(help_text[topic])
    return SUCCESS


def validate_fixture(path: Path) -> tuple[int, str]:
    manifest_path = path / "manifest.json"
    if not path.is_dir():
        return INPUT_OR_CONFIG_ERROR, f"fixture directory does not exist: {path}"
    if not manifest_path.is_file():
        return INPUT_OR_CONFIG_ERROR, f"fixture manifest is missing: {manifest_path}"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        return INPUT_OR_CONFIG_ERROR, f"fixture manifest cannot be read: {exc}"
    except json.JSONDecodeError as exc:
        return SCHEMA_FORMAT_ERROR, (
            f"fixture manifest is invalid JSON at line {exc.lineno}, column {exc.colno}"
        )
    if not isinstance(value, dict):
        return SCHEMA_FORMAT_ERROR, "fixture manifest must be a JSON object"
    for field, expected_type in FIXTURE_REQUIRED_FIELDS.items():
        if field not in value:
            return SCHEMA_FORMAT_ERROR, f"fixture manifest is missing field: {field}"
        if not isinstance(value[field], expected_type) or not value[field]:
            return SCHEMA_FORMAT_ERROR, f"fixture manifest field has invalid type: {field}"
    if value["schema_version"] != "m0.fixture.v1":
        return SCHEMA_FORMAT_ERROR, "unsupported fixture schema_version"
    if value["project"] != VERSION_INFO["project"]:
        return SCHEMA_FORMAT_ERROR, "fixture project does not match this project"
    return SUCCESS, f"fixture is valid: {path}"


def _write_probe(parent: Path = ROOT) -> Check:
    try:
        with tempfile.TemporaryDirectory(prefix="m0-doctor-", dir=parent) as temp_dir:
            probe = Path(temp_dir) / "probe"
            probe.write_text("ok\n", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "ok\n":
                raise OSError("probe content mismatch")
        return Check("temporary_write", "pass", ENVIRONMENT_ERROR, f"write probe passed: {parent}")
    except OSError as exc:
        return Check("temporary_write", "fail", ENVIRONMENT_ERROR, f"write probe failed at {parent}: {exc}")


def _doctor(args: Sequence[str]) -> int:
    no_api_key = False
    json_mode = False
    fixture: Path | None = None
    write_probe = ROOT
    write_probe_set = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--no-api-key":
            if no_api_key:
                raise CliError("duplicate option: --no-api-key")
            no_api_key = True
        elif arg == "--json":
            if json_mode:
                raise CliError("duplicate option: --json")
            json_mode = True
        elif arg == "--fixture":
            if fixture is not None or index + 1 >= len(args):
                raise CliError("--fixture requires exactly one path")
            index += 1
            fixture = Path(args[index])
        elif arg == "--write-probe":
            if write_probe_set or index + 1 >= len(args):
                raise CliError("--write-probe requires exactly one path")
            index += 1
            write_probe = Path(args[index])
            write_probe_set = True
        else:
            raise CliError(f"unsupported option: {arg}")
        index += 1

    checks: list[Check] = []
    python_ok = sys.version_info[:2] >= PYTHON_MIN
    checks.append(
        Check(
            "python_version",
            "pass" if python_ok else "fail",
            ENVIRONMENT_ERROR,
            f"Python {sys.version_info.major}.{sys.version_info.minor}; minimum is {VERSION_INFO['python_min']}",
        )
    )
    cwd_ok = Path.cwd().resolve() == ROOT
    checks.append(
        Check(
            "engineering_root",
            "pass" if cwd_ok else "fail",
            INPUT_OR_CONFIG_ERROR,
            f"current directory is {Path.cwd().resolve()}; expected {ROOT}",
        )
    )
    agents_ok = (ROOT / "AGENTS.md").is_file()
    checks.append(
        Check("agents_file", "pass" if agents_ok else "fail", INPUT_OR_CONFIG_ERROR, "AGENTS.md exists" if agents_ok else "AGENTS.md is missing")
    )
    missing = [name for name in BASE_DIRECTORIES if not (ROOT / name).is_dir()]
    checks.append(
        Check(
            "base_directories",
            "pass" if not missing else "fail",
            INPUT_OR_CONFIG_ERROR,
            "all M0 base directories exist" if not missing else f"missing directories: {', '.join(missing)}",
        )
    )
    version_ok = all(key in VERSION_INFO for key in ("project", "version", "phase", "python_min", "api_required"))
    checks.append(
        Check(
            "version_metadata",
            "pass" if version_ok else "fail",
            SCHEMA_FORMAT_ERROR,
            "version metadata is readable" if version_ok else "version metadata is incomplete",
        )
    )
    checks.append(_write_probe(write_probe))
    try:
        json.loads("{}")
        checks.append(Check("stdlib_json", "pass", ENVIRONMENT_ERROR, "standard-library JSON is available"))
    except Exception as exc:  # pragma: no cover - protects against a broken runtime
        checks.append(Check("stdlib_json", "fail", ENVIRONMENT_ERROR, f"JSON unavailable: {exc}"))
    checks.append(
        Check(
            "api_key",
            "pass",
            ENVIRONMENT_ERROR,
            "no-api-key-ready" if no_api_key else "API key is optional and was not inspected",
        )
    )
    if fixture is not None:
        fixture_code, fixture_message = validate_fixture(fixture)
        checks.append(
            Check(
                "fixture_manifest",
                "pass" if fixture_code == SUCCESS else "fail",
                fixture_code,
                fixture_message,
            )
        )

    failures = [check for check in checks if check.status == "fail"]
    exit_code = failures[0].exit_code_if_failed if failures else SUCCESS
    report = {
        "ok": not failures,
        "phase": VERSION_INFO["phase"],
        "checks": [check.as_dict() for check in checks],
        "api_key_required": False,
    }
    if json_mode:
        print(_json_dump(report))
    else:
        stream = sys.stderr if failures else sys.stdout
        for check in checks:
            print(f"[{check.status.upper()}] {check.id}: {check.message}", file=stream)
        print("doctor: PASS" if not failures else f"doctor: FAIL (exit {exit_code})", file=stream)
    return exit_code


def _init(args: Sequence[str]) -> int:
    target: Path | None = None
    force = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--path":
            if target is not None or index + 1 >= len(args):
                raise CliError("--path requires exactly one target")
            index += 1
            target = Path(args[index])
        elif arg == "--force":
            if force:
                raise CliError("duplicate option: --force")
            force = True
        else:
            raise CliError(f"unsupported option: {arg}")
        index += 1
    if target is None:
        raise CliError("init requires --path PATH")
    if target.exists() and not target.is_dir():
        raise CliError(f"target exists and is not a directory: {target}")
    if target.exists() and not force:
        raise CliError(f"target already exists; use --force to refresh it: {target}")
    try:
        target.mkdir(parents=True, exist_ok=True)
        for directory in INIT_DIRECTORIES:
            (target / directory).mkdir(exist_ok=True)
        manifest = {
            "schema_version": "m0.workspace.v1",
            "project": VERSION_INFO["project"],
            "engineering_version": VERSION_INFO["version"],
            "phase_created": VERSION_INFO["phase"],
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise CliError(f"cannot initialize target: {exc}", ENVIRONMENT_ERROR) from None
    print(f"initialized M0 workspace: {target}")
    return SUCCESS


def _outline(args: Sequence[str]) -> int:
    if not args or args[0] not in {"validate", "compile", "bootstrap", "readiness"}:
        raise CliError("outline supports: outline validate | outline compile | outline bootstrap | outline readiness")
    action = args[0]
    book_id: str | None = None
    package_path: Path | None = None
    json_mode = False
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--book":
            if book_id is not None or package_path is not None or index + 1 >= len(args):
                raise CliError("--book requires one ID and cannot be combined with --path")
            index += 1
            book_id = args[index]
        elif arg == "--path":
            if package_path is not None or book_id is not None or index + 1 >= len(args):
                raise CliError("--path requires one directory and cannot be combined with --book")
            index += 1
            package_path = Path(args[index])
        elif arg == "--json":
            if json_mode:
                raise CliError("duplicate option: --json")
            json_mode = True
        else:
            raise CliError(f"unsupported option: {arg}")
        index += 1
    if book_id is None and package_path is None:
        raise CliError(f"outline {action} requires --book ID or --path PATH")

    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    from novel_kernel.outline_domain import OutlineDomainValidator

    root = package_path if package_path is not None else ROOT / "workspace" / book_id / "outline"
    try:
        if action == "validate":
            report = OutlineDomainValidator().validate(root, expected_book_id=book_id)
        elif action == "compile":
            from novel_kernel.outline_compile import OutlineCompiler
            report = OutlineCompiler().compile(root, expected_book_id=book_id)
        elif action == "bootstrap":
            from novel_kernel.outline_bootstrap import OutlineBootstrapper
            report = OutlineBootstrapper().bootstrap(root, expected_book_id=book_id)
        else:
            from novel_kernel.outline_readiness import OutlineReadinessChecker
            report = OutlineReadinessChecker().check(root, expected_book_id=book_id)
    except OutlineError as exc:
        if json_mode:
            value = {"ok": False, "exit_code": exc.exit_code, "error": str(exc)}
            if hasattr(exc, "diagnostics"):
                value["diagnostics"] = [item.as_dict() for item in exc.diagnostics]
            print(_json_dump(value))
        else:
            print(f"outline {action} error: {exc}", file=sys.stderr)
        return exc.exit_code
    if json_mode:
        print(_json_dump(asdict(report)))
    elif action == "validate":
        print(
            f"outline PASS book={report.book_id} schema={report.schema_version} "
            f"structured={report.structured_document_count} sources={report.source_file_count}"
        )
        print(f"package hash: {report.package_hash}")
    elif action == "compile":
        print(f"outline COMPILED book={report.book_id} compile_id={report.compile_id}")
        print(f"generation: {report.generation_path}")
    elif action == "bootstrap":
        print(f"outline BOOTSTRAPPED book={report.book_id} events={report.event_count} head={report.head_event_id}")
        print(f"projection state hash: {report.projection_state_hash}")
    else:
        print(f"outline READY book={report.book_id} chapter={report.chapter_id} compile_id={report.compile_id}")
        print(f"projection state hash: {report.projection_state_hash}")
    return SUCCESS


def _state(args: Sequence[str]) -> int:
    if not args or args[0] != "query":
        raise CliError("state currently supports only: state query")
    book_id: str | None = None
    book_path: Path | None = None
    as_of: str | None = None
    valid_at: str | None = None
    branch = "main"
    branch_set = False
    json_mode = False
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in {"--book", "--path", "--as-of", "--valid-at", "--branch"}:
            if index + 1 >= len(args):
                raise CliError(f"{arg} requires a value")
            value = args[index + 1]
            index += 2
            if arg == "--book":
                if book_id is not None or book_path is not None:
                    raise CliError("--book cannot be repeated or combined with --path")
                book_id = value
            elif arg == "--path":
                if book_path is not None or book_id is not None:
                    raise CliError("--path cannot be repeated or combined with --book")
                book_path = Path(value)
            elif arg == "--as-of":
                if as_of is not None:
                    raise CliError("duplicate option: --as-of")
                as_of = value
            elif arg == "--valid-at":
                if valid_at is not None:
                    raise CliError("duplicate option: --valid-at")
                valid_at = value
            else:
                if branch_set:
                    raise CliError("duplicate option: --branch")
                branch = value
                branch_set = True
            continue
        if arg == "--json":
            if json_mode:
                raise CliError("duplicate option: --json")
            json_mode = True
            index += 1
            continue
        raise CliError(f"unsupported option: {arg}")
    if book_id is None and book_path is None:
        raise CliError("state query requires --book ID or --path PATH")
    if as_of is None:
        raise CliError("state query requires --as-of SELECTOR")
    from novel_kernel.events import BOOK_ID_RE, BRANCH_ID_RE
    if book_id is not None and BOOK_ID_RE.fullmatch(book_id) is None:
        raise CliError("--book must match book_<lowercase-id>")
    if BRANCH_ID_RE.fullmatch(branch) is None:
        raise CliError("--branch has an invalid identifier")
    root = book_path if book_path is not None else ROOT / "workspace" / book_id
    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    from novel_kernel.temporal import TemporalStateQuery
    try:
        report = TemporalStateQuery().query(root, as_of=as_of, valid_at=valid_at, branch_id=branch)
    except OutlineError as exc:
        if json_mode:
            print(_json_dump({"ok": False, "exit_code": exc.exit_code, "error": str(exc)}))
        else:
            print(f"state query error: {exc}", file=sys.stderr)
        return exc.exit_code
    if json_mode:
        print(_json_dump(asdict(report)))
    else:
        print(
            f"state PASS book={report.book_id} branch={report.branch_id} "
            f"as_of={report.cutoff['selector']} valid_at={report.valid_at or 'current'}"
        )
        print(
            f"objects={len(report.objects)} facets={len(report.facets)} "
            f"facts={len(report.facts)} relations={len(report.relations)}"
        )
        print(f"state hash: {report.state_hash}")
    return SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _help([])
    if args[0] in {"--help", "-h"}:
        if len(args) != 1:
            print("error: --help does not accept additional arguments", file=sys.stderr)
            return INPUT_OR_CONFIG_ERROR
        return _help([])
    command, command_args = args[0], args[1:]
    commands = {
        "version": _version,
        "help": _help,
        "doctor": _doctor,
        "init": _init,
        "outline": _outline,
        "state": _state,
    }
    if command not in commands:
        print(f"error: unknown command: {command}", file=sys.stderr)
        return INPUT_OR_CONFIG_ERROR
    try:
        return commands[command](command_args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
