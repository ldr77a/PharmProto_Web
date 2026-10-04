from __future__ import annotations

from generation.generation_loop import run_generation
from generation.input_parser import build_spec
from pharma_proto.knowledge import NullKnowledgeRepository, RangeStats, UsageEvidence
from tests.product.fakes import FakeKnowledge


def test_null_repository_returns_empty_evidence():
    repository = NullKnowledgeRepository()

    assert repository.api_doses("rabeprazole") == []
    assert repository.pct_range("povidone") == RangeStats(n=0)
    assert repository.function("povidone") is None
    assert repository.function_pct_range("binder") == RangeStats(n=0)
    assert repository.compatibility_usage("rabeprazole", "povidone") == UsageEvidence(
        count=0,
        source_types=(),
    )
    assert repository.health() == {"status": "unconfigured"}
    assert repository.close() is None


def test_generation_uses_repository_without_neo4j_session():
    spec = build_spec(
        apis=["라베프라졸"],
        excipients={"binder": ["PVP-K30"], "diluent": ["D-만니톨"]},
        n_candidates=1,
    )

    result = run_generation(spec, repository=FakeKnowledge(), offline=True)

    assert len(result) == 1
    assert result[0].doses[0].source == "kg"
