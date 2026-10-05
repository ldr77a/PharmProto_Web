"""Verified, immutable SQLite snapshots used by the researcher runtime."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pharma_proto.errors import (
    DB_INTEGRITY_ERROR,
    DB_VERSION_ERROR,
    AppError,
)

SCHEMA_VERSION = 3  # 2: 역할층 표(lookup_role_*), 3: API 함량 구간별 희석제 범위(lookup_filler_pct_ranges)
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

SCHEMA_SQL = """
CREATE TABLE snapshot_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE kg_nodes (
    element_id TEXT PRIMARY KEY,
    labels_json TEXT NOT NULL,
    properties_json TEXT NOT NULL
) STRICT;

CREATE TABLE kg_relationships (
    element_id TEXT PRIMARY KEY,
    start_element_id TEXT NOT NULL,
    end_element_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    FOREIGN KEY(start_element_id) REFERENCES kg_nodes(element_id),
    FOREIGN KEY(end_element_id) REFERENCES kg_nodes(element_id)
) STRICT;

CREATE TABLE lookup_api_doses (
    ingredient_key TEXT NOT NULL,
    aggregation_mode TEXT NOT NULL,
    observation_index INTEGER NOT NULL,
    dose_mg REAL NOT NULL,
    PRIMARY KEY(ingredient_key, aggregation_mode, observation_index)
) STRICT;

CREATE TABLE lookup_pct_ranges (
    ingredient_key TEXT NOT NULL,
    aggregation_mode TEXT NOT NULL,
    n INTEGER NOT NULL,
    lo REAL,
    hi REAL,
    mean REAL,
    p5 REAL,
    p95 REAL,
    median REAL,
    identity_json TEXT,
    excluded_reason TEXT,
    PRIMARY KEY(ingredient_key, aggregation_mode)
) STRICT;

CREATE TABLE lookup_functions (
    ingredient_key TEXT PRIMARY KEY,
    function_name TEXT NOT NULL
) STRICT;

CREATE TABLE lookup_function_pct_ranges (
    function_name TEXT PRIMARY KEY,
    n INTEGER NOT NULL,
    lo REAL,
    hi REAL,
    mean REAL,
    p5 REAL,
    p95 REAL,
    median REAL
) STRICT;

CREATE TABLE lookup_ingredient_candidates (
    function_name TEXT NOT NULL,
    dosage_form_base TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY(function_name, dosage_form_base, ingredient_key)
) STRICT;

CREATE TABLE lookup_compatibility (
    api_name TEXT NOT NULL,
    excipient_name TEXT NOT NULL,
    formulation_id TEXT NOT NULL,
    source_type TEXT,
    PRIMARY KEY(api_name, excipient_name, formulation_id)
) STRICT;

CREATE TABLE lookup_function_catalog (
    function_name TEXT PRIMARY KEY,
    canonical_role TEXT,
    scope TEXT NOT NULL,
    support_status TEXT NOT NULL
) STRICT;

CREATE TABLE lookup_ingredient_monographs (
    ingredient_key TEXT NOT NULL,
    monograph_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    monograph_name TEXT NOT NULL,
    pdf_start_page INTEGER,
    pdf_end_page INTEGER,
    PRIMARY KEY(ingredient_key, monograph_id)
) STRICT;

CREATE TABLE lookup_ingredient_use_ranges (
    evidence_id TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    function_name TEXT NOT NULL,
    min_pct REAL,
    max_pct REAL,
    unit TEXT NOT NULL,
    dosage_form TEXT,
    application_raw TEXT,
    source_id TEXT NOT NULL,
    pdf_page INTEGER,
    review_status TEXT,
    PRIMARY KEY(ingredient_key, evidence_id)
) STRICT;

CREATE TABLE lookup_ingredient_properties (
    evidence_id TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    property_name TEXT NOT NULL,
    property_label_raw TEXT,
    value_text TEXT NOT NULL,
    section INTEGER,
    source_id TEXT NOT NULL,
    pdf_page INTEGER,
    review_status TEXT,
    PRIMARY KEY(ingredient_key, evidence_id)
) STRICT;

CREATE TABLE lookup_ingredient_stability (
    evidence_id TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    statement TEXT NOT NULL,
    section INTEGER,
    source_id TEXT NOT NULL,
    pdf_page INTEGER,
    review_status TEXT,
    PRIMARY KEY(ingredient_key, evidence_id)
) STRICT;

CREATE TABLE lookup_ingredient_incompatibilities (
    evidence_id TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    target_name TEXT NOT NULL,
    normalized_target_name TEXT NOT NULL,
    target_kind TEXT,
    section INTEGER,
    source_id TEXT NOT NULL,
    pdf_page INTEGER,
    review_status TEXT,
    PRIMARY KEY(ingredient_key, evidence_id, normalized_target_name)
) STRICT;

CREATE TABLE lookup_role_dictionary (
    ingredient_key TEXT PRIMARY KEY,
    primary_role TEXT,
    allowed_roles_json TEXT NOT NULL,
    review_status TEXT NOT NULL,
    ruleset_version TEXT NOT NULL
) STRICT;

CREATE TABLE lookup_role_candidates (
    role TEXT NOT NULL,
    dosage_form_base TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    rank INTEGER NOT NULL,
    formulation_count INTEGER NOT NULL,
    PRIMARY KEY(role, dosage_form_base, ingredient_key)
) STRICT;

CREATE TABLE lookup_role_pct_ranges (
    ingredient_key TEXT NOT NULL,
    role TEXT NOT NULL,
    n INTEGER NOT NULL,
    lo REAL,
    hi REAL,
    mean REAL,
    p5 REAL,
    p95 REAL,
    median REAL,
    PRIMARY KEY(ingredient_key, role)
) STRICT;

CREATE TABLE lookup_role_pct_sums (
    role TEXT PRIMARY KEY,
    n INTEGER NOT NULL,
    lo REAL,
    hi REAL,
    mean REAL,
    p5 REAL,
    p95 REAL,
    median REAL
) STRICT;

CREATE TABLE lookup_filler_pct_ranges (
    api_load_band TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    n INTEGER NOT NULL,
    lo REAL,
    hi REAL,
    mean REAL,
    p5 REAL,
    p95 REAL,
    median REAL,
    PRIMARY KEY(api_load_band, ingredient_key)
) STRICT;

CREATE INDEX idx_candidates_lookup
ON lookup_ingredient_candidates(function_name, dosage_form_base, rank);

CREATE INDEX idx_role_candidates_lookup
ON lookup_role_candidates(role, dosage_form_base, rank);

CREATE INDEX idx_monographs_ingredient
ON lookup_ingredient_monographs(ingredient_key);

CREATE INDEX idx_use_ranges_ingredient
ON lookup_ingredient_use_ranges(ingredient_key);

CREATE INDEX idx_properties_ingredient
ON lookup_ingredient_properties(ingredient_key);

CREATE INDEX idx_stability_ingredient
ON lookup_ingredient_stability(ingredient_key);

CREATE INDEX idx_incompatibilities_ingredient
ON lookup_ingredient_incompatibilities(ingredient_key);
"""


class SnapshotEncodingError(ValueError):
    """Raised when a graph value cannot be represented without loss."""


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=200)
    schema_version: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(ge=0)
    relationship_count: int = Field(ge=0)


@dataclass
class VerifiedSnapshot:
    connection: sqlite3.Connection
    manifest: SnapshotManifest
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.connection.close()


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def _neo4j_tag(value: object) -> dict[str, object] | None:
    module = value.__class__.__module__
    name = value.__class__.__name__
    if not module.startswith("neo4j."):
        return None
    if name in {"Date", "Time", "DateTime"}:
        iso = value.iso_format()  # type: ignore[attr-defined]
        tagged: dict[str, object] = {
            "$type": f"neo4j.{name.lower()}",
            "iso": iso,
        }
        tzinfo = getattr(value, "tzinfo", None)
        timezone = getattr(tzinfo, "key", None) or getattr(tzinfo, "zone", None)
        if timezone:
            tagged["timezone"] = str(timezone)
        return tagged
    if name == "Duration":
        return {
            "$type": "neo4j.duration",
            "months": int(value.months),  # type: ignore[attr-defined]
            "days": int(value.days),  # type: ignore[attr-defined]
            "seconds": int(value.seconds),  # type: ignore[attr-defined]
            "nanoseconds": int(value.nanoseconds),  # type: ignore[attr-defined]
        }
    if "Point" in name:
        return {
            "$type": "neo4j.point",
            "srid": int(value.srid),  # type: ignore[attr-defined]
            "coordinates": list(value),  # type: ignore[arg-type]
        }
    return None


def _encode_graph_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotEncodingError("non-finite float")
        return value
    if isinstance(value, bytes):
        return {
            "$type": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, (list, tuple)):
        return [_encode_graph_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise SnapshotEncodingError("graph map keys must be strings")
        return {key: _encode_graph_value(value[key]) for key in sorted(value)}
    tagged = _neo4j_tag(value)
    if tagged is not None:
        return tagged
    raise SnapshotEncodingError(f"unsupported graph value type: {type(value).__name__}")


def _decode_graph_value(value: object) -> object:
    if isinstance(value, list):
        return [_decode_graph_value(item) for item in value]
    if isinstance(value, dict):
        if value.get("$type") == "bytes" and set(value) == {"$type", "base64"}:
            try:
                return base64.b64decode(str(value["base64"]), validate=True)
            except ValueError as error:
                raise SnapshotEncodingError("invalid bytes payload") from error
        return {key: _decode_graph_value(item) for key, item in value.items()}
    return value


def canonical_json_dumps(value: object) -> str:
    try:
        return json.dumps(
            _encode_graph_value(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, SnapshotEncodingError):
            raise
        raise SnapshotEncodingError("graph value encoding failed") from error


def canonical_json_loads(value: str) -> object:
    try:
        return _decode_graph_value(json.loads(value))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, SnapshotEncodingError):
            raise
        raise SnapshotEncodingError("graph value decoding failed") from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(path: Path) -> SnapshotManifest:
    return SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _verify_database(
    connection: sqlite3.Connection,
    manifest: SnapshotManifest,
) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise ValueError("integrity check failed")
    meta = dict(connection.execute("SELECT key, value FROM snapshot_meta"))
    expected = {
        "snapshot_id": manifest.snapshot_id,
        "schema_version": str(manifest.schema_version),
        "node_count": str(manifest.node_count),
        "relationship_count": str(manifest.relationship_count),
    }
    if any(meta.get(key) != value for key, value in expected.items()):
        raise ValueError("snapshot metadata mismatch")
    node_count = connection.execute("SELECT count(*) FROM kg_nodes").fetchone()[0]
    relationship_count = connection.execute(
        "SELECT count(*) FROM kg_relationships"
    ).fetchone()[0]
    if node_count != manifest.node_count or relationship_count != manifest.relationship_count:
        raise ValueError("snapshot count mismatch")


def open_verified_snapshot(
    database_path: str | Path,
    manifest_path: str | Path,
) -> VerifiedSnapshot:
    database = Path(database_path)
    manifest_file = Path(manifest_path)
    connection: sqlite3.Connection | None = None
    try:
        if not database.is_file() or not manifest_file.is_file():
            raise FileNotFoundError
        manifest = _load_manifest(manifest_file)
        if manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise AppError(DB_VERSION_ERROR)
        if _file_sha256(database) != manifest.sha256:
            raise ValueError("snapshot hash mismatch")
        uri = database.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        _verify_database(connection, manifest)
        return VerifiedSnapshot(connection=connection, manifest=manifest)
    except AppError:
        if connection is not None:
            connection.close()
        raise
    except Exception:
        if connection is not None:
            connection.close()
        raise AppError(DB_INTEGRITY_ERROR) from None


__all__ = [
    "DB_VERSION_ERROR",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "SnapshotEncodingError",
    "SnapshotManifest",
    "VerifiedSnapshot",
    "canonical_json_dumps",
    "canonical_json_loads",
    "create_schema",
    "open_verified_snapshot",
]
