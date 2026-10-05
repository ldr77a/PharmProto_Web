# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Researcher-facing web app of the pharmaceutical formulation-candidate generator (oral solid dosage
forms): a natural-language request becomes 1–5 candidate composition tables, each allocated from
knowledge-graph evidence and validated by gates. The system is explicitly **decision support, not a
manufacturability verdict** — user-facing wording must never claim a final prescription judgment.

Docstrings, comments, and user-facing strings are Korean; code identifiers are English.

## Two repositories, one contract

| | This repository (app, `PhramaProto-0.1`) | `Phrama_Proto` (DB, `../Phrama_Proto`) |
|---|---|---|
| Owns | `pharma_proto/app.py`, launcher, `llm/`, `gates/*` (except `kg_util`), `generation/*`, `static/`, `templates/`, `start.bat`, `tools/build-release.ps1`, tests | Neo4j pipelines, ingestion, cleaning, normalization, ingredient merging, SQLite exporter, **contract files** |
| Storage | read-only `release-data/knowledge.sqlite` (git LFS) | live Neo4j (Docker) |
| Platform | Windows 11 x64, non-admin, no Docker/Neo4j/system Python | developer machine |

**Contract files are read-only here.** They are owned by the DB repository and copied in by its
`tools/publish_snapshot.py` together with `release-data/`:
`pharma_proto/knowledge/{snapshot,sqlite_repository,contracts,evidence,function_taxonomy}.py`,
`cleaning/canonical_base.py`, `gates/kg_util.py`, `function_seed.json`, `pharma_proto/cli.py`. If a change seems needed in one
of them, make it in `Phrama_Proto` and re-publish; editing them here silently desynchronizes the lookup
keys. Runtime data such as `generation/standard_doses.json` is owned here.

`release-data/manifest.json` carries the snapshot id, SHA-256, schema version, and counts. The app
refuses a snapshot whose `schema_version` is not in `SUPPORTED_SCHEMA_VERSIONS` (`DB-VERSION-001`) or
whose hash/counts mismatch (`DB-INTEGRITY-001`). The app never copies, writes, migrates, or updates the
database in place; rollback means re-running an older ZIP. Schema 2 snapshots carry the role layer
(`lookup_role_*`): `generation/candidate_selector.py`, `generation/excipient_allocator.py`,
`gates/manufacturability.py` and `gates/kg_util.py` consult `role_candidates` / `role_pct_range` /
`role_pct_sum_range` / `primary_role` first and fall back to the function-based lookups when the role
table has fewer than 5 observations. Provenance labels `kg_role` / `hpe6+kg_role` mark the role-specific path.

## Explanation layer (second LLM call)

The LLM parses the request (`LLMService.parse`) and, after the deterministic generation, explains the result
(`LLMService.explain`). `generation/explanation.py` builds the payload (components with provenance, gate results,
HPE6 evidence, co-usage counts with the requested API); the model returns `FormulationExplanation`
(`llm/schema.py`) and every sentence carries `basis`: `evidence` (cites supplied data, `refs`) or `general`
(model knowledge, rendered as "일반 지식·검증 필요"). Numbers are never changed by the model. The explanation is
deferred: `/api/generate` returns the table with `explain-slot` placeholders and `app.js` calls
`POST /api/explain` per candidate (candidate 1 automatically, others on click); the server merges each answer into
`conversation.explanation` and re-renders `conversation.html`. A failed call shows `해설 생성 실패 (<code>)` in the slot. All three providers use structured outputs; the Claude
path uses `messages.parse` because current Claude models reject forced `tool_choice`.

## Follow-up layer (third LLM call)

`POST /api/followup` sends the previous `ParsedRequest`, the current result payload and recent turns to
`LLMService.followup`; the model returns `FollowUpResponse` (`action` refine|answer, a **full** `request`, `answer`
sentences with `basis`). `refine` regenerates from `request.to_domain()` (never from the mutated spec) and only
when `request_changes()` is non-empty; `answer` never touches the table. Conversation state is process memory
(`pharma_proto/conversation.py`, LRU 20), cleared by logout/shutdown. Saved results (`/api/results…`) can be
reopened read-only or resumed by recomputing deterministically from the stored `ParsedRequest` (no LLM call;
refused with `RESULTS-SNAPSHOT-001` if the snapshot id differs). Plain-language explanations for provenance
tags, gates and badges live in `generation/help_text.py` (app-owned) and feed both the sidebar and the popover.

## Request flow

`POST /api/generate` → `llm/service.py` (`LLMService.parse_request`, provider-agnostic structured output) →
`llm/schema.py:ParsedRequest.to_domain()` (user amounts → `FormulationSpec.user_amounts`) →
`generation/input_parser.py:FormulationSpec` →
`generation/candidate_selector.py` fills omitted roles (DB evidence intersected with curated defaults,
then curated fallback; records provenance in `spec.selection_sources`) →
`generation/generation_loop.py:run_generation` → per candidate
`generation/excipient_allocator.py:allocate` (API mg fixed, functional excipients at user % / user mg or KG
median %, **diluent takes the remainder so Σ=100 is structural**; with no user total but a user diluent amount
the total is solved backwards) → `gates/pipeline.py:run_pipeline` → `generation/html_formatter.py:results_html`.

Gates run cheapest-first: 4 total-constraint → 5 total-sum → 6 function-coverage → 1 allowable-range →
3 manufacturability → 2 compatibility (RDKit, last). Hard fails: 4, 5, 6, clear range violations in 1.
Soft warnings: 2, 3. On hard fail the loop adjusts target total mass up to `MAX_RETRIES` times, except when
the user fixed the total or the diluent amount (then the first result is reported as is). If the only hard
failure is gate 1 and every violation is a user-specified amount, the candidate is downgraded to `warning`
(the gate chip still shows the failure). Unresolved candidates are returned labeled, not dropped.

Role → KG function-name mapping is `knowledge/function_taxonomy.py:ROLE_ALIASES` (contract file);
dosage-form role profiles and curated defaults are `generation/oral_solid_profiles.py`. API dose
fallback is user value → KG median (`lookup_api_doses`) → `generation/standard_doses.json`.

## Safety rules baked into the code

- **Error codes only**: every HTTP error returns a stable code from `pharma_proto/errors.py`. Never put
  exception text, paths, keys, or provider payloads into a response or a log.
- **API keys are process-memory only** (`llm/memory_keys.py`); `POST /api/logout` clears them together with
  the conversation store. The only persisted settings are non-secret display preferences in
  `LOCALAPPDATA/PhramaProto/preferences.json` (`pharma_proto/preferences.py`: allowlisted keys, rejects names
  matching `key|secret|token|password`). Saved results live under `LOCALAPPDATA/PhramaProto/results/`
  (`pharma_proto/results_store.py`), written only when the user clicks save, never containing keys, and the
  app returns them as JSON (ids, never paths).
- **No browser storage**: `tests/product/test_mvp_app.py` fails if `static/app.js` mentions `localStorage`,
  `sessionStorage` or `document.cookie`. CSP forbids inline scripts/styles; data is injected only via
  `<script type="application/json">` blocks (`#model-catalog`, `#help-text`).
- **Model allowlist**: `llm/catalog.py` maps provider × tier (`cheap`/`normal`/`good`) to model ids.
  There is intentionally no free-text model field.
- Gemini/OpenAI/Anthropic SDKs are imported lazily inside the factory functions in `llm/service.py`;
  keep them lazy so the app starts without every provider installed.

## Commands

```bash
uv sync
uv run pytest                          # on macOS: LOCALAPPDATA=/tmp/localappdata and deselect the Windows-only product tests
node --test tests/test_app_js.mjs      # app.js in a fake DOM; add new element ids to its `elements` map
uv run ruff check .
pwsh tools/build-release.ps1          # → dist/PhramaProto-<app-version>-<snapshot-id>.zip (Windows)
```

`tools/build-release.ps1` holds the **authoritative file allowlist** for the Release ZIP. If you add a
module that the app imports at runtime, add it to `$runtimePackageFiles` or the release will be missing
it (`tools/check-release-tree.ps1` audits the staged tree). `docs/release/*-manifest.json` records
each shipped build's snapshot.

Receiving a new snapshot: run `python tools/publish_snapshot.py --confirm` in `Phrama_Proto`, then here
`git add release-data gates/kg_util.py …` and commit (git-lfs must be installed because
`release-data/knowledge.sqlite` is an LFS file). Rebuild the ZIP afterwards.
