"""Administrator commands for building and verifying release snapshots."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from pharma_proto.errors import RELEASE_BUILD_ERROR, AppError
from pharma_proto.knowledge.snapshot import open_verified_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pharma-proto")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-snapshot")
    verify.add_argument("--database", required=True)
    verify.add_argument("--manifest", required=True)

    export = subparsers.add_parser("export-kg")
    export.add_argument("--uri", default="bolt://127.0.0.1:7689")
    export.add_argument("--user", default="neo4j")
    export.add_argument("--database", default="neo4j")
    export.add_argument("--output-dir", default="release-data")
    return parser


def _verify(database: str, manifest: str) -> int:
    snapshot = open_verified_snapshot(database, manifest)
    try:
        value = snapshot.manifest
        print(
            json.dumps(
                {
                    "snapshot_id": value.snapshot_id,
                    "schema_version": value.schema_version,
                    "node_count": value.node_count,
                    "relationship_count": value.relationship_count,
                },
                sort_keys=True,
            )
        )
    finally:
        snapshot.close()
    return 0


def _export(uri: str, user: str, database: str, output_dir: str) -> int:
    password = os.environ.get("PHARMA_NEO4J_PASSWORD")
    if not password:
        raise AppError(RELEASE_BUILD_ERROR)
    from neo4j import GraphDatabase

    from pharma_proto.knowledge.exporter import export_snapshot
    from pharma_proto.knowledge.neo4j_export_source import Neo4jGraphExportSource
    from pharma_proto.knowledge.neo4j_repository import Neo4jKnowledgeRepository

    driver = GraphDatabase.driver(uri, auth=(user, password))
    repository = Neo4jKnowledgeRepository(driver, database=database)
    source = Neo4jGraphExportSource(
        driver,
        database=database,
        repository=repository,
    )
    snapshot_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        database_path, manifest_path = export_snapshot(
            source,
            Path(output_dir),
            snapshot_id=snapshot_id,
        )
        return _verify(str(database_path), str(manifest_path))
    finally:
        repository.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "verify-snapshot":
        return _verify(arguments.database, arguments.manifest)
    if arguments.command == "export-kg":
        return _export(
            arguments.uri,
            arguments.user,
            arguments.database,
            arguments.output_dir,
        )
    raise AppError(RELEASE_BUILD_ERROR)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AppError as error:
        print(error.code, file=os.sys.stderr)
        raise SystemExit(1) from None


__all__ = ["build_parser", "main"]
