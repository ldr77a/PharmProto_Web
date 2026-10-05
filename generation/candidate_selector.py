"""Fill omitted oral-solid excipient roles from DB evidence, then curated defaults."""

from __future__ import annotations

from generation.oral_solid_profiles import (
    CURATED_DEFAULTS,
    OralSolidProfile,
    coating_system_role,
    resolve_profile,
    role_aliases,
)
from pharma_proto.knowledge import KnowledgeRepository


def _dedupe(values: list[str], excluded: set[str], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = value.strip()
        key = name.casefold()
        if not name or key in seen or key in excluded:
            continue
        seen.add(key)
        selected.append(name)
        if len(selected) == limit:
            break
    return selected


def _split_coating_system(spec, repository, source_map: dict) -> None:
    """사용자가 '코팅: HPMC, PEG, talc, 색소' 처럼 코팅 시스템을 통째로 적은 경우.

    네 성분이 후보마다 돌아가며 '코팅제' 자리를 차지하지 않도록, 역할 사전의 기본 역할(없으면 이름 규칙)로
    가소제·착색제·불투명화제·활택보조 자리로 옮기고 코팅 자리에는 피막 형성제만 남긴다.
    """
    listed = list(spec.excipient_choices.get("coating", ()))
    if len(listed) < 2:
        return
    primary = getattr(repository, "primary_role", None)
    keep: list[str] = []
    for name in listed:
        role = coating_system_role(name, primary(name) if callable(primary) else None)
        if role == "coating":
            keep.append(name)
            continue
        bucket = spec.excipient_choices.setdefault(role, [])
        if name.casefold() not in {item.casefold() for item in bucket}:
            bucket.append(name)
        source_map[role] = "user"
    spec.excipient_choices["coating"] = keep or listed[:1]


_DILUENT_REROUTE_ROLES = ("disintegrant", "binder", "glidant", "lubricant")


def _reroute_diluents_by_primary_role(spec, repository, source_map: dict) -> None:
    """'옥수수전분, D-만니톨' 처럼 기존 조성을 그대로 적으면 둘 다 희석제 후보로 들어와 후보마다 하나씩만 쓰인다.

    역할 사전의 기본 역할이 희석제가 아닌 것(옥수수전분 → 붕해제)은 그 역할 자리로 옮겨, 후보 1 에 둘 다 들어가게 한다.
    진짜 희석제가 하나도 남지 않으면 건드리지 않는다.
    """
    listed = list(spec.excipient_choices.get("diluent", ()))
    primary = getattr(repository, "primary_role", None)
    if len(listed) < 2 or not callable(primary):
        return
    keep: list[str] = []
    moved: list[tuple[str, str]] = []
    for name in listed:
        role = primary(name)
        if role in _DILUENT_REROUTE_ROLES:
            moved.append((name, role))
        else:
            keep.append(name)
    if not keep or not moved:
        return
    for name, role in moved:
        bucket = spec.excipient_choices.setdefault(role, [])
        if name.casefold() not in {item.casefold() for item in bucket}:
            bucket.append(name)
        source_map[role] = "user"
    spec.excipient_choices["diluent"] = keep


def complete_excipient_choices(
    spec,
    repository: KnowledgeRepository,
    *,
    limit_per_role: int = 3,
) -> OralSolidProfile:
    """Mutate a parsed spec only where role choices are absent."""
    profile = resolve_profile(
        spec.dosage_form,
        spec.process,
        getattr(spec, "release_profile", ""),
    )
    spec.profile_id = profile.profile_id
    excluded = {api.name.casefold() for api in spec.apis}
    source_map = getattr(spec, "selection_sources", None)
    if source_map is None:
        source_map = {}
        spec.selection_sources = source_map

    _split_coating_system(spec, repository, source_map)
    _reroute_diluents_by_primary_role(spec, repository, source_map)

    lookup = getattr(repository, "ingredient_candidates", None)
    role_lookup = getattr(repository, "role_candidates", None)
    catalog_lookup = getattr(repository, "function_catalog", None)
    catalog = tuple(catalog_lookup()) if callable(catalog_lookup) else ()
    auto_function_names = {
        descriptor.name
        for descriptor in catalog
        if descriptor.scope == "oral_solid" and descriptor.support_status == "auto"
    }
    for role in profile.auto_roles:
        explicit = _dedupe(list(spec.excipient_choices.get(role, ())), excluded, limit_per_role)
        if explicit:
            spec.excipient_choices[role] = explicit
            source_map[role] = "user"
            continue

        candidates: list[str] = []
        curated = list(CURATED_DEFAULTS.get(role, ()))
        used_role_table = False
        if callable(role_lookup):   # schema 2: "이 배합에서 맡은 역할" 기준 순위(요청 제형 배합 수 합)
            candidates = list(
                role_lookup(
                    role,
                    dosage_form_bases=profile.dosage_form_bases,
                    limit=max(30, limit_per_role * 10),
                )
            )
            used_role_table = bool(candidates)
        if not candidates and callable(lookup):
            aliases = role_aliases(role)
            if catalog:
                aliases = tuple(alias for alias in aliases if alias in auto_function_names)
            candidates = list(
                lookup(
                    aliases,
                    dosage_form_bases=profile.dosage_form_bases,
                    limit=max(30, limit_per_role * 10),
                )
            ) if aliases else []
        curated_keys = {name.casefold() for name in curated}
        reviewed_db_candidates = [
            name for name in candidates if name.strip().casefold() in curated_keys
        ]
        selected = _dedupe(reviewed_db_candidates, excluded, limit_per_role)
        selected_keys = excluded | {name.casefold() for name in selected}
        fallback = _dedupe(
            curated,
            selected_keys,
            limit_per_role - len(selected),
        )
        combined = selected + fallback
        if combined:
            spec.excipient_choices[role] = combined
            kg_label = "kg_role" if used_role_table else "kg"
            if selected and fallback:
                source_map[role] = f"{kg_label}+curated_default"
            elif selected:
                source_map[role] = kg_label
            else:
                source_map[role] = "curated_default"

    return profile


__all__ = ["complete_excipient_choices"]
