# Phase 9 -- Evaluation Layer

> **Objective:** Measure the quality of reasoning outputs.
>
> Phase 9 answers "How good was this reasoning decision?" It creates
> bounded evaluation scores and evidence records. It does not learn from them,
> validate knowledge, or change recommendations yet.

---

## Product Context

Existing drone platforms monitor missions. TARS is designed to learn from
missions.

Phases 1 through 8 create the evidence needed for evaluation:

- Phase 2 stores replayable mission history.
- Phase 4 creates deterministic incident records.
- Phase 5 produces advisory root-cause reasoning.
- Phase 6 traces every reasoning execution in Phoenix.
- Phase 7 connects missions, incidents, root causes, mitigations, and outcomes
  in Neo4j operational memory.
- Phase 8 lets the agent inspect bounded prior reasoning traces.

Phase 9 turns this evidence into explicit quality measurements. The platform
can now ask:

```text
Was the reasoning correct, consistent, and useful after the mission outcome
was known?
```

These evaluations become the measured substrate for later learning. Without
metrics, Phase 10 would only have opinions and anecdotes. With Phase 9, it has
auditable quality signals.

---

## Scope

Phase 9 introduces an evaluation service that compares reasoning outputs
against bounded ground-truth labels, mission outcomes, deterministic incident
facts, and trace metadata.

Phase 9 owns:

- Evaluation configuration and scoring thresholds.
- Evaluation request and result models.
- Root-cause accuracy scoring.
- Recommendation quality scoring.
- Response consistency checks.
- False-positive and false-negative incident/reasoning labels.
- Evaluation persistence.
- Optional Phoenix eval export or trace annotation.
- API endpoints for evaluating one reasoning result, a mission, or a batch.
- Tests proving evaluations are bounded, explainable, and non-adaptive.

Phase 9 should answer:

- "Was this root-cause classification correct?"
- "Was the recommendation aligned with the eventual outcome?"
- "Did similar incidents receive consistent reasoning?"
- "Did the reasoning create a false positive?"
- "Did the system miss an incident or root cause?"
- "Which reasoning outputs are low-confidence and low-quality?"
- "Which traces have evaluation scores attached?"

---

## Success Statement

Phase 9 succeeds when a completed mission or reasoning result can be evaluated
against explicit evidence and produce durable, inspectable scores without
changing operational behavior.

```text
Mission outcome + incident facts + reasoning result + trace metadata
    -> Evaluation service
    -> bounded metrics and explanations
    -> persisted evaluation record
    -> optional Phoenix eval visibility
```

An operator should be able to inspect why a reasoning output was scored as
correct, partially correct, incorrect, inconsistent, false positive, or false
negative.

---

## Non-Goals

Phase 9 must not:

- Generate candidate learning; that belongs to Phase 10.
- Promote validated knowledge; that belongs to Phase 11.
- Adapt recommendations from validated knowledge; that belongs to Phase 12.
- Automatically change Phase 5 prompts or model settings.
- Call PX4, MAVSDK, or any flight-control interface.
- Treat LLM judgment as ground truth without an explicit label or outcome.
- Evaluate raw telemetry directly.
- Store full Phoenix traces, prompts, responses, credentials, or raw telemetry.
- Make Phoenix, Gemini, Neo4j, or a live simulator required for evaluation.
- Block Phase 5 reasoning when evaluation infrastructure is unavailable.

Phase 9 grades the decision after evidence is available. It does not teach the
system what to do next.

---

## Architecture

```mermaid
flowchart LR
    A[(Phase 2 Mission Replay)] --> E[Phase 9 Evaluation Service]
    B[Phase 4 Incident API] --> E
    C[(Phase 5 Reasoning Store)] --> E
    D[(Phase 7 Operational Memory)] -. outcome labels .-> E
    F[(Phoenix Traces)] -. trace identifiers .-> E
    E --> G[(Evaluation Store)]
    E -. optional eval visibility .-> H[Phoenix]
    E -. future input .-> I[Phase 10 Learning Engine]
```

### Runtime Boundary

```text
Flight-critical path:
PX4 -> telemetry -> state -> deterministic incident detection

Analysis path:
reasoning result + outcome evidence -> evaluation -> stored quality metrics
```

Phase 9 runs after or beside mission analysis. It is not part of control,
state classification, incident detection, or live reasoning generation.

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Evaluation Config** | Load thresholds, weights, store settings, and optional Phoenix export settings. |
| **Evaluation Models** | Define bounded requests, labels, metrics, evidence, and responses. |
| **Ground Truth Adapter** | Load operator labels, mission outcomes, and deterministic incident facts. |
| **Reasoning Adapter** | Read Phase 5 reasoning results without invoking the provider. |
| **Trace Adapter** | Attach Phoenix trace IDs and safe metadata only. |
| **Evaluator** | Compute root-cause, recommendation, consistency, false-positive, and false-negative scores. |
| **Evaluation Store** | Persist evaluation results and expose query APIs. |
| **Phoenix Eval Exporter** | Optionally publish scores to Phoenix without making Phoenix required. |
| **API Layer** | Provide health, evaluate, batch, and lookup endpoints. |

---

## Source-of-Truth Boundaries

| Data | Source of Truth | Phase 9 Behavior |
|------|-----------------|------------------|
| Mission events | Phase 2 PostgreSQL | Read bounded mission/replay identifiers and outcome references. |
| Incident facts | Phase 4 Incident API | Read deterministic incident records and labels. |
| Reasoning results | Phase 5 Redis | Read advisory reasoning outputs and metadata. |
| Reasoning traces | Phoenix | Reference trace IDs and optional eval export; do not copy trace bodies. |
| Operational outcomes | Phase 7 Neo4j / operator labels | Read outcome labels and mitigation results. |
| Evaluation records | Phase 9 store | Own metric scores, explanations, and provenance. |
| Candidate learning | Future Phase 10 | Not created in Phase 9. |

Evaluation records are durable product data. Phoenix remains the observability
surface; it is not the only source of evaluation history.

---

## Metric Contract

All metric outputs must be bounded, explainable, and versioned.

### Core Metrics

| Metric | Type | Range | Meaning |
|--------|------|-------|---------|
| `root_cause_accuracy` | float | `0.0` to `1.0` | Whether the predicted root cause matches the accepted label. |
| `recommendation_accuracy` | float | `0.0` to `1.0` | Whether the recommendation aligned with the successful or preferred mitigation. |
| `response_consistency` | float | `0.0` to `1.0` | Whether similar incidents received compatible reasoning outputs. |
| `false_positive` | bool | true/false | Reasoning or incident claimed a problem unsupported by later evidence. |
| `false_negative` | bool | true/false | System missed a problem later confirmed by evidence. |
| `overall_score` | float | `0.0` to `1.0` | Weighted aggregate for filtering and future learning. |

### Classification Labels

```text
correct
partially_correct
incorrect
insufficient_evidence
not_applicable
```

`insufficient_evidence` is a first-class result. Phase 9 must prefer
uncertainty over invented certainty.

### Evidence Levels

```text
operator_label
mission_outcome
deterministic_incident
historical_consistency
trace_metadata
```

Evidence levels are ordered from strongest to weakest. Trace metadata can
explain execution behavior, but it cannot by itself prove root-cause truth.

---

## Evaluation Data Model

### `EvaluationRequest`

```json
{
  "mission_id": "mission_20260618_120000",
  "incident_id": "inc_01J...",
  "reasoning_id": "reason_01J...",
  "trace_id": "abc123",
  "ground_truth": {
    "root_cause": "gps_interference",
    "preferred_mitigation": "switch_to_visual_odometry",
    "outcome": "recovered"
  },
  "evaluate_consistency": true,
  "overwrite": false
}
```

Fields:

- `mission_id`: Required mission identifier.
- `incident_id`: Optional when evaluating a mission-level false negative.
- `reasoning_id`: Optional when evaluating incident detection only.
- `trace_id`: Optional Phoenix trace correlation.
- `ground_truth`: Optional explicit label payload. If omitted, the service
  attempts to load outcome evidence from configured adapters.
- `evaluate_consistency`: Whether to compare against similar evaluated cases.
- `overwrite`: Whether to replace an existing evaluation for the same target.

### `GroundTruthLabel`

```json
{
  "root_cause": "gps_interference",
  "preferred_mitigation": "switch_to_visual_odometry",
  "outcome": "recovered",
  "source": "operator_label",
  "labeled_by": "operator",
  "labeled_at": "2026-06-18T10:30:00Z"
}
```

`source` must be one of:

```text
operator_label
mission_outcome
synthetic_test_case
deterministic_rule
```

### `EvaluationMetric`

```json
{
  "name": "root_cause_accuracy",
  "score": 1.0,
  "label": "correct",
  "evidence": ["operator_label", "deterministic_incident"],
  "explanation": "Predicted root cause matched accepted label."
}
```

### `EvaluationResult`

```json
{
  "evaluation_id": "eval_01J...",
  "mission_id": "mission_20260618_120000",
  "incident_id": "inc_01J...",
  "reasoning_id": "reason_01J...",
  "trace_id": "abc123",
  "metrics": [
    {
      "name": "root_cause_accuracy",
      "score": 1.0,
      "label": "correct",
      "evidence": ["operator_label"],
      "explanation": "Predicted root cause matched accepted label."
    }
  ],
  "overall_score": 0.86,
  "false_positive": false,
  "false_negative": false,
  "evidence_level": "operator_label",
  "evaluator_version": "v1.0",
  "created_at": "2026-06-18T10:35:00Z",
  "advisory_only": true
}
```

Evaluation result fields must not contain raw prompts, full trace bodies,
credentials, or raw telemetry.

---

## Scoring Rules

### Root-Cause Accuracy

Root-cause scoring compares the Phase 5 `root_cause` against the accepted
ground-truth root cause.

Rules:

- Exact normalized match: `1.0`, label `correct`.
- Known alias match: `1.0`, label `correct`.
- Same root-cause family: `0.5`, label `partially_correct`.
- Different root cause with enough evidence: `0.0`, label `incorrect`.
- Missing accepted label: `null` score, label `insufficient_evidence`.

Alias examples:

```text
gps_drift -> gps_interference
localization_loss -> gps_interference
wind_disturbance -> environmental_wind
battery_sag -> power_instability
```

Aliases must be deterministic and versioned in configuration or a local mapping
module. They must not be inferred by a live LLM during tests.

### Recommendation Accuracy

Recommendation scoring checks whether the advisory recommendation aligns with
the preferred or successful mitigation.

Rules:

- Recommendation names the preferred mitigation: `1.0`.
- Recommendation supports a compatible mitigation family: `0.5`.
- Recommendation is advisory but not useful for the outcome: `0.0`.
- Recommendation contains a direct flight-control command: validation failure.
- No preferred mitigation available: `null`, label `insufficient_evidence`.

Recommendation accuracy is not command execution. It measures advisory quality
after the fact.

### Response Consistency

Consistency scoring compares the current reasoning output with previously
evaluated similar incidents.

Similarity may use:

- Incident type.
- Severity.
- Root-cause family.
- Mission phase.
- Outcome class.

Rules:

- Compatible root cause and mitigation family: high consistency.
- Compatible root cause with different but non-conflicting mitigation:
  partial consistency.
- Same incident family with contradictory reasoning: low consistency.
- Fewer than the configured minimum comparison cases: insufficient evidence.

Consistency must not imply correctness. A system can be consistently wrong.

### False Positives

A false positive occurs when the system produced or reasoned about a problem
that later evidence does not support.

Examples:

- Incident classified as `navigation_instability`, but mission outcome and
  operator label confirm nominal behavior.
- Reasoning claims `gps_interference`, but accepted root cause is
  `operator_abort` or `planned_stop`.

False-positive labels require outcome or operator evidence. Trace history alone
is not enough.

### False Negatives

A false negative occurs when later evidence confirms a problem that the system
failed to detect or reason about.

Examples:

- Mission outcome shows `battery_failure`, but no incident was emitted.
- Incident was emitted, but no reasoning was generated for it.
- Reasoning ignored the confirmed root cause despite sufficient incident facts.

False-negative evaluation may be mission-level and not tied to a single
`reasoning_id`.

### Overall Score

Default weighting:

```text
root_cause_accuracy: 0.40
recommendation_accuracy: 0.35
response_consistency: 0.15
false_positive_penalty: 0.05
false_negative_penalty: 0.05
```

Scores with `insufficient_evidence` should be excluded from the denominator.
Penalty terms should apply only when evidence is strong enough to support the
label.

---

## Storage Design

Phase 9 should use PostgreSQL for durable evaluation records.

### Tables

#### `evaluation_results`

Columns:

- `evaluation_id` primary key.
- `mission_id`.
- `incident_id` nullable.
- `reasoning_id` nullable.
- `trace_id` nullable.
- `overall_score` nullable.
- `root_cause_score` nullable.
- `recommendation_score` nullable.
- `consistency_score` nullable.
- `false_positive` boolean.
- `false_negative` boolean.
- `evidence_level`.
- `evaluator_version`.
- `advisory_only` boolean, always true.
- `created_at`.
- `updated_at`.

#### `evaluation_metrics`

Columns:

- `metric_id` primary key.
- `evaluation_id` foreign key.
- `name`.
- `score` nullable.
- `label`.
- `evidence` JSON array.
- `explanation`.
- `created_at`.

#### `ground_truth_labels`

Columns:

- `label_id` primary key.
- `mission_id`.
- `incident_id` nullable.
- `root_cause` nullable.
- `preferred_mitigation` nullable.
- `outcome` nullable.
- `source`.
- `labeled_by` nullable.
- `labeled_at`.
- `created_at`.

### Idempotency

Default uniqueness:

```text
mission_id + incident_id + reasoning_id + evaluator_version
```

For mission-level false-negative evaluations, `incident_id` and `reasoning_id`
may be null. The uniqueness rule should treat mission-level evaluations as a
separate target type.

---

## API Contract

Base path:

```text
/api/v1/evaluations
```

### `GET /health`

Returns service readiness.

```json
{
  "status": "ok",
  "postgres": "ok",
  "phase4": "ok",
  "phase5": "ok",
  "phase7": "disabled",
  "phoenix": "disabled"
}
```

Phase 7 and Phoenix are optional. Their unavailability must not make the
service unhealthy unless explicitly configured as required.

### `POST /api/v1/evaluations/evaluate`

Evaluate one reasoning result or mission-level target.

Response:

```json
{
  "evaluation_id": "eval_01J...",
  "mission_id": "mission_20260618_120000",
  "incident_id": "inc_01J...",
  "reasoning_id": "reason_01J...",
  "overall_score": 0.86,
  "false_positive": false,
  "false_negative": false,
  "metrics": []
}
```

### `POST /api/v1/evaluations/batch`

Evaluate a bounded list of targets.

Rules:

- Maximum batch size from config.
- Partial failures are returned per item.
- A failed item must not abort successful evaluations.

### `GET /api/v1/evaluations/{evaluation_id}`

Return a stored evaluation result.

### `GET /api/v1/evaluations/mission/{mission_id}`

Return evaluations for one mission.

### `GET /api/v1/evaluations/reasoning/{reasoning_id}`

Return evaluations for one reasoning result.

### `POST /api/v1/evaluations/labels`

Create or update an explicit ground-truth label.

This endpoint should be useful for tests and operator-reviewed workflows.

---

## Phoenix Integration

Phoenix is optional in Phase 9.

When enabled, Phase 9 may:

- Export evaluation scores associated with a trace ID.
- Add evaluation spans around scoring work.
- Attach `evaluation_id`, metric names, labels, and scores as span attributes.

Phase 9 must not:

- Require a live Phoenix server for tests.
- Copy full trace bodies into the evaluation store.
- Use trace frequency as correctness.
- Treat Phase 8 introspection summaries as evaluation labels.

Suggested span names:

```text
evaluation.evaluate
evaluation.load_reasoning
evaluation.load_ground_truth
evaluation.score_root_cause
evaluation.score_recommendation
evaluation.score_consistency
evaluation.persist
evaluation.export_phoenix
```

Suggested attributes:

```text
tars.evaluation.id
tars.evaluation.version
tars.evaluation.overall_score
tars.evaluation.root_cause_score
tars.evaluation.recommendation_score
tars.evaluation.consistency_score
tars.evaluation.false_positive
tars.evaluation.false_negative
```

---

## Configuration

Environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `EVALUATION_ENABLED` | `true` | Enable the Phase 9 service. |
| `EVALUATION_DATABASE_URL` | `postgresql+asyncpg://tars:tars@localhost:5432/tars` | PostgreSQL URL. |
| `EVALUATION_VERSION` | `v1.0` | Evaluator version stamped on results. |
| `EVALUATION_BATCH_LIMIT` | `50` | Maximum targets per batch request. |
| `EVALUATION_CONSISTENCY_MIN_CASES` | `3` | Minimum historical cases for consistency scoring. |
| `EVALUATION_SIMILARITY_LIMIT` | `20` | Maximum similar evaluated cases to compare. |
| `EVALUATION_EXPORT_PHOENIX` | `false` | Export eval scores/spans to Phoenix when possible. |
| `EVALUATION_REQUIRE_OPERATOR_LABEL` | `false` | Require explicit labels instead of outcome-derived labels. |
| `EVALUATION_ROOT_CAUSE_WEIGHT` | `0.40` | Overall score root-cause weight. |
| `EVALUATION_RECOMMENDATION_WEIGHT` | `0.35` | Overall score recommendation weight. |
| `EVALUATION_CONSISTENCY_WEIGHT` | `0.15` | Overall score consistency weight. |
| `EVALUATION_FALSE_POSITIVE_WEIGHT` | `0.05` | Overall score false-positive penalty weight. |
| `EVALUATION_FALSE_NEGATIVE_WEIGHT` | `0.05` | Overall score false-negative penalty weight. |

Invalid weights should fail configuration validation. Weight totals should be
normalized or rejected deterministically.

---

## Package Layout

```text
src/tars/phase9/
├── __init__.py
├── api.py
├── config.py
├── database.py
├── evaluator.py
├── ground_truth.py
├── models.py
├── phoenix_exporter.py
├── repository.py
├── service.py
└── adapters/
    ├── __init__.py
    ├── phase4_client.py
    ├── phase5_client.py
    └── phase7_client.py
```

Tests:

```text
tests/phase9/
├── __init__.py
├── conftest.py
├── test_api.py
├── test_config.py
├── test_evaluator.py
├── test_ground_truth.py
├── test_models.py
├── test_phoenix_exporter.py
├── test_repository.py
└── test_service.py
```

Migration:

```text
migrations/versions/009_create_phase9_evaluation_tables.py
```

---

## Failure Behavior

| Scenario | Required behavior |
|----------|-------------------|
| Evaluation disabled | API reports disabled; no scoring is performed. |
| Missing reasoning result | Return 404 or item-level batch failure. |
| Missing ground truth | Return evaluation with `insufficient_evidence`; do not invent labels. |
| Missing Phoenix trace | Evaluate from reasoning and labels; trace ID remains nullable. |
| Phoenix unavailable | Log safe warning; persist evaluation without Phoenix export. |
| Phase 7 unavailable | Skip outcome lookup unless required; accept explicit labels. |
| Malformed label | Return validation error; do not persist partial metric rows. |
| Store unavailable | Return service error; do not claim evaluation succeeded. |
| Duplicate request | Return existing result when `overwrite=false`. |
| Batch partial failure | Return per-item success/error payloads. |

---

## Security and Safety

- Evaluation is analysis-only.
- Evaluation must never call flight-control APIs.
- Evaluation must never mutate mission, incident, reasoning, or graph records.
- Evaluation labels must be explicit about their source.
- Stored explanations must be bounded in length.
- Secrets in labels, reasoning text, or trace metadata must be redacted.
- API responses must not include raw telemetry, prompts, responses, or full
  trace bodies.
- All persisted results must include `advisory_only=true`.

---

## Testing Strategy

Automated tests must not require PX4, Gazebo, Gemini, Neo4j, Phoenix, or live
upstream APIs. Use fake clients and local stores.

### Model Tests

- Metric scores are clamped or rejected outside `0.0` to `1.0`.
- Unknown metric names are rejected.
- Unknown labels are rejected.
- `advisory_only=false` is rejected.
- Overlong explanations are truncated or rejected.
- Secret-like text is redacted.
- Missing evidence produces `insufficient_evidence`.

### Evaluator Tests

- Exact root-cause match scores `1.0`.
- Alias root-cause match scores `1.0`.
- Same root-cause family scores partial credit.
- Mismatched root cause scores `0.0`.
- Missing ground truth returns insufficient evidence.
- Recommendation matching preferred mitigation scores `1.0`.
- Conflicting recommendation scores `0.0`.
- Direct flight-control command fails validation.
- Consistency scoring requires the minimum number of cases.
- False-positive and false-negative labels require strong evidence.
- Overall score excludes insufficient-evidence metrics from denominator.

### Ground Truth Tests

- Explicit operator labels take priority over derived labels.
- Mission outcomes can provide labels when configured.
- Deterministic incident facts can support evidence but not replace outcome
  labels for root-cause truth.
- Missing labels are represented clearly.

### Repository Tests

- Evaluation results persist with all metric rows.
- Duplicate requests are idempotent.
- `overwrite=true` replaces the prior version safely.
- Mission lookup returns all evaluations.
- Reasoning lookup returns all evaluations for one reasoning ID.
- No raw prompt, response, telemetry, or trace body fields are stored.

### Service Tests

- Evaluating one reasoning result loads reasoning and ground truth.
- Batch evaluation returns per-item status.
- Missing reasoning returns a clear error.
- Missing ground truth returns insufficient evidence.
- Phoenix export failure does not fail persistence.
- Phase 7 unavailable does not fail evaluation when explicit labels exist.

### API Tests

- Health endpoint reports PostgreSQL and optional dependencies.
- Single evaluate endpoint returns evaluation result.
- Batch endpoint enforces configured maximum size.
- Label endpoint stores explicit labels.
- Lookup endpoints return stored results.
- Validation errors are safe and bounded.

### Integration Tests

- Phase 5 reasoning result can be evaluated without invoking Gemini.
- Phase 8 introspection metadata can be referenced but not treated as ground
  truth.
- Phase 9 results can be linked to Phoenix trace IDs without live Phoenix.
- Full Phase 9 tests run without PX4, Phoenix, Gemini, Neo4j, or upstream APIs.

---

## Implementation Steps

### Step 1 -- Define Models and Configuration

- Create `src/tars/phase9/config.py`.
- Define evaluator version, limits, weights, optional dependency settings, and
  Phoenix export flag.
- Create `src/tars/phase9/models.py`.
- Add request, label, metric, result, batch, and health models.
- Enforce score bounds, enum values, `advisory_only=true`, and bounded text.

### Step 2 -- Create Evaluation Store

- Add PostgreSQL migration for evaluation tables.
- Implement `database.py` and `repository.py`.
- Support create, get by ID, get by mission, get by reasoning, label upsert,
  and duplicate detection.
- Keep repository tests independent of live upstream services.

### Step 3 -- Implement Ground Truth Loading

- Create `ground_truth.py`.
- Support explicit request labels first.
- Support stored labels second.
- Support optional outcome-derived labels from Phase 7 when available.
- Return structured missing-evidence results instead of raising for normal
  absence.

### Step 4 -- Implement Deterministic Evaluator

- Create `evaluator.py`.
- Implement root-cause normalization, aliases, and families.
- Implement recommendation mitigation matching.
- Implement consistency comparison against stored evaluations.
- Implement false-positive and false-negative scoring.
- Implement weighted overall score.
- Keep scoring deterministic and testable.

### Step 5 -- Implement Service Orchestration

- Create `service.py`.
- Load reasoning results from Phase 5 adapters or direct store clients.
- Load incident facts from Phase 4 when needed.
- Load ground-truth labels.
- Run evaluator.
- Persist result.
- Optionally export to Phoenix.
- Handle fail-open behavior for optional dependencies.

### Step 6 -- Add API

- Create `api.py`.
- Add health, evaluate, batch, lookup, and label endpoints.
- Validate batch size and overwrite behavior.
- Return safe error payloads.
- Add startup/shutdown lifecycle for PostgreSQL resources.

### Step 7 -- Add Phoenix Eval Export

- Create `phoenix_exporter.py`.
- Export evaluation spans and score attributes when enabled.
- Never require Phoenix for local tests.
- Confirm export failures do not roll back persisted evaluations.

### Step 8 -- Add Scripts and Documentation

- Add `scripts/start_evaluation_api.sh`.
- Update `.env.example` with Phase 9 variables.
- Update `README.md` phase table, tree, environment section, and usage section.
- Document example evaluate and label requests.

### Step 9 -- Verify End to End

- Run `pytest tests/phase9 -q`.
- Run `pytest tests/phase5 tests/phase8 tests/phase9 -q`.
- Run the full suite when dependencies are installed.
- Confirm no live Phoenix, Gemini, Neo4j, PX4, or upstream API is required for
  automated Phase 9 tests.

---

## Acceptance Criteria

1. Phase 9 exposes an evaluation service with health, evaluate, batch, label,
   and lookup endpoints.
2. Evaluation records are persisted durably in PostgreSQL.
3. Root-cause accuracy, recommendation accuracy, response consistency, false
   positives, false negatives, and overall score are represented explicitly.
4. Missing ground truth produces `insufficient_evidence` rather than invented
   scores.
5. Evaluation outputs are bounded, explainable, versioned, and advisory-only.
6. Evaluation can reference Phoenix trace IDs without copying trace bodies.
7. Phoenix export is optional and fail-open.
8. Evaluation does not invoke Gemini or mutate reasoning results.
9. Evaluation does not create candidate or validated knowledge.
10. Evaluation does not adapt future recommendations.
11. Evaluation never calls PX4, MAVSDK, or flight-control APIs.
12. Automated tests run without live Phoenix, Gemini, Neo4j, PX4, or upstream
    services.

---

## Deliverables

- `src/tars/phase9/` evaluation package.
- Phase 9 PostgreSQL migration.
- Phase 9 API service.
- Deterministic evaluator with metric contracts.
- Ground-truth label model and label storage.
- Optional Phoenix evaluation export.
- Phase 9 tests.
- README and `.env.example` updates.
- Startup script for the evaluation API.

---

## Phase 10 Handoff

Phase 9 produces measured evaluation records. Phase 10 turns those records into
candidate learning.

Phase 10 can consume:

- Evaluation scores and metric labels.
- Root-cause and mitigation outcomes.
- False-positive and false-negative signals.
- Evaluation explanations.
- Reasoning IDs and Phoenix trace IDs.
- Mission and incident identifiers for graph lookup.

Phase 10 must treat Phase 9 evaluations as evidence, not automatic truth. It
should generate candidate knowledge only after aggregating enough evaluated
cases to support a pattern.
