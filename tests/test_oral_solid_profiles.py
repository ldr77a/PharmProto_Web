"""제형 판정과 역할 별칭 (Neo4j·LLM 불필요).

- 비고형 판정은 제형 문자열만 보고, 공정 설명의 '결합액'·'코팅액' 같은 단어에 끌려가지 않는다.
- 'gel' 이 'gelatin' 에, 'solution' 이 'dissolution' 에 걸리지 않는다(단어 경계).
- LLM 이 돌려주는 영문 역할 표현(film coating, colorant …)이 생성기 역할로 매핑된다.
"""

from __future__ import annotations

import pytest

from generation.oral_solid_profiles import (
    UnsupportedDosageForm,
    canonical_role,
    is_oral_solid,
    resolve_profile,
)


@pytest.mark.parametrize("form", [
    "film-coated tablet", "tablet", "hard gelatin capsule", "필름코팅정", "정제", "caplet",
    "orally disintegrating tablet", "granules for oral suspension",   # 과립이 주 제형
])
def test_oral_solid_forms_are_accepted(form):
    assert is_oral_solid(form)


@pytest.mark.parametrize("form", ["oral solution", "injection", "topical gel", "nasal spray suspension", "soft gelatin capsule"])
def test_non_oral_solid_forms_are_rejected(form):
    assert not is_oral_solid(form) or "capsule" in form


def test_process_text_with_binder_solution_does_not_reject():
    process = ("Change from wet granulation (povidone binder solution, coating suspension) to direct "
               "compression to reduce NDMA; improve dissolution")
    assert resolve_profile("film-coated tablet", process, "").profile_id == "film_coated_tablet"
    with pytest.raises(UnsupportedDosageForm):
        resolve_profile("oral solution", "", "")


@pytest.mark.parametrize(("value", "expected"), [
    ("film coating", "coating"), ("Film-Coating Agent", "coating"), ("coating agent", "coating"),
    ("colorant", "colorant"), ("coloring agent", "colorant"), ("pigment", "colorant"), ("lake", "colorant"),
    ("filler", "diluent"), ("dry binder", "binder"), ("anti-adherent", "glidant"),
    ("코팅제", "coating"), ("binder", "binder"), ("tablet_coating", "coating"),
    ("film coating polymer", "coating"), ("anti-tacking agent", "glidant"), ("film former", "coating"),
])
def test_llm_role_phrases_map_to_generator_roles(value, expected):
    assert canonical_role(value) == expected


def test_coating_system_list_is_split_by_role():
    from types import SimpleNamespace

    from generation.candidate_selector import complete_excipient_choices
    from tests.product.fakes import FakeKnowledge

    spec = SimpleNamespace(
        apis=[SimpleNamespace(name="trimetazidine hydrochloride")], dosage_form="film-coated tablet",
        process="direct compression", release_profile="",
        excipient_choices={"coating": ["hypromellose", "polyethylene glycol", "talc", "Sunset Yellow FCF aluminum lake"]},
        selection_sources={},
    )
    repository = FakeKnowledge(primary_roles={"hypromellose": "binder", "polyethylene glycol": "plasticizer", "talc": "glidant"})

    complete_excipient_choices(spec, repository)

    assert spec.excipient_choices["coating"] == ["hypromellose"]          # 피막 형성제만 코팅 자리에
    assert spec.excipient_choices["plasticizer"] == ["polyethylene glycol"]
    assert spec.excipient_choices["glidant"] == ["talc"]
    assert spec.excipient_choices["colorant"] == ["Sunset Yellow FCF aluminum lake"]   # 사전에 없어도 이름 규칙
    assert spec.selection_sources["plasticizer"] == "user" and spec.selection_sources["colorant"] == "user"


def test_non_diluent_in_diluent_list_moves_to_its_primary_role():
    from types import SimpleNamespace

    from generation.candidate_selector import complete_excipient_choices
    from tests.product.fakes import FakeKnowledge

    spec = SimpleNamespace(
        apis=[SimpleNamespace(name="trimetazidine hydrochloride")], dosage_form="film-coated tablet",
        process="direct compression", release_profile="",
        excipient_choices={"diluent": ["starch", "mannitol"], "binder": ["microcrystalline cellulose"]},
        selection_sources={},
    )
    repository = FakeKnowledge(primary_roles={"starch": "disintegrant", "mannitol": "diluent",
                                              "microcrystalline cellulose": "diluent"})

    complete_excipient_choices(spec, repository)

    assert spec.excipient_choices["diluent"] == ["mannitol"]          # 후보 1 희석제 = 만니톨
    assert spec.excipient_choices["disintegrant"] == ["starch"]       # 옥수수전분은 붕해제 자리로
    assert spec.excipient_choices["binder"] == ["microcrystalline cellulose"]   # 사용자가 결합제로 적은 MCC 는 그대로
    assert spec.selection_sources["disintegrant"] == "user"


def test_diluent_list_is_left_alone_when_nothing_true_diluent_remains():
    from types import SimpleNamespace

    from generation.candidate_selector import complete_excipient_choices
    from tests.product.fakes import FakeKnowledge

    spec = SimpleNamespace(
        apis=[SimpleNamespace(name="x")], dosage_form="tablet", process="", release_profile="",
        excipient_choices={"diluent": ["starch", "pregelatinized starch"]}, selection_sources={},
    )
    complete_excipient_choices(spec, FakeKnowledge(primary_roles={"starch": "disintegrant", "pregelatinized starch": "binder"}))
    assert spec.excipient_choices["diluent"] == ["starch", "pregelatinized starch"]
