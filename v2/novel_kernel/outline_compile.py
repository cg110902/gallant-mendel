"""M2.4 deterministic Outline compilation and atomic generation publication."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .outline import OutlineError, OutlineValidationReport, StructuredLoaderRegistry
from .outline_domain import OutlineDomainValidator
from .outline_semantics import DECLARATIONS
from .storage import atomic_write_json, canonical_json_bytes, sha256_bytes

COMPILER_SCHEMA = "outline.compiled.v1"
COMPILER_VERSION = "m2.4.1"
LOGICAL_PATHS = (
    "objects.json", "initial-state.json", "obligations.json", "timeline.json",
    "intent-ledger.json", "production-manifest.yaml", "compile-report.md",
)


class OutlineCompileEnvironmentError(OutlineError):
    exit_code = 5


class OutlineCompileIntegrityError(OutlineError):
    exit_code = 6


class OutlineCompileBusyError(OutlineError):
    exit_code = 7


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    schema_version: str
    book_id: str
    compile_id: str
    source_package_hash: str
    generation_path: str
    current_path: str
    artifact_count: int
    artifact_index_hash: str
    reused_generation: bool
    previous_compile_id: str | None


class _CompileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "_CompileLock":
        try:
            self.stream = self.path.open("a+b")
            if os.name == "posix":
                import fcntl
                try:
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise OutlineCompileBusyError(f"outline compilation is already running: {self.path}") from exc
            return self
        except OutlineError:
            if self.stream is not None:
                self.stream.close()
            raise
        except OSError as exc:
            raise OutlineCompileEnvironmentError(f"cannot acquire compile lock {self.path}: {exc}") from exc

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.stream is not None:
            if os.name == "posix":
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()


class OutlineCompiler:
    def __init__(
        self,
        validator: OutlineDomainValidator | None = None,
        loaders: StructuredLoaderRegistry | None = None,
    ) -> None:
        self.validator = validator or OutlineDomainValidator()
        self.loaders = loaders or StructuredLoaderRegistry()

    def compile(
        self,
        package_path: Path | str,
        *,
        expected_book_id: str | None = None,
        _before_pointer: Callable[[], None] | None = None,
    ) -> CompileResult:
        report = self.validator.validate(package_path, expected_book_id=expected_book_id)
        outline_root = Path(report.package_path)
        book_root = outline_root.parent
        compiled = book_root / "compiled"
        self._prepare_directory(compiled, "compiled")
        generations = compiled / "generations"
        self._prepare_directory(generations, "compiled/generations")

        with _CompileLock(compiled / ".compile.lock"):
            previous_compile_id = self._read_previous(compiled / "current.json")
            documents = self._load_documents(report)
            logical = self._build_logical_artifacts(report, documents)
            preimage = {
                "schema_version": COMPILER_SCHEMA,
                "compiler_version": COMPILER_VERSION,
                "book_id": report.book_id,
                "source_package_hash": report.package_hash,
                "artifacts": [
                    {"path": path, "sha256": sha256_bytes(data), "bytes": len(data)}
                    for path, data in sorted(logical.items())
                ],
            }
            compile_id = sha256_bytes(canonical_json_bytes(preimage))
            production_manifest = {
                "schema_version": "production-manifest.v1",
                "compiler_schema": COMPILER_SCHEMA,
                "compiler_version": COMPILER_VERSION,
                "book_id": report.book_id,
                "source_package_hash": report.package_hash,
                "compile_id": compile_id,
                "status": "compiled",
                "artifact_index": "artifact-index.json",
            }
            logical["production-manifest.yaml"] = canonical_json_bytes(production_manifest)
            entries = [
                {"path": path, "bytes": len(data), "sha256": sha256_bytes(data)}
                for path, data in sorted(logical.items())
            ]
            artifact_index = {
                "schema_version": "outline.artifact-index.v1",
                "book_id": report.book_id,
                "compile_id": compile_id,
                "source_package_hash": report.package_hash,
                "artifacts": entries,
            }
            index_bytes = canonical_json_bytes(artifact_index)
            all_files = dict(logical)
            all_files["artifact-index.json"] = index_bytes
            generation = generations / compile_id.removeprefix("sha256:")
            reused = generation.exists()
            installed_new = False
            if reused:
                self._verify_generation(generation, all_files)
            else:
                installed_new = self._install_generation(compiled, generation, all_files)
            pointer = {
                "schema_version": "outline.current.v1",
                "book_id": report.book_id,
                "compile_id": compile_id,
                "source_package_hash": report.package_hash,
                "generation": f"generations/{generation.name}",
                "artifact_index_hash": sha256_bytes(index_bytes),
            }
            try:
                if _before_pointer is not None:
                    _before_pointer()
                atomic_write_json(compiled / "current.json", pointer, mode=0o600)
            except Exception as exc:
                if installed_new:
                    shutil.rmtree(generation, ignore_errors=True)
                if isinstance(exc, OutlineError):
                    raise
                from .storage import StorageError
                if isinstance(exc, StorageError):
                    raise OutlineCompileEnvironmentError(f"cannot publish compiled current pointer: {exc}") from exc
                raise
            return CompileResult(
                ok=True,
                schema_version=COMPILER_SCHEMA,
                book_id=report.book_id,
                compile_id=compile_id,
                source_package_hash=report.package_hash,
                generation_path=str(generation.resolve()),
                current_path=str((compiled / "current.json").resolve()),
                artifact_count=len(entries),
                artifact_index_hash=sha256_bytes(index_bytes),
                reused_generation=reused,
                previous_compile_id=previous_compile_id,
            )

    @staticmethod
    def _prepare_directory(path: Path, label: str) -> None:
        if path.is_symlink():
            raise OutlineCompileEnvironmentError(f"symbolic link is forbidden for {label}: {path}")
        try:
            path.mkdir(parents=False, exist_ok=True)
        except OSError as exc:
            raise OutlineCompileEnvironmentError(f"cannot create {label}: {exc}") from exc
        if not path.is_dir():
            raise OutlineCompileEnvironmentError(f"{label} is not a directory: {path}")

    @staticmethod
    def _read_previous(path: Path) -> str | None:
        if path.is_symlink():
            raise OutlineCompileIntegrityError(f"compiled current pointer is a symbolic link: {path}")
        if not path.exists():
            return None
        if not path.is_file():
            raise OutlineCompileIntegrityError(f"compiled current pointer is not a file: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OutlineCompileIntegrityError(f"compiled current pointer is unreadable: {exc}") from exc
        compile_id = value.get("compile_id") if isinstance(value, dict) else None
        if not isinstance(compile_id, str) or not compile_id.startswith("sha256:") or len(compile_id) != 71:
            raise OutlineCompileIntegrityError("compiled current pointer has invalid compile_id")
        expected_generation = f"generations/{compile_id.removeprefix('sha256:')}"
        if value.get("generation") != expected_generation:
            raise OutlineCompileIntegrityError("compiled current pointer generation does not match compile_id")
        generation = path.parent / expected_generation
        if generation.is_symlink() or not generation.is_dir():
            raise OutlineCompileIntegrityError(f"current compiled generation is unavailable: {generation}")
        index_path = generation / "artifact-index.json"
        if index_path.is_symlink() or not index_path.is_file():
            raise OutlineCompileIntegrityError("current generation artifact index is unavailable")
        try:
            index_bytes = index_path.read_bytes()
            index = json.loads(index_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise OutlineCompileIntegrityError(f"current generation artifact index is unreadable: {exc}") from exc
        if sha256_bytes(index_bytes) != value.get("artifact_index_hash"):
            raise OutlineCompileIntegrityError("current generation artifact index hash mismatch")
        if not isinstance(index, dict) or index.get("compile_id") != compile_id or not isinstance(index.get("artifacts"), list):
            raise OutlineCompileIntegrityError("current generation artifact index metadata mismatch")
        expected_names = {"artifact-index.json"}
        for artifact in index["artifacts"]:
            if not isinstance(artifact, dict) or set(artifact) != {"path", "bytes", "sha256"}:
                raise OutlineCompileIntegrityError("current generation has malformed artifact entry")
            name = artifact["path"]
            if name not in LOGICAL_PATHS or name in expected_names:
                raise OutlineCompileIntegrityError(f"current generation has invalid artifact path: {name!r}")
            expected_names.add(name)
            artifact_path = generation / name
            if artifact_path.is_symlink() or not artifact_path.is_file():
                raise OutlineCompileIntegrityError(f"current generation artifact is unavailable: {name}")
            try:
                data = artifact_path.read_bytes()
            except OSError as exc:
                raise OutlineCompileIntegrityError(f"current generation artifact is unreadable: {name}: {exc}") from exc
            if len(data) != artifact["bytes"] or sha256_bytes(data) != artifact["sha256"]:
                raise OutlineCompileIntegrityError(f"current generation artifact integrity mismatch: {name}")
        required_names = set(LOGICAL_PATHS) | {"artifact-index.json"}
        if expected_names != required_names:
            raise OutlineCompileIntegrityError("current generation artifact index does not declare the fixed file set")
        if expected_names != {item.name for item in generation.iterdir()}:
            raise OutlineCompileIntegrityError("current generation contains undeclared artifacts")
        return compile_id

    def _load_documents(self, report: OutlineValidationReport) -> dict[str, Any]:
        root = Path(report.package_path)
        files = {item.role: root / item.path for item in report.files if item.role in DECLARATIONS}
        return {role: self.loaders.load(path) for role, path in files.items()}

    @staticmethod
    def _records(document: Any, wrappers: tuple[str, ...]) -> list[dict[str, Any]]:
        if isinstance(document, list):
            return document
        if not document:
            return []
        if "id" in document:
            return [document]
        return next(document[key] for key in wrappers if key in document)

    def _build_logical_artifacts(
        self, report: OutlineValidationReport, documents: dict[str, Any]
    ) -> dict[str, bytes]:
        records = {
            role: self._records(documents[role], DECLARATIONS[role][1])
            for role in DECLARATIONS
        }
        role_types = {
            "04-cast": "character", "05-factions": "faction", "06-places": "place",
            "07-items": "item", "09-threads": "thread", "11-arcs": "arc",
            "12-chapter-map": "chapter",
        }
        objects: list[dict[str, Any]] = []
        for role, object_type in role_types.items():
            for record in records[role]:
                objects.append({
                    "object_id": record["id"], "object_type": object_type,
                    "source_ref": f"outline/{role}#{record['id']}", "data": record,
                })
                if role == "12-chapter-map":
                    for beat in record.get("beats", []):
                        objects.append({
                            "object_id": beat["id"], "object_type": "beat",
                            "source_ref": f"outline/{role}#{record['id']}/beats/{beat['id']}", "data": beat,
                        })
        objects.sort(key=lambda item: item["object_id"])

        initial_characters = [
            {"character_id": record["id"], "state": record["initial_state"]}
            for record in records["04-cast"]
        ]
        initial_items = []
        for record in records["07-items"]:
            holder_field = next(field for field in ("current_holder", "holder", "owner") if field in record)
            initial_items.append({"item_id": record["id"], "holder_id": record[holder_field]})
        initial_places = []
        for record in records["06-places"]:
            owner_field = next(field for field in ("faction", "faction_id", "owner_faction") if field in record)
            initial_places.append({"place_id": record["id"], "faction_id": record[owner_field]})
        initial_state = {
            "schema_version": "outline.initial-state.v1", "book_id": report.book_id,
            "authority": False, "characters": sorted(initial_characters, key=lambda item: item["character_id"]),
            "items": sorted(initial_items, key=lambda item: item["item_id"]),
            "places": sorted(initial_places, key=lambda item: item["place_id"]),
        }
        obligations = {
            "schema_version": "outline.obligations.v1", "book_id": report.book_id,
            "obligations": sorted(records["10-obligations"], key=lambda item: item["id"]),
        }
        timeline = {
            "schema_version": "outline.timeline.v1", "book_id": report.book_id,
            "events": sorted(records["08-timeline"], key=lambda item: item["id"]),
            "chapter_times": sorted(
                [{"chapter_id": item["id"], "time": item["time"]} for item in records["12-chapter-map"]],
                key=lambda item: item["chapter_id"],
            ),
        }
        ledger = {
            "schema_version": "outline.intent-ledger.v1", "book_id": report.book_id,
            "chapters": sorted(
                [{"chapter_id": item["id"], "intent": item["intent"]} for item in records["12-chapter-map"]],
                key=lambda item: item["chapter_id"],
            ),
        }
        report_text = self._compile_report(report, objects, records)
        return {
            "objects.json": canonical_json_bytes({
                "schema_version": "outline.objects.v1", "book_id": report.book_id, "objects": objects,
            }),
            "initial-state.json": canonical_json_bytes(initial_state),
            "obligations.json": canonical_json_bytes(obligations),
            "timeline.json": canonical_json_bytes(timeline),
            "intent-ledger.json": canonical_json_bytes(ledger),
            "compile-report.md": report_text.encode("utf-8"),
        }

    @staticmethod
    def _compile_report(
        report: OutlineValidationReport,
        objects: list[dict[str, Any]],
        records: dict[str, list[dict[str, Any]]],
    ) -> str:
        return "\n".join([
            "# Outline compile report", "", "- Decision: **PASS**",
            f"- Book: `{report.book_id}`", f"- Source package hash: `{report.package_hash}`",
            f"- Compiler schema: `{COMPILER_SCHEMA}`", f"- Objects: `{len(objects)}`",
            f"- Timeline events: `{len(records['08-timeline'])}`",
            f"- Obligations: `{len(records['10-obligations'])}`",
            f"- Chapters: `{len(records['12-chapter-map'])}`", "- Authority events created: `0`", "",
        ])

    @staticmethod
    def _install_generation(
        compiled: Path, generation: Path, files: dict[str, bytes]
    ) -> bool:
        temporary = compiled / f".generation-{uuid.uuid4().hex}.tmp"
        try:
            temporary.mkdir(mode=0o700)
            for name, data in sorted(files.items()):
                path = temporary / name
                with path.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if path.read_bytes() != data:
                    raise OutlineCompileIntegrityError(f"staged artifact verification failed: {name}")
            if os.name == "posix":
                descriptor = os.open(temporary, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
            try:
                os.replace(temporary, generation)
            except OSError:
                if generation.is_dir():
                    shutil.rmtree(temporary, ignore_errors=True)
                    OutlineCompiler._verify_generation(generation, files)
                    return False
                raise
            if os.name == "posix":
                descriptor = os.open(generation.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return True
        except OutlineError:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            raise OutlineCompileEnvironmentError(f"cannot install compiled generation: {exc}") from exc

    @staticmethod
    def _verify_generation(generation: Path, files: dict[str, bytes]) -> None:
        if generation.is_symlink() or not generation.is_dir():
            raise OutlineCompileIntegrityError(f"compiled generation is not a regular directory: {generation}")
        actual_names = {path.name for path in generation.iterdir()}
        if actual_names != set(files):
            raise OutlineCompileIntegrityError(
                f"compiled generation file set mismatch: expected {sorted(files)}, got {sorted(actual_names)}"
            )
        for name, expected in sorted(files.items()):
            path = generation / name
            if path.is_symlink() or not path.is_file():
                raise OutlineCompileIntegrityError(f"compiled artifact is not a regular file: {path}")
            try:
                actual = path.read_bytes()
            except OSError as exc:
                raise OutlineCompileIntegrityError(f"cannot read compiled artifact {path}: {exc}") from exc
            if actual != expected:
                raise OutlineCompileIntegrityError(
                    f"compiled artifact bytes do not match content-addressed generation: {path}"
                )
