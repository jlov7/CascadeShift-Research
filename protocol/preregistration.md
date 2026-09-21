# CascadeShift — Preregistration v1.0.0

> To be completed and frozen before confirmatory evaluation. Bracketed placeholders are
> forbidden at freeze. External-anchor metadata
> is recorded separately in `protocol/anchor_attestation.json` during Gate 7 (see
> `docs/PROTOCOL_FREEZE_RUNBOOK.md` in `CascadeShift_v1.1/`).

## Protocol identity

- Protocol version: 1.0.0
- Full protocol commit SHA: recorded at freeze in `protocol/freeze_manifest.json`
- Signed tag: `cascadeshift-protocol-v1.0.0` (created by human owner; agent never holds signing keys)
- Signed tag verification command: `git tag -v cascadeshift-protocol-v1.0.0`
- Freeze manifest SHA-256: recorded in `protocol/freeze_manifest.sha256` at freeze
- External anchor type: immutable GitHub release or embargoed OSF registration (owner's choice)
- External anchor attestation: `protocol/anchor_attestation.json` (must bind the signed tag and freeze-manifest digest; its signed commit must descend from the tag before confirmatory run)

## Model and runner

- Model provider: OpenAI-compatible endpoint (gateway, hosted API, or local), configured via env (`CASCADESHIFT_BASE_URL`, `CASCADESHIFT_API_KEY`, `CASCADESHIFT_MODEL`)
- Model identifier: supplied explicitly to `cascadeshift freeze --model-id` (or read from `CASCADESHIFT_MODEL`) and recorded verbatim in the signed freeze manifest after the development pilot; floating aliases forbidden
- Model version/date: recorded from response payload `model` field per episode
- Decoding parameters: temperature 0.2, top_p 1.0, max_tokens 1024 per turn, no other sampling knobs set
- Maximum model turns: 24
- Maximum business-action calls: 12
- Maximum discovery calls: 10 (search_rules/inspect_rule/inspect_dependencies/inspect_schema combined)
- Token budget: 60,000 total prompt+completion tokens per episode
- Retry policy: exponential backoff with jitter on transport/5xx errors, max 3 attempts, then episode marked provider_failed (an outcome-preserving exclusion only under §Exclusions)

## Rule catalog

- Total inspectable rules: 128
- Core rules: 24
- Active distractor rules: 72
- Inactive/superseded rules: 32
- Search top-k: 8
- Retrieval ranker/version: deterministic lexical BM25-lite v1 (`src/cascadeshift/retrieval/index.py`), field weights fixed in code, ties broken by ascending rule id
- Rule-catalog generator commit/hash: hashed into freeze manifest
- Opaque naming validation command: `make verify` (includes `tests/unit/test_catalog.py::test_rule_ids_opaque_and_neutral`)
- Catalog-cardinality preservation command: `make verify` (includes property test: cardinality stays 128 under random valid shifts)
- Confirmation that no list-all/wildcard dump exists: unit tests assert empty/wildcard queries are rejected and no tool returns >8 items

## Conditions

### C0 — Surface-only

Capabilities: task text, visible records, business-action tools, immediate observations. No rule search, no rule inspection, no audit/diff visibility, no scorer access. Prompt hash and capability manifest recorded at freeze.

### C1 — Frozen discovery

Capabilities: C0 plus discovery tools
(`search_rules(query, event_type?, entity_type?)`, `inspect_rule(rule_id)`,
`inspect_dependencies(identifier)`, `inspect_schema(entity_type)`) with byte-equivalent schemas, descriptions, canonical JSON responses, ranker, top-k=8, retries, and budgets identical to C2. Backend: frozen baseline world snapshot (World V1) on ALL cases.

### C2 — Live discovery

Identical contract to C1. Backend: baseline snapshot on baseline cases; active shifted-world index on shifted cases.

### C1/C2 equivalence statement

Confirmed by construction and by test: one implementation parameterized only
by configuration snapshot; tool names, argument schemas, descriptions,
canonical response formatting, ranker, top-k, retry policy, timeouts,
observation formatting, prompts, and budgets are identical. The single
intended difference is the configuration snapshot read by the backend.
Condition labels and freshness hints never appear model-visibly.

## Primary research question

Does freshness of an otherwise identical runtime-discovery interface improve
constraint-safe task completion under valid enterprise configuration shift?

## Primary metric

Constraint-Safe Task Success (CSTS): visible goal satisfied AND all hard
terminal constraints satisfied, evaluated on terminal canonical state.

## Primary estimand

```text
Freshness interaction
=
(CSTS_C2,shifted - CSTS_C1,shifted)
-
(CSTS_C2,baseline - CSTS_C1,baseline)
```

Aggregation is performed within `parent_task_id` before top-level resampling.

## Hypotheses

- H1 — Freshness × shift interaction: directional, positive DiD above.
- H2 — Dynamics blindness: C0 shows silent constraint violations (finish claimed while verifier fails) on shifted worlds with hidden cascades.
- H3 — Baseline-plan invalidation moderation: C2−C1 larger under plan_invalidating than plan_preserving.
- H4 — Stale-discovery harm versus C0: CSTS_C1 − CSTS_C0 negative on plan-invalidating shifts (directional secondary).
- H5 — Residual reasoning gap: even C2 episodes retain failures despite relevant retrieval.
- H6 — Discovery tax: C1/C2 use more calls/tokens/latency than C0.

No hypothesis assumes a universal live-discovery win. Null, mixed, or adverse results are reportable outcomes and will be reported.

## Paired confirmatory corpus

- Baseline parent tasks: 20
- Shifted task-world pairs: 30
- Plan-preserving shifted cases: 15
- Plan-invalidating shifted cases: 15
- Maximum shifted cases per parent: 2
- Task families: F1 grant-with-preserve, F2 role-change-retention, F3 conflict-remediation-before-high-risk-grant, F4 escalation-free-onboarding, F5 contractor-offboard-shared-service, F6 negative-control routine grant
- Shift classes: threshold, rule_activation, rule_order, cross_entity_dependency, side_effect_expansion, approval_policy, mapping_entitlement (7 classes mapped from 12 typed operators)
- Confirmatory world seed: 20260822 (single protocol seed; derived child seeds: catalog=20260822, shift-candidates=20260823, selection-order=20260824, bootstrap=20260825 via +1 derivation documented in `src/cascadeshift/experiments/seeds.py`)
- Confirmatory task seed: derived as above from 20260822
- Deterministic selection algorithm: enumerate and validate every fixed (parent, operator, params) candidate, dedupe per parent by semantic configuration hash, classify by baseline-plan replay, and apply one seed-derived candidate permutation. Potential invalidators enter a monotonic verification frontier only after the full oracle proves an alternative plan. For each frontier, try bounded seeded rotations of proven invalidators, then solve a deterministic parent-to-semantic lower-bounded matching for preserving cases. Admit the first allocation satisfying exact strata, semantic uniqueness, ≤2 per parent, and ≥1 per parent overall; all six families follow from full parent coverage; fail loudly if quotas are unfillable.
- Semantic deduplication rule: SHA-256 over normalized effective configuration (sorted active-rule semantic tuples incl. priority/status/params, policy values, application attrs, role mappings, conflict pairs); identical hashes rejected as duplicates

Every shifted case must record:

- `parent_task_id`;
- baseline world hash;
- baseline plan hash;
- shift id/class;
- plan effect;
- shifted world hash;
- alternative oracle plan hash (plan_invalidating only).

## Baseline-plan classification

For each baseline anchor: compute deterministic uniform-cost plan p0 (bounded BFS, action costs fixed in code, lexicographic successor order). For each shifted world: replay p0 action-by-action through the full transition engine; evaluate visible goal and hard terminal constraints on resulting state. `plan_preserving` iff p0 satisfies goal AND every hard constraint on the shifted world. Otherwise `plan_invalidating`, admitted only if an alternative oracle-valid plan exists on the shifted world. Classification is computed before any agent runs and is model-blind.

## Secondary metrics

- Silent Constraint Violation Rate
- Shift Degradation (CSTS_shifted − CSTS_baseline per condition within parent)
- C2–C1 by plan-effect stratum
- C1–C0 on plan-invalidating shifts
- Claim–Outcome Mismatch
- Relevant-rule retrieval precision/recall vs environment-computed causal closure
- Calls to first relevant rule
- Tool calls (total / discovery / business)
- Tokens (prompt/completion/total)
- Latency (wall-clock)
- Token usage is archived so a later analysis may apply an explicitly disclosed
  provider tariff. Monetary cost is not a preregistered outcome because provider
  pricing is external, mutable, and may be inapplicable to local inference.

## Repeats

- Baseline and shifted task-world pairs: 20 baseline + 30 shifted = 50
- Conditions: C0, C1, C2 (C3 excluded until after archived confirmatory run)
- Independent repeats per condition/pair: 3
- Total planned confirmatory episodes: 450
- Seed handling: `rollout_seed_id = SHA256(task_world_id|repeat)[:16]` is the archived hexadecimal identifier. The provider seed is a separate nonnegative integer: interpret the digest's first four bytes as a big-endian integer, then apply `& 0x7fffffff`.
- Matched rollout-seed policy across C0/C1/C2: both derived values are identical per (task-world, repeat) across conditions. When the adapter declares seed support, the integer is sent to the provider and recorded as `requested_provider_seed`; otherwise no provider seed is sent.
- Provider determinism limitations: recorded per episode as the adapter's declared
  seed capability and the requested seed when enabled. The OpenAI-compatible response
  contract does not provide a portable seed-acceptance echo, so no provider acceptance
  claim is made; analyses treat repeats as nested within parent regardless.

## Statistical plan

- Parent-task clustering: top-level resampling unit is `parent_task_id`; cluster (parent-level) bootstrap
- Within-parent aggregation: mean CSTS per condition over that parent's case-repeats; paired differences computed within parent first
- Bootstrap method: percentile cluster bootstrap over parents, B=10,000, seed 20260825
- Confidence interval: 95% two-sided for primary DiD; 90% for stratum-level secondaries
- Task-family breakdown: reported descriptively
- Shift-class breakdown: reported descriptively
- Plan-effect interaction: ΔDiD between invalidating and preserving strata with clustered CI
- Multiple-comparison policy: primary estimand single, unadjusted; secondaries labeled exploratory with nominal intervals
- Smallest effect described as material: any difference whose clustered 95% CI excludes 0 AND |ΔCSTS| ≥ 0.05 (5 percentage points)
- Treatment of malformed/provider-failed episodes: preserved and reported; excluded from numerators only under §Exclusions; denominators always shown

Do not claim C1/C2 baseline equivalence solely from a non-significant
difference; report the paired effect and interval.

## Exclusions

Technical exclusions fixed now:

- provider outage before any model response;
- malformed provider payload after the protocol-defined retry;
- environment checksum mismatch;
- runner crash before the first agent action.

Agent mistakes, invalid tool calls, budget exhaustion, excessive discovery,
wrong completion claims, and timeouts caused by agent behavior are outcomes,
not exclusions.

## Illustrative trajectory selection

Predeclared algorithm (implemented in `src/cascadeshift/reporting/report.py`):

1. Candidate set: confirmatory task-world pairs where C1 majority-fails (≥2 of 3 repeats CSTS=0) and C2 majority-passes (≥2 of 3 CSTS=1).
2. Choose median cascade depth (event-chain length) among candidates, defined as the lower median (index (n-1)//2 of ascending depths).
3. Ties broken by lexicographically smallest `shift_id`.
4. Fallback if no candidate: pair with largest absolute pre-registered C2−C1 CSTS difference, same tie-break.

The report states this trajectory was selected post-run by the predeclared
algorithm and is illustrative, not additional statistical evidence.

## Freeze statement

Once this preregistration has a freeze manifest, signed tag, and external anchor,
the following changes are prohibited for that protocol version:

- no prompt changes;
- no discovery-tool changes;
- no ranker/top-k changes;
- no generator changes;
- no task changes;
- no metric changes;
- no exclusion changes;
- no seed replacement after inspecting outcomes.

Any amendment requires a new protocol version. Amended results are exploratory
until separately confirmed.

## Offline validation mode (research-integrity clarification)

`cascadeshift reproduce` executes the complete pipeline offline using the
deterministic scripted agents to validate mechanics end-to-end and produce a
report explicitly labeled `evidence_source: scripted_validation`. Scripted
episodes are never presented as model evidence. Headline claims require the
live-model confirmatory run executed by the owner after the external anchor.
