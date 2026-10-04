from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from pharma_proto.knowledge.snapshot import create_schema


def write_test_snapshot(
    root: Path,
    *,
    snapshot_id: str = "fixture-snapshot",
    schema_version: int = 1,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "knowledge.sqlite"
    manifest = root / "manifest.json"

    connection = sqlite3.connect(database)
    create_schema(connection)
    connection.executemany(
        "INSERT INTO snapshot_meta(key, value) VALUES (?, ?)",
        (
            ("snapshot_id", snapshot_id),
            ("schema_version", str(schema_version)),
            ("node_count", "2"),
            ("relationship_count", "1"),
        ),
    )
    connection.executemany(
        "INSERT INTO kg_nodes(element_id, labels_json, properties_json) VALUES (?, ?, ?)",
        (
            ("n1", '["Ingredient"]', '{"canonical_name":"example api"}'),
            ("n2", '["Ingredient"]', '{"canonical_name":"example excipient"}'),
        ),
    )
    connection.execute(
        "INSERT INTO kg_relationships "
        "(element_id, start_element_id, end_element_id, relationship_type, properties_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("r1", "n1", "n2", "CONTAINS", "{}"),
    )
    connection.executemany(
        "INSERT INTO lookup_api_doses "
        "(ingredient_key, aggregation_mode, observation_index, dose_mg) "
        "VALUES (?, ?, ?, ?)",
        (
            ("example api", "dual_legacy", 0, 20.0),
            ("example api", "legacy", 0, 20.0),
        ),
    )
    connection.execute(
        "INSERT INTO lookup_pct_ranges "
        "(ingredient_key, aggregation_mode, n, lo, hi, mean, p5, p95, median, identity_json, excluded_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "example excipient",
            "dual_legacy",
            4,
            2.0,
            8.0,
            5.0,
            2.5,
            7.5,
            5.0,
            '{"target_kind":"material_grade"}',
            None,
        ),
    )
    connection.execute(
        "INSERT INTO lookup_functions(ingredient_key, function_name) VALUES (?, ?)",
        ("example excipient", "binder"),
    )
    connection.execute(
        "INSERT INTO lookup_function_pct_ranges "
        "(function_name, n, lo, hi, mean, p5, p95, median) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("binder", 5, 1.0, 10.0, 4.0, 1.5, 9.0, 4.0),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_candidates "
        "(function_name, dosage_form_base, ingredient_key, rank) VALUES (?, ?, ?, ?)",
        ("binder", "tablet", "example excipient", 1),
    )
    connection.execute(
        "INSERT INTO lookup_compatibility "
        "(api_name, excipient_name, formulation_id, source_type) VALUES (?, ?, ?, ?)",
        ("example api", "example excipient", "f1", "patent"),
    )
    connection.executemany(
        "INSERT INTO lookup_compatibility "
        "(api_name, excipient_name, formulation_id, source_type) VALUES (?, ?, ?, ?)",
        (
            ("example api", "example excipient", "f2", "patent"),
            ("example api", "example excipient", "f3", "label"),
        ),
    )
    connection.execute(
        "INSERT INTO lookup_function_catalog "
        "(function_name, canonical_role, scope, support_status) VALUES (?, ?, ?, ?)",
        ("binder", "binder", "oral_solid", "auto"),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_monographs "
        "(ingredient_key, monograph_id, source_id, monograph_name, pdf_start_page, pdf_end_page) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("example excipient", "HPE6:example", "HPE6", "Example Excipient", 10, 12),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_use_ranges "
        "(evidence_id, ingredient_key, function_name, min_pct, max_pct, unit, dosage_form, "
        "application_raw, source_id, pdf_page, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "use-1",
            "example excipient",
            "binder",
            2.0,
            5.0,
            "%",
            "tablet",
            "tablet binder",
            "HPE6",
            11,
            "reviewed",
        ),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_properties "
        "(evidence_id, ingredient_key, property_name, property_label_raw, value_text, section, "
        "source_id, pdf_page, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "property-1",
            "example excipient",
            "density",
            "Density",
            "1.2 g/cm3",
            10,
            "HPE6",
            12,
            "reviewed",
        ),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_stability "
        "(evidence_id, ingredient_key, statement, section, source_id, pdf_page, review_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("stability-1", "example excipient", "Store dry.", 11, "HPE6", 12, "reviewed"),
    )
    connection.execute(
        "INSERT INTO lookup_ingredient_incompatibilities "
        "(evidence_id, ingredient_key, target_name, normalized_target_name, target_kind, section, "
        "source_id, pdf_page, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "incompatibility-1",
            "example excipient",
            "Vanillin",
            "vanillin",
            "named_target",
            12,
            "HPE6",
            12,
            "reviewed",
        ),
    )
    connection.commit()
    connection.close()

    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest.write_text(
        json.dumps(
            {
                "snapshot_id": snapshot_id,
                "schema_version": schema_version,
                "sha256": digest,
                "node_count": 2,
                "relationship_count": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return database, manifest
