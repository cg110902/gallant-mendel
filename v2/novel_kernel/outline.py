"""Outline Package v1 layout, loader, and manifest validation (M2.1 only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from .storage import canonical_json_bytes, sha256_file, sha256_json

STRUCTURED_STEMS = (
    "00-manifest",
    "02-theme",
    "03-world",
    "04-cast",
    "05-factions",
    "06-places",
    "07-items",
    "08-timeline",
    "09-threads",
    "10-obligations",
    "11-arcs",
    "12-chapter-map",
    "13-style",
    "14-platform",
)
STRUCTURED_SUFFIXES = (".json", ".yaml", ".yml")
FIXED_ENTRIES = frozenset({"01-premise.md", "sources"})
MANIFEST_REQUIRED = frozenset(
    {"schema_version", "book_id", "title", "language", "planned_chapters", "canon_policy"}
)
MANIFEST_OPTIONAL = frozenset(
    {
        "genre_profile", "status", "planned_words", "chapter_word_range", "point_of_view",
        "tense", "created_at", "last_modified_at", "approval",
    }
)
BOOK_ID_RE = re.compile(r"^book_[a-z0-9][a-z0-9_-]{0,62}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class OutlineError(Exception):
    exit_code = 1


class OutlineLayoutError(OutlineError):
    exit_code = 1


class OutlineFormatError(OutlineError):
    exit_code = 2


class OutlineDependencyError(OutlineError):
    exit_code = 5


class StructuredDocumentLoader(Protocol):
    def load(self, path: Path) -> Any:
        """Load a structured document as a JSON-compatible value."""


class JsonDocumentLoader:
    @staticmethod
    def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OutlineFormatError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def load(self, path: Path) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OutlineDependencyError(f"cannot read structured document {path}: {exc}") from exc
        try:
            value = json.loads(text, object_pairs_hook=self._pairs, parse_constant=self._reject_constant)
        except OutlineFormatError:
            raise
        except json.JSONDecodeError as exc:
            raise OutlineFormatError(
                f"invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        return _json_compatible(value, path.name)

    @staticmethod
    def _reject_constant(value: str) -> Any:
        raise OutlineFormatError(f"non-standard JSON constant is forbidden: {value}")


class OptionalYamlDocumentLoader:
    def load(self, path: Path) -> Any:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OutlineDependencyError(
                f"YAML input requires an optional YAML adapter; use equivalent JSON or install a supported adapter: {path.name}"
            ) from exc
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OutlineDependencyError(f"cannot read structured document {path}: {exc}") from exc
        class JsonCompatibleSafeLoader(yaml.SafeLoader):
            pass

        # PyYAML otherwise converts an unquoted ISO date (used by the canonical
        # author format) into datetime.date, which is not a JSON-compatible
        # protocol value. Keep timestamps as strings without weakening other
        # safe-loader rules or mutating the process-global SafeLoader.
        JsonCompatibleSafeLoader.yaml_implicit_resolvers = {
            key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
            for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }

        def unique_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
            result: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in result
                except TypeError as exc:
                    raise OutlineFormatError(f"unhashable YAML mapping key in {path.name}") from exc
                if duplicate:
                    raise OutlineFormatError(f"duplicate YAML mapping key in {path.name}: {key!r}")
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        JsonCompatibleSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
        )
        try:
            value = yaml.load(text, Loader=JsonCompatibleSafeLoader)
        except OutlineFormatError:
            raise
        except yaml.YAMLError as exc:
            raise OutlineFormatError(f"invalid YAML in {path.name}: {exc}") from exc
        return _json_compatible(value, path.name)


class StructuredLoaderRegistry:
    def __init__(self) -> None:
        self._loaders: dict[str, StructuredDocumentLoader] = {
            ".json": JsonDocumentLoader(),
            ".yaml": OptionalYamlDocumentLoader(),
            ".yml": OptionalYamlDocumentLoader(),
        }

    def load(self, path: Path) -> Any:
        loader = self._loaders.get(path.suffix.lower())
        if loader is None:
            raise OutlineLayoutError(f"unsupported structured document extension: {path.name}")
        return loader.load(path)


def _json_compatible(value: Any, label: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise OutlineFormatError(f"{label} is not JSON-compatible: {exc}") from exc


@dataclass(frozen=True)
class OutlineFile:
    path: str
    role: str
    format: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class OutlineValidationReport:
    ok: bool
    schema_version: str
    book_id: str
    package_path: str
    manifest_file: str
    structured_document_count: int
    source_file_count: int
    files: tuple[OutlineFile, ...]
    package_hash: str
    manifest: dict[str, Any]
    semantic: dict[str, Any] | None = None
    domain: dict[str, Any] | None = None


def _nonempty_string(value: Any, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutlineFormatError(f"manifest.{field} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise OutlineFormatError(f"manifest.{field} has invalid format: {value!r}")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OutlineFormatError(f"manifest.{field} must be a positive integer")
    return value


def _iso_date(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise OutlineFormatError(f"manifest.{field} must be an ISO 8601 string")
    try:
        if "T" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
    except ValueError as exc:
        raise OutlineFormatError(f"manifest.{field} is not ISO 8601: {value}") from exc
    return value


def validate_manifest(value: Any, *, expected_book_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OutlineFormatError("00-manifest must be a JSON object")
    keys = set(value)
    missing = MANIFEST_REQUIRED - keys
    extra = keys - MANIFEST_REQUIRED - MANIFEST_OPTIONAL
    if missing:
        raise OutlineFormatError(f"manifest is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise OutlineFormatError(f"manifest has unknown fields: {', '.join(sorted(extra))}")
    manifest = _json_compatible(value, "manifest")
    if manifest["schema_version"] != "outline.v1":
        raise OutlineFormatError(f"unsupported outline schema_version: {manifest['schema_version']!r}")
    book_id = _nonempty_string(manifest["book_id"], "book_id", BOOK_ID_RE)
    if expected_book_id is not None and book_id != expected_book_id:
        raise OutlineFormatError(
            f"manifest.book_id {book_id!r} does not match requested book {expected_book_id!r}"
        )
    _nonempty_string(manifest["title"], "title")
    _nonempty_string(manifest["language"], "language", LANGUAGE_RE)
    _positive_integer(manifest["planned_chapters"], "planned_chapters")
    policy = manifest["canon_policy"]
    if policy not in {"strict", "guided", "emergent_with_reconcile"}:
        raise OutlineFormatError(f"manifest.canon_policy has unsupported value: {policy!r}")

    for field in ("genre_profile", "point_of_view", "tense"):
        if field in manifest:
            _nonempty_string(manifest[field], field)
    if "status" in manifest and manifest["status"] not in {"draft", "approved", "frozen"}:
        raise OutlineFormatError(f"manifest.status has unsupported value: {manifest['status']!r}")
    if "planned_words" in manifest:
        _positive_integer(manifest["planned_words"], "planned_words")
    if "chapter_word_range" in manifest:
        word_range = manifest["chapter_word_range"]
        if not isinstance(word_range, list) or len(word_range) != 2:
            raise OutlineFormatError("manifest.chapter_word_range must contain exactly two integers")
        lower = _positive_integer(word_range[0], "chapter_word_range[0]")
        upper = _positive_integer(word_range[1], "chapter_word_range[1]")
        if lower > upper:
            raise OutlineFormatError("manifest.chapter_word_range lower bound exceeds upper bound")
    for field in ("created_at", "last_modified_at"):
        if field in manifest:
            _iso_date(manifest[field], field)
    approval = manifest.get("approval")
    if approval is not None:
        if not isinstance(approval, dict):
            raise OutlineFormatError("manifest.approval must be an object")
        approval_keys = set(approval)
        if approval_keys != {"owner", "approved_at"}:
            raise OutlineFormatError("manifest.approval must contain only owner and approved_at")
        _nonempty_string(approval["owner"], "approval.owner")
        _iso_date(approval["approved_at"], "approval.approved_at", nullable=True)
    if manifest.get("status") in {"approved", "frozen"}:
        if approval is None or approval["approved_at"] is None:
            raise OutlineFormatError("approved/frozen manifest requires approval.approved_at")
    return manifest


class OutlinePackageValidator:
    def __init__(self, loaders: StructuredLoaderRegistry | None = None) -> None:
        self.loaders = loaders or StructuredLoaderRegistry()

    def validate(
        self,
        package_path: Path | str,
        *,
        expected_book_id: str | None = None,
    ) -> OutlineValidationReport:
        root = Path(package_path)
        if root.is_symlink() or not root.is_dir():
            raise OutlineLayoutError(f"outline package is not a regular directory: {root}")
        if expected_book_id is not None and BOOK_ID_RE.fullmatch(expected_book_id) is None:
            raise OutlineLayoutError(f"requested book ID has invalid format: {expected_book_id}")

        try:
            entries = list(root.iterdir())
        except OSError as exc:
            raise OutlineDependencyError(f"cannot list outline package {root}: {exc}") from exc
        for entry in entries:
            if entry.is_symlink():
                raise OutlineLayoutError(f"symbolic links are forbidden in outline root: {entry.name}")

        selected: dict[str, Path] = {}
        allowed_names = set(FIXED_ENTRIES)
        for stem in STRUCTURED_STEMS:
            candidates = [root / f"{stem}{suffix}" for suffix in STRUCTURED_SUFFIXES]
            existing = [path for path in candidates if path.exists()]
            if not existing:
                raise OutlineLayoutError(f"required outline file is missing: {stem}.(json|yaml|yml)")
            if len(existing) != 1:
                raise OutlineLayoutError(
                    f"outline file has ambiguous duplicate formats: {', '.join(path.name for path in existing)}"
                )
            path = existing[0]
            if path.is_symlink() or not path.is_file():
                raise OutlineLayoutError(f"outline entry is not a regular file: {path.name}")
            selected[stem] = path
            allowed_names.add(path.name)

        premise = root / "01-premise.md"
        sources = root / "sources"
        if premise.is_symlink() or not premise.is_file():
            raise OutlineLayoutError("required outline file is missing or invalid: 01-premise.md")
        if sources.is_symlink() or not sources.is_dir():
            raise OutlineLayoutError("required outline directory is missing or invalid: sources/")
        unknown = sorted(entry.name for entry in entries if entry.name not in allowed_names)
        if unknown:
            raise OutlineLayoutError(f"outline root contains unknown entries: {', '.join(unknown)}")

        source_paths: list[Path] = []
        for path in sources.rglob("*"):
            if path.is_symlink():
                raise OutlineLayoutError(f"symbolic links are forbidden in sources/: {path.relative_to(root)}")
            if path.is_file():
                source_paths.append(path)
            elif not path.is_dir():
                raise OutlineLayoutError(f"unsupported source entry: {path.relative_to(root)}")

        documents: dict[str, Any] = {}
        for stem, path in selected.items():
            value = self.loaders.load(path)
            if stem != "00-manifest" and not isinstance(value, (dict, list)):
                raise OutlineFormatError(f"{path.name} root must be an object or array")
            documents[stem] = value
        manifest = validate_manifest(documents["00-manifest"], expected_book_id=expected_book_id)
        try:
            premise.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OutlineDependencyError(f"cannot read 01-premise.md: {exc}") from exc

        files: list[OutlineFile] = []
        for stem in STRUCTURED_STEMS:
            path = selected[stem]
            files.append(
                OutlineFile(
                    path=path.name,
                    role=stem,
                    format=path.suffix.lower().lstrip("."),
                    bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                )
            )
        files.append(
            OutlineFile(
                path="01-premise.md",
                role="premise",
                format="markdown",
                bytes=premise.stat().st_size,
                sha256=sha256_file(premise),
            )
        )
        for path in sorted(source_paths, key=lambda item: item.relative_to(root).as_posix()):
            files.append(
                OutlineFile(
                    path=path.relative_to(root).as_posix(),
                    role="source",
                    format=path.suffix.lower().lstrip(".") or "binary",
                    bytes=path.stat().st_size,
                    sha256=sha256_file(path),
                )
            )
        package_hash = sha256_json(
            [
                {"path": item.path, "role": item.role, "format": item.format, "bytes": item.bytes, "sha256": item.sha256}
                for item in files
            ]
        )
        return OutlineValidationReport(
            ok=True,
            schema_version="outline.v1",
            book_id=manifest["book_id"],
            package_path=str(root.resolve()),
            manifest_file=selected["00-manifest"].name,
            structured_document_count=len(STRUCTURED_STEMS),
            source_file_count=len(source_paths),
            files=tuple(files),
            package_hash=package_hash,
            manifest=manifest,
        )
