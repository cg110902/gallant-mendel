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
  knowledge diff (--book ID | --path PATH) --holder CHARACTER --as-of SELECTOR
                 [--valid-at STORY_TIME] [--branch ID] [--json]
                                      Query M3.2 character/reader knowledge boundaries
  obligation list (--book ID | --path PATH) --as-of SELECTOR
                  [--status FILTER] [--branch ID] [--json]
                                      Query M3.3 Future Obligation lifecycle
  reconcile diff (--book ID | --path PATH) --scope ID --as-of SELECTOR
                 [--branch ID] [--json]
                                      Query M3.4 Intent/Reality classifications
  reader tension (--book ID | --path PATH) --holder ID --as-of CHAPTER --window N [--json]
  impact analyze (--book ID | --path PATH) --object ID --as-of SELECTOR [--depth N] [--json]
                                      Query M3.5 deterministic analytics

Examples:
  python studio.py version --json
  python studio.py doctor --no-api-key
  python studio.py init --path workspace/book_demo
  python studio.py outline validate --book book_demo
  python studio.py outline compile --book book_demo
  python studio.py outline bootstrap --book book_demo
  python studio.py outline readiness --book book_demo
  python studio.py state query --book book_demo --as-of ch_001
  python studio.py knowledge diff --book book_demo --holder char_hero --as-of ch_001
  python studio.py obligation list --book book_demo --as-of ch_001 --status active

M3.1–M3.3 queries are read-only and keep truth, knowledge, obligations, and time axes separate.
""",
        "version": "Usage: python studio.py version [--json]",
        "help": "Usage: python studio.py help [version|help|doctor|init|outline|state|knowledge|obligation|reconcile|reader|impact]",
        "doctor": (
            "Usage: python studio.py doctor [--no-api-key] [--json] "
            "[--fixture PATH] [--write-probe PATH]"
        ),
        "init": "Usage: python studio.py init --path PATH [--force]",
        "outline": "Usage: python studio.py outline (validate|compile|bootstrap|readiness) (--book ID | --path PATH) [--json]",
        "state": "Usage: python studio.py state query (--book ID | --path PATH) --as-of SELECTOR [--valid-at STORY_TIME] [--branch ID] [--json]",
        "knowledge": "Usage: python studio.py knowledge diff (--book ID | --path PATH) --holder CHARACTER --as-of SELECTOR [--valid-at STORY_TIME] [--branch ID] [--json]",
        "obligation": "Usage: python studio.py obligation list (--book ID | --path PATH) --as-of SELECTOR [--status FILTER] [--branch ID] [--json]",
        "reconcile": "Usage: python studio.py reconcile diff ... | reconcile (--book ID | --path PATH) --run ID [--json]",
        "reader": "Usage: python studio.py reader tension (--book ID | --path PATH) --holder ID --as-of CHAPTER --window N [--branch ID] [--json]",
        "impact": "Usage: python studio.py impact analyze (--book ID | --path PATH) --object ID --as-of SELECTOR [--depth N] [--branch ID] [--json]",
        "plan": "Usage: python studio.py plan chapter (--book ID | --path PATH) --chapter ID [--json]",
        "context": "Usage: python studio.py context build (--book ID | --path PATH) --run ID [--json]",
        "run": "Usage: python studio.py run (start --task ID | status|resume|abort|review --run ID | decide --run ID --decision approve|rework --actor ID) (--book ID | --path PATH) [--runtime NAME] [--note TEXT] [--json]",
        "extract": "Usage: python studio.py extract (--book ID | --path PATH) --run ID [--json]",
        "audit": "Usage: python studio.py audit hard|semantic|style ... | audit gate ... --decision approve|rework --actor ID",
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


def _knowledge(args: Sequence[str]) -> int:
    if not args or args[0] != "diff":
        raise CliError("knowledge currently supports only: knowledge diff")
    values: dict[str, str] = {}
    json_mode = False
    index = 1
    value_options = {"--book", "--path", "--holder", "--as-of", "--valid-at", "--branch"}
    while index < len(args):
        option = args[index]
        if option in value_options:
            if option in values:
                raise CliError(f"duplicate option: {option}")
            if index + 1 >= len(args):
                raise CliError(f"{option} requires a value")
            values[option] = args[index + 1]
            index += 2
            continue
        if option == "--json":
            if json_mode:
                raise CliError("duplicate option: --json")
            json_mode = True
            index += 1
            continue
        raise CliError(f"unsupported option: {option}")
    if ("--book" in values) == ("--path" in values):
        raise CliError("knowledge diff requires exactly one of --book ID or --path PATH")
    if "--holder" not in values or "--as-of" not in values:
        raise CliError("knowledge diff requires --holder CHARACTER and --as-of SELECTOR")

    from novel_kernel.events import BOOK_ID_RE, BRANCH_ID_RE
    book_id = values.get("--book")
    branch = values.get("--branch", "main")
    if book_id is not None and BOOK_ID_RE.fullmatch(book_id) is None:
        raise CliError("--book must match book_<lowercase-id>")
    if BRANCH_ID_RE.fullmatch(branch) is None:
        raise CliError("--branch has an invalid identifier")
    root = Path(values["--path"]) if "--path" in values else ROOT / "workspace" / book_id

    from dataclasses import asdict
    from novel_kernel.knowledge import KnowledgeBoundaryQuery
    from novel_kernel.outline import OutlineError
    try:
        report = KnowledgeBoundaryQuery().query(
            root,
            holder_id=values["--holder"],
            as_of=values["--as-of"],
            valid_at=values.get("--valid-at"),
            branch_id=branch,
        )
    except OutlineError as exc:
        if json_mode:
            print(_json_dump({"ok": False, "exit_code": exc.exit_code, "error": str(exc)}))
        else:
            print(f"knowledge diff error: {exc}", file=sys.stderr)
        return exc.exit_code
    if json_mode:
        print(_json_dump(asdict(report)))
    else:
        print(
            f"knowledge PASS book={report.book_id} holder={report.holder_id} "
            f"as_of={report.cutoff['selector']}"
        )
        print(
            f"holder={len(report.holder_edges)} reader={len(report.reader_edges)} "
            f"reader_only={len(report.reader_only)} hidden_truth={len(report.hidden_truth)}"
        )
        print(f"knowledge hash: {report.knowledge_hash}")
    return SUCCESS


def _obligation(args: Sequence[str]) -> int:
    if not args or args[0] != "list":
        raise CliError("obligation currently supports only: obligation list")
    values: dict[str, str] = {}
    json_mode = False
    index = 1
    value_options = {"--book", "--path", "--as-of", "--status", "--branch"}
    while index < len(args):
        option = args[index]
        if option in value_options:
            if option in values:
                raise CliError(f"duplicate option: {option}")
            if index + 1 >= len(args):
                raise CliError(f"{option} requires a value")
            values[option] = args[index + 1]
            index += 2
            continue
        if option == "--json":
            if json_mode:
                raise CliError("duplicate option: --json")
            json_mode = True
            index += 1
            continue
        raise CliError(f"unsupported option: {option}")
    if ("--book" in values) == ("--path" in values):
        raise CliError("obligation list requires exactly one of --book ID or --path PATH")
    if "--as-of" not in values:
        raise CliError("obligation list requires --as-of SELECTOR")

    from novel_kernel.events import BOOK_ID_RE, BRANCH_ID_RE
    book_id = values.get("--book")
    branch = values.get("--branch", "main")
    if book_id is not None and BOOK_ID_RE.fullmatch(book_id) is None:
        raise CliError("--book must match book_<lowercase-id>")
    if BRANCH_ID_RE.fullmatch(branch) is None:
        raise CliError("--branch has an invalid identifier")
    root = Path(values["--path"]) if "--path" in values else ROOT / "workspace" / book_id

    from dataclasses import asdict
    from novel_kernel.obligations import ObligationStateQuery
    from novel_kernel.outline import OutlineError
    try:
        report = ObligationStateQuery().query(
            root,
            as_of=values["--as-of"],
            status=values.get("--status"),
            branch_id=branch,
        )
    except OutlineError as exc:
        if json_mode:
            print(_json_dump({"ok": False, "exit_code": exc.exit_code, "error": str(exc)}))
        else:
            print(f"obligation list error: {exc}", file=sys.stderr)
        return exc.exit_code
    if json_mode:
        print(_json_dump(asdict(report)))
    else:
        print(
            f"obligation PASS book={report.book_id} as_of={report.cutoff['selector']} "
            f"filter={report.status_filter or 'all'}"
        )
        print(
            f"returned={len(report.obligations)} active={report.active_count} "
            f"terminal={report.terminal_count} due={report.due_count} overdue={report.overdue_count}"
        )
        print(f"obligation hash: {report.obligation_hash}")
    return SUCCESS


def _candidate_reconcile_cli(args:Sequence[str])->int:
    values={};json_mode=False;i=0
    while i<len(args):
        key=args[i]
        if key in {"--book","--path","--run"}:
            if key in values or i+1>=len(args):raise CliError(f"invalid option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values) or "--run" not in values:raise CliError("reconcile requires exactly one book/path and --run")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.candidate_reconcile import CandidateReconciler
    from novel_kernel.outline import OutlineError
    try:report=CandidateReconciler().reconcile(root,run_id=values["--run"])
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"reconcile error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"reconcile {'PASS' if report.ok else 'GATED'} run={report.run_id} state={report.state}")
    return 3 if report.has_hard_violation else (4 if report.requires_human_review else SUCCESS)


def _reconcile(args: Sequence[str]) -> int:
    if not args or args[0] != "diff": return _candidate_reconcile_cli(args)
    values: dict[str,str]={}; json_mode=False; index=1; options={"--book","--path","--scope","--as-of","--branch"}
    while index<len(args):
        option=args[index]
        if option in options:
            if option in values: raise CliError(f"duplicate option: {option}")
            if index+1>=len(args): raise CliError(f"{option} requires a value")
            values[option]=args[index+1]; index+=2; continue
        if option=="--json":
            if json_mode: raise CliError("duplicate option: --json")
            json_mode=True; index+=1; continue
        raise CliError(f"unsupported option: {option}")
    if ("--book" in values)==("--path" in values): raise CliError("reconcile diff requires exactly one of --book or --path")
    if "--scope" not in values or "--as-of" not in values: raise CliError("reconcile diff requires --scope and --as-of")
    from novel_kernel.events import BOOK_ID_RE,BRANCH_ID_RE
    book=values.get("--book"); branch=values.get("--branch","main")
    if book is not None and BOOK_ID_RE.fullmatch(book) is None: raise CliError("--book must match book_<lowercase-id>")
    if BRANCH_ID_RE.fullmatch(branch) is None: raise CliError("--branch has an invalid identifier")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/book
    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    from novel_kernel.reconcile import IntentRealityQuery
    try: report=IntentRealityQuery().query(root,scope_id=values["--scope"],as_of=values["--as-of"],branch_id=branch)
    except OutlineError as exc:
        if json_mode: print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else: print(f"reconcile diff error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode: print(_json_dump(asdict(report)))
    else:
        print(f"reconcile PASS book={report.book_id} scope={report.scope_id} as_of={report.cutoff['selector']}")
        print(f"classifications={len(report.classifications)} hard_violation={report.has_hard_violation}")
        print(f"diff hash: {report.diff_hash}")
    return SUCCESS


def _analytics(command: str, args: Sequence[str]) -> int:
    expected = "tension" if command == "reader" else "analyze"
    if not args or args[0] != expected: raise CliError(f"{command} supports only: {command} {expected}")
    values: dict[str,str]={}; json_mode=False; i=1
    allowed={"--book","--path","--holder","--object","--as-of","--window","--depth","--branch"}
    while i<len(args):
        key=args[i]
        if key in allowed:
            if key in values or i+1>=len(args): raise CliError(f"invalid or duplicate option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values) or "--as-of" not in values:raise CliError(f"{command} requires one book/path and --as-of")
    branch=values.get("--branch","main");root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.analytics import ImpactQuery,ReaderTensionQuery
    from novel_kernel.outline import OutlineError
    try:
        if command=="reader":
            if "--holder" not in values or "--window" not in values:raise CliError("reader tension requires --holder and --window")
            try: window=int(values["--window"])
            except ValueError:raise CliError("--window must be an integer")
            report=ReaderTensionQuery().query(root,holder_id=values["--holder"],as_of=values["--as-of"],window=window,branch_id=branch)
        else:
            if "--object" not in values:raise CliError("impact analyze requires --object")
            try: depth=int(values.get("--depth","3"))
            except ValueError:raise CliError("--depth must be an integer")
            report=ImpactQuery().query(root,object_id=values["--object"],as_of=values["--as-of"],depth=depth,branch_id=branch)
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"{command} error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"{command} PASS hash={getattr(report,'tension_hash',getattr(report,'impact_hash',''))}")
    return SUCCESS


def _reader(args: Sequence[str]) -> int: return _analytics("reader",args)
def _impact(args: Sequence[str]) -> int: return _analytics("impact",args)


def _production(command: str,args: Sequence[str])->int:
    expected="chapter" if command=="plan" else "build"
    if not args or args[0]!=expected:raise CliError(f"{command} supports only {expected}")
    values={};json_mode=False;i=1
    while i<len(args):
        key=args[i]
        if key in {"--book","--path","--chapter","--run"}:
            if key in values or i+1>=len(args):raise CliError(f"invalid option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values):raise CliError("exactly one of --book/--path is required")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    from novel_kernel.production import ContextPackBuilder,ProductionPlanner
    try:
        if command=="plan":
            if "--chapter" not in values:raise CliError("--chapter is required")
            report=ProductionPlanner().plan(root,chapter_id=values["--chapter"])
        else:
            if "--run" not in values:raise CliError("--run is required")
            report=ContextPackBuilder().build(root,run_id=values["--run"])
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"{command} error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"{command} PASS run={report.run_id} state={report.state}")
    return SUCCESS

def _plan(args):return _production("plan",args)
def _context(args):return _production("context",args)

def _run(args:Sequence[str])->int:
    if not args or args[0] not in {"start","status","resume","abort","review","decide"}:raise CliError("run requires start, status, resume, abort, review, or decide")
    action=args[0];values={};json_mode=False;i=1
    while i<len(args):
        key=args[i]
        if key in {"--book","--path","--task","--run","--runtime","--decision","--actor","--note"}:
            if key in values or i+1>=len(args):raise CliError(f"invalid option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values):raise CliError("exactly one of --book/--path is required")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    from novel_kernel.writer_runtime import WriterRunController
    controller=WriterRunController();runtime=values.get("--runtime","offline")
    try:
        if action=="start":
            if "--task" not in values:raise CliError("run start requires --task")
            report=controller.start_task(root,task_id=values["--task"],runtime_name=runtime)
        else:
            if "--run" not in values:raise CliError(f"run {action} requires --run")
            if action=="status":report=controller.status(root,run_id=values["--run"])
            elif action=="resume":report=controller.resume(root,run_id=values["--run"],runtime_name=runtime)
            elif action=="abort":report=controller.abort(root,run_id=values["--run"])
            elif action=="review":report=controller.request_review(root,run_id=values["--run"])
            else:
                if "--decision" not in values or "--actor" not in values:raise CliError("run decide requires --decision and --actor")
                report=controller.decide_review(root,run_id=values["--run"],decision=values["--decision"],actor=values["--actor"],note=values.get("--note",""))
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"run {action} error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"run {action} {'PASS' if report.ok else 'FAIL'} run={report.run_id} state={report.state}")
    return SUCCESS if report.ok else INPUT_OR_CONFIG_ERROR


def _extract(args:Sequence[str])->int:
    values={};json_mode=False;i=0
    while i<len(args):
        key=args[i]
        if key in {"--book","--path","--run"}:
            if key in values or i+1>=len(args):raise CliError(f"invalid option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values) or "--run" not in values:raise CliError("extract requires exactly one book/path and --run")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.extraction import CandidateExtractor
    from novel_kernel.outline import OutlineError
    try:report=CandidateExtractor().extract(root,run_id=values["--run"])
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"extract error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"extract PASS run={report.run_id} claims={report.claim_count} evidence={report.evidence_count}")
    return SUCCESS


def _audit(args:Sequence[str])->int:
    if not args or args[0] not in {"hard","semantic","style","gate"}:raise CliError("audit requires hard, semantic, style, or gate")
    action=args[0];values={};json_mode=False;i=1
    while i<len(args):
        key=args[i]
        if key in {"--book","--path","--run","--decision","--actor","--note"}:
            if key in values or i+1>=len(args):raise CliError(f"invalid option: {key}")
            values[key]=args[i+1];i+=2;continue
        if key=="--json" and not json_mode:json_mode=True;i+=1;continue
        raise CliError(f"unsupported option: {key}")
    if ("--book" in values)==("--path" in values) or "--run" not in values:raise CliError(f"audit {action} requires exactly one book/path and --run")
    root=Path(values["--path"]) if "--path" in values else ROOT/"workspace"/values["--book"]
    from dataclasses import asdict
    from novel_kernel.outline import OutlineError
    try:
        if action=="hard":
            from novel_kernel.hard_audit import HardInvariantAuditor
            report=HardInvariantAuditor().audit(root,run_id=values["--run"])
        else:
            from novel_kernel.soft_audit import SoftAuditor
            auditor=SoftAuditor()
            if action=="semantic":report=auditor.semantic(root,run_id=values["--run"])
            elif action=="style":report=auditor.style(root,run_id=values["--run"])
            else:
                if "--decision" not in values or "--actor" not in values:raise CliError("audit gate requires --decision and --actor")
                report=auditor.gate(root,run_id=values["--run"],decision=values["--decision"],actor=values["--actor"],note=values.get("--note",""))
    except OutlineError as exc:
        if json_mode:print(_json_dump({"ok":False,"exit_code":exc.exit_code,"error":str(exc)}))
        else:print(f"audit {action} error: {exc}",file=sys.stderr)
        return exc.exit_code
    if json_mode:print(_json_dump(asdict(report)))
    else:print(f"audit {action} PASS run={report.run_id} state={report.state}")
    if action=="hard":return 3 if report.has_hard_violation else (4 if report.requires_human_review else SUCCESS)
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
        "knowledge": _knowledge,
        "obligation": _obligation,
        "reconcile": _reconcile,
        "reader": _reader,
        "impact": _impact,
        "plan": _plan,
        "context": _context,
        "run": _run,
        "extract": _extract,
        "audit": _audit,
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
