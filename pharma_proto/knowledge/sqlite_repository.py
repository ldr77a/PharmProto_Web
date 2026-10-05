"""SQLite implementation of the backend-neutral knowledge contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from cleaning.canonical_base import classify_base
from pharma_proto.knowledge.contracts import FILLER_ANY_INGREDIENT, RangeStats, UsageEvidence
from pharma_proto.knowledge.evidence import (
    FunctionDescriptor,
    IncompatibilityEvidence,
    IngredientEvidence,
    MonographEvidence,
    PropertyEvidence,
    StabilityEvidence,
    UseRangeEvidence,
)
from pharma_proto.knowledge.snapshot import VerifiedSnapshot, open_verified_snapshot


def _ingredient_key(value: str) -> str:
    return classify_base(value).canonical_base.strip().casefold()


def _range_from_row(row, *, aggregation_mode: str | None = None) -> RangeStats:
    if row is None:
        return RangeStats(n=0)
    identity = json.loads(row["identity_json"]) if "identity_json" in row.keys() and row["identity_json"] else None
    return RangeStats(
        n=int(row["n"]),
        lo=row["lo"],
        hi=row["hi"],
        mean=row["mean"],
        p5=row["p5"],
        p95=row["p95"],
        median=row["median"],
        aggregation_mode=aggregation_mode,
        identity=identity,
        excluded_reason=row["excluded_reason"] if "excluded_reason" in row.keys() else None,
    )


class SQLiteKnowledgeRepository:
    def __init__(self, snapshot: VerifiedSnapshot) -> None:
        self._snapshot = snapshot
        self._connection = snapshot.connection
        self._connection.row_factory = __import__("sqlite3").Row
        self._closed = False

    @classmethod
    def open(
        cls,
        database_path: str | Path,
        manifest_path: str | Path,
    ) -> "SQLiteKnowledgeRepository":
        return cls(open_verified_snapshot(database_path, manifest_path))

    def api_doses(self, name: str, *, mode: str | None = None) -> list[float]:
        selected_mode = mode or "dual_legacy"
        rows = self._connection.execute(
            "SELECT dose_mg FROM lookup_api_doses "
            "WHERE ingredient_key = ? AND aggregation_mode = ? "
            "ORDER BY observation_index",
            (_ingredient_key(name), selected_mode),
        )
        return [float(row[0]) for row in rows]

    def pct_range(self, ingredient: str, *, mode: str | None = None) -> RangeStats:
        selected_mode = mode or "dual_legacy"
        row = self._connection.execute(
            "SELECT * FROM lookup_pct_ranges "
            "WHERE ingredient_key = ? AND aggregation_mode = ?",
            (_ingredient_key(ingredient), selected_mode),
        ).fetchone()
        return _range_from_row(row, aggregation_mode=selected_mode) if row else RangeStats(n=0)

    def function(self, ingredient: str) -> str | None:
        row = self._connection.execute(
            "SELECT function_name FROM lookup_functions WHERE ingredient_key = ?",
            (_ingredient_key(ingredient),),
        ).fetchone()
        return None if row is None else str(row[0])

    def function_pct_range(self, function: str) -> RangeStats:
        row = self._connection.execute(
            "SELECT * FROM lookup_function_pct_ranges WHERE function_name = ?",
            (function,),
        ).fetchone()
        return _range_from_row(row) if row else RangeStats(n=0)

    def ingredient_candidates(
        self,
        functions: tuple[str, ...],
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]:
        if not functions or not dosage_form_bases:
            return []
        function_marks = ",".join("?" for _ in functions)
        dosage_marks = ",".join("?" for _ in dosage_form_bases)
        rows = self._connection.execute(
            "SELECT ingredient_key, min(rank) AS best_rank "
            "FROM lookup_ingredient_candidates "
            f"WHERE function_name IN ({function_marks}) "
            f"AND dosage_form_base IN ({dosage_marks}) "
            "GROUP BY ingredient_key ORDER BY best_rank, ingredient_key LIMIT ?",
            (*functions, *dosage_form_bases, max(1, int(limit))),
        )
        return [str(row[0]) for row in rows]

    # --- 역할층(schema 2) ---------------------------------------------------------------
    def primary_role(self, ingredient: str) -> str | None:
        row = self._connection.execute(
            "SELECT primary_role FROM lookup_role_dictionary WHERE ingredient_key = ?",
            (_ingredient_key(ingredient),),
        ).fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def role_candidates(
        self,
        role: str,
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]:
        if not role or not dosage_form_bases:
            return []
        dosage_marks = ",".join("?" for _ in dosage_form_bases)
        rows = self._connection.execute(
            "SELECT ingredient_key, sum(formulation_count) AS total "
            "FROM lookup_role_candidates "
            f"WHERE role = ? AND dosage_form_base IN ({dosage_marks}) "
            "GROUP BY ingredient_key ORDER BY total DESC, ingredient_key LIMIT ?",
            (role, *dosage_form_bases, max(1, int(limit))),
        )
        return [str(row[0]) for row in rows]

    def role_pct_range(self, ingredient: str, role: str) -> RangeStats:
        row = self._connection.execute(
            "SELECT * FROM lookup_role_pct_ranges WHERE ingredient_key = ? AND role = ?",
            (_ingredient_key(ingredient), role),
        ).fetchone()
        return _range_from_row(row) if row else RangeStats(n=0)

    def role_pct_sum_range(self, role: str) -> RangeStats:
        row = self._connection.execute(
            "SELECT * FROM lookup_role_pct_sums WHERE role = ?",
            (role,),
        ).fetchone()
        return _range_from_row(row) if row else RangeStats(n=0)

    def filler_pct_range(self, ingredient: str, api_load_band: str) -> RangeStats:
        specific = self._connection.execute(
            "SELECT * FROM lookup_filler_pct_ranges WHERE api_load_band = ? AND ingredient_key = ?",
            (api_load_band, _ingredient_key(ingredient)),
        ).fetchone()
        if specific is not None and int(specific["n"]) >= 5:
            return _range_from_row(specific)
        generic = self._connection.execute(
            "SELECT * FROM lookup_filler_pct_ranges WHERE api_load_band = ? AND ingredient_key = ?",
            (api_load_band, FILLER_ANY_INGREDIENT),
        ).fetchone()
        return _range_from_row(generic) if generic else RangeStats(n=0)

    def compatibility_usage(self, api: str, excipient: str) -> UsageEvidence:
        parameters = (api.lower(), excipient.lower())
        matching = (
            "SELECT DISTINCT formulation_id, source_type "
            "FROM lookup_compatibility "
            "WHERE instr(api_name, ?) > 0 AND instr(excipient_name, ?) > 0"
        )
        count = self._connection.execute(
            f"SELECT count(*) FROM ({matching})",
            parameters,
        ).fetchone()[0]
        source_rows = self._connection.execute(
            f"SELECT source_type, count(*) AS source_count FROM ({matching}) "
            "WHERE source_type IS NOT NULL GROUP BY source_type "
            "ORDER BY source_count DESC, source_type ASC LIMIT 5",
            parameters,
        )
        return UsageEvidence(
            int(count),
            tuple(str(row[0]) for row in source_rows),
        )

    def function_catalog(self) -> tuple[FunctionDescriptor, ...]:
        rows = self._connection.execute(
            "SELECT function_name, canonical_role, scope, support_status "
            "FROM lookup_function_catalog ORDER BY function_name"
        )
        return tuple(
            FunctionDescriptor(
                name=str(row[0]),
                canonical_role=None if row[1] is None else str(row[1]),
                scope=str(row[2]),
                support_status=str(row[3]),
            )
            for row in rows
        )

    def ingredient_evidence(self, ingredient: str) -> IngredientEvidence:
        key = _ingredient_key(ingredient)
        monographs = tuple(
            MonographEvidence(
                monograph_id=str(row[0]),
                source_id=str(row[1]),
                name=str(row[2]),
                pdf_start_page=row[3],
                pdf_end_page=row[4],
            )
            for row in self._connection.execute(
                "SELECT monograph_id, source_id, monograph_name, pdf_start_page, pdf_end_page "
                "FROM lookup_ingredient_monographs WHERE ingredient_key = ? ORDER BY monograph_id",
                (key,),
            )
        )
        use_ranges = tuple(
            UseRangeEvidence(
                evidence_id=str(row[0]),
                function_name=str(row[1]),
                min_pct=row[2],
                max_pct=row[3],
                unit=str(row[4]),
                dosage_form=row[5],
                application=row[6],
                source_id=str(row[7]),
                pdf_page=row[8],
                review_status=row[9],
            )
            for row in self._connection.execute(
                "SELECT evidence_id, function_name, min_pct, max_pct, unit, dosage_form, "
                "application_raw, source_id, pdf_page, review_status "
                "FROM lookup_ingredient_use_ranges WHERE ingredient_key = ? "
                "ORDER BY function_name, evidence_id",
                (key,),
            )
        )
        properties = tuple(
            PropertyEvidence(
                evidence_id=str(row[0]),
                property_name=str(row[1]),
                label=row[2],
                value_text=str(row[3]),
                section=row[4],
                source_id=str(row[5]),
                pdf_page=row[6],
                review_status=row[7],
            )
            for row in self._connection.execute(
                "SELECT evidence_id, property_name, property_label_raw, value_text, section, "
                "source_id, pdf_page, review_status FROM lookup_ingredient_properties "
                "WHERE ingredient_key = ? ORDER BY property_name, evidence_id",
                (key,),
            )
        )
        stability = tuple(
            StabilityEvidence(
                evidence_id=str(row[0]),
                statement=str(row[1]),
                section=row[2],
                source_id=str(row[3]),
                pdf_page=row[4],
                review_status=row[5],
            )
            for row in self._connection.execute(
                "SELECT evidence_id, statement, section, source_id, pdf_page, review_status "
                "FROM lookup_ingredient_stability WHERE ingredient_key = ? ORDER BY evidence_id",
                (key,),
            )
        )
        incompatibilities = tuple(
            IncompatibilityEvidence(
                evidence_id=str(row[0]),
                target_name=str(row[1]),
                normalized_target_name=str(row[2]),
                target_kind=row[3],
                section=row[4],
                source_id=str(row[5]),
                pdf_page=row[6],
                review_status=row[7],
            )
            for row in self._connection.execute(
                "SELECT evidence_id, target_name, normalized_target_name, target_kind, section, "
                "source_id, pdf_page, review_status FROM lookup_ingredient_incompatibilities "
                "WHERE ingredient_key = ? ORDER BY evidence_id, normalized_target_name",
                (key,),
            )
        )
        return IngredientEvidence(
            ingredient=key,
            monographs=monographs,
            use_ranges=use_ranges,
            properties=properties,
            stability=stability,
            incompatibilities=incompatibilities,
        )

    def health(self) -> Mapping[str, object]:
        manifest = self._snapshot.manifest
        return {
            "status": "ok",
            "backend": "sqlite",
            "snapshot_id": manifest.snapshot_id,
            "schema_version": manifest.schema_version,
            "node_count": manifest.node_count,
            "relationship_count": manifest.relationship_count,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._snapshot.close()


__all__ = ["SQLiteKnowledgeRepository"]
