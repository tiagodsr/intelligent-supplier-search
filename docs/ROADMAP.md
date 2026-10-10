# Roadmap

Supplier Search Assistant: ordered build plan from the current data layer to a measured, documented, submittable project.

- Last updated: 2026-10-10
- Status: planning. The synthetic data layer exists on SQLite. Nothing else is built yet.
- Companion guide: [golden_set_guide.md](golden_set_guide.md) (how to know the data and build the evaluation set).

## 0. How to use this document

1. **This is a plan, not a description of the code.** Until Step 1a is merged, `README.md`, `CLAUDE.md` and `docs/data_model.md` describe the real, working state (SQLite). When this roadmap and those files disagree about the database, the files are the current truth and this roadmap is the target. Step 1a updates them in the same series of commits.
2. **Work top to bottom.** Every step has a Definition of Done (DoD). Do not start the next step before the DoD is met. Each step ends with a commit; each gate ends with a tag.
3. **Docs follow code.** If a step changes behaviour that `README.md`, `CLAUDE.md` or `docs/data_model.md` describe, update them in that step, not later.
4. **Tick the boxes** (`- [ ]` to `- [x]`) as you go. The checklists are the progress tracker.
5. Decisions that are still open are marked **D-OPEN** (section 4). Take the default unless you have a reason not to, and write down the choice.

## 1. Where the project stands today

| Area | Current state | What happens to it |
|---|---|---|
| Data generator | `scripts/build_db.py`: deterministic (seed 42), standard library only, writes SQLite | Step 1a: generation logic untouched, output target becomes PostgreSQL |
| Database | `data/suppliers.db` (SQLite, committed) | Step 1a: removed from the tree; preserved in git history by the tag `sqlite-final` |
| DB access | `src/assistant/db.py`: read-only SQLite connection | Steps 1a and 1b: role-based PostgreSQL connections |
| Tests | `tests/`: pytest suite for schema, integrity, data properties, determinism, read-only access | Step 1a: ported (some SQLite-specific tests are replaced) |
| Docs | `README.md`, `CLAUDE.md`, `docs/data_model.md` | Step 1a: updated for PostgreSQL |
| Config | `pyproject.toml` has no runtime dependencies; `.env.example` has `OPENAI_API_KEY`, `DB_PATH` | Dependencies are added step by step, never all at once |
| LLM code, embeddings, SQL guard, evals, API, UI, Docker | not started | Steps 2 to 10 |

## 2. What has to be delivered, and where this plan covers it

| Requirement | Covered by |
|---|---|
| At least two LLM steps (for example classify, then generate) | Intake (LLM #1) and SQL generation or agent (LLM #2). Steps 7 and 8 |
| Structured output validated against a schema | `IntakeResult`, `GeneratedSQL`, `FinalAnswer` in Pydantic. Steps 2 and 7 |
| Defined behaviour when information is missing | Explicit statuses (`needs_clarification`, `no_suppliers`, `out_of_scope`, `forbidden`, `refused`, `error`) and empty-result diagnostics. Steps 3, 7, 8 |
| A set of test cases | Golden set of 30 to 40 cases plus unit and integration tests. Steps 3 and 5 |
| Visible evidence (tools, retrieval, citations) | Every answer shows the SQL, the rows, the diagnostics and the trace. Steps 8 and 10 |
| Awareness of cost and latency | One LLM wrapper, a trace log, a results table. Steps 4, 7, 11 |
| Clear README and structure | Step 11 |
| Appropriate use of course concepts | Embeddings and semantic search (schema knowledge), structured outputs, dev/holdout evaluation, tool calling and a bounded agent loop, FastAPI, Docker |
| Central challenge of the Text-to-SQL idea | Correct failing queries from the error message; ask for clarification instead of guessing; evaluate against expected results. Steps 3, 5, 7, 8 |

## 3. Target architecture

```text
Streamlit UI ──HTTP──► FastAPI  POST /v1/query {role, question}
                          │ [1] request validated (Pydantic)
                          ▼
                 Role policy (code): role → database role, visible schema, limits
                          ▼
                 Intake (LLM #1, cheap model)            [2] IntakeResult
                   │ ambiguous / out of scope / unsafe ──► direct answer (no agent, no SQL)
                   ▼
        ┌──────────┴───────────────┬───────────────────────────────┐
        │ Variant A: fixed pipeline│ Variant B: Strands agent (LLM #2)
        │ resolve entities (code)  │ tools: search_schema · resolve_supplier · run_sql
        │ search_schema            │ the model chooses tools and order,
        │ generate SQL (structured)│ bounded by max steps, retries, timeout
        │ execute, 1 retry on error│
        └──────────┬───────────────┴───────────────────────────────┘
                   ▼                                              [3] tool results typed
        Shared safe execution: guard → EXPLAIN cost check → READ ONLY transaction
                              → PostgreSQL role with SELECT on its own views only
                   ▼
        Post-validation (code): sanity checks, empty-result diagnostics, confidence
                   ▼
        FinalAnswer                                               [4] validated
          status · answer · SQL · rows · evidence · assumptions · confidence · usage
        Every step above also writes one event to the trace log   [5] JSONL
```

The numbers in brackets are the points where Pydantic validates data.

**Two orchestrations, one set of parts.** Variant A is a fixed workflow: code decides every step and the LLM fills in specific slots. Variant B is an agent: inside a code-defined frame (validation, role policy, intake, limits, post-validation) the model decides which tools to call and in what order. Both use the same schema search, guard, executor, diagnostics, validators and answer schema, so the comparison measures orchestration and nothing else.

### Components

| Module (`src/assistant/`) | Kind | Responsibility |
|---|---|---|
| `config.py` | code | Settings from environment: models, limits, thresholds, URLs |
| `db.py` | code | Role-based PostgreSQL connections (`requester_ro`, `purchaser_ro`) |
| `schemas.py` | code | All Pydantic models, statuses, cross-field validators |
| `llm.py` | code | The only place that calls the LLM or embedding API; records tokens, latency, cost |
| `tracing.py` | code | JSONL trace events and summaries (sum, p50, p95) |
| `guard.py` | code | SQL parsing and rules (sqlglot, dialect `postgres`) |
| `executor.py` | code | Read-only transaction, timeout, EXPLAIN cost check, row cap, typed errors |
| `diagnostics.py` | code | Why a query returned zero rows (which filter removed them) |
| `schema_introspect.py`, `schema_index.py`, `schema_search.py` | code + embeddings | Schema knowledge: introspect, embed, search |
| `intake.py` | LLM #1 | Scope, entities, ambiguity, unsafe intent |
| `tools.py` | code | `search_schema`, `resolve_supplier`, `run_sql` as plain functions |
| `pipeline.py` | LLM #2 | Variant A |
| `agent.py` | LLM #2 | Variant B (Strands) |
| `validation.py` | code | Sanity checks, confidence score, final-answer rules |
| `api.py` | code | FastAPI app |

### Statuses

| Status | Meaning |
|---|---|
| `answered` | A query ran and the answer is grounded in its rows |
| `needs_clarification` | The question is ambiguous (entity, metric or period); options are offered |
| `no_suppliers` | A valid query returned nothing and the filters were verified (diagnostics attached) |
| `out_of_scope` | Not a supplier or procurement question |
| `forbidden` | A valid read request, but the data is not visible to this role |
| `refused` | Unsafe request (write or DDL intent, injection attempt) |
| `error` | Internal or upstream failure, or a limit was reached (steps, retries, time). Never shown as an answer |

## 4. Decisions

| # | Decision | Why | Cost or trade-off |
|---|---|---|---|
| D1 | **PostgreSQL**, not SQLite | Real roles and `GRANT`, `READ ONLY` transactions, `statement_timeout`, `EXPLAIN` with cost estimates, and Docker Compose is part of the course anyway | Needs Docker. Time-boxed: if Step 1a passes 2 days, stop and reassess (the tag `sqlite-final` is the way back) |
| D2 | **Synthetic data stays** | Deterministic, traps known by construction, no overlap with model training data, no privacy issue | The golden set depends on the exact data; see the guide for freezing and fingerprinting |
| D3 | **Role = database permission**, not a prompt instruction. No web search | A prompt rule can be talked around; a `GRANT` cannot. Removes an external provider, cost and unverifiable results | The requester and purchaser differ only in what they can read |
| D4 | Two schemas: `core` (tables) and `app` (views). Roles can only read views in `app` | The agent sees a small, documented, EUR-normalised semantic layer; base tables are unreachable | Six to nine small views to write (Step 1b) |
| D5 | **Variant A first, Variant B second** | A is a safety net that already meets the minimum; B is measured against it | None, A is also the baseline |
| D6 | **Strands Agents** for B (approved extension beyond course material) | Higher ambition for the portfolio | Tools are plain functions so the framework is replaceable. A 2-hour spike decides (Appendix B); fallback is the course's manual loop |
| D7 | **Embeddings only for schema knowledge** (descriptions, glossary, example queries) | It is the "semantic search over table descriptions and example queries" reuse | Not used on supplier data; see section 8 |
| D8 | **Confidence from objective signals**, not self-reported | Model self-confidence is poorly calibrated | The score is calibrated in the eval report |
| D9 | **Every LLM and embedding call goes through `llm.py`** | Cost and latency come for free and cannot be forgotten | Strands calls its model internally, so its usage is read from the run metrics instead |
| D10 | **Golden set is written before the pipeline**; few-shot examples never overlap it | Prevents tuning the test to the system | Costs two days before any model call |

### Open decisions (D-OPEN)

| # | Question | Default |
|---|---|---|
| D-OPEN-1 | Does the requester see catalog `unit_price`? | Yes; never contract discounts or spend |
| D-OPEN-2 | A purchase "in 2025": by cart `created_at` or `completed_at`? | `created_at` (the view exposes it as `cart_created_at`) |
| D-OPEN-3 | Language of the questions | English, plus a small Portuguese subset to test robustness |
| D-OPEN-4 | `is_preferred` and `active` as `BOOLEAN` or `0/1` | `BOOLEAN` |
| D-OPEN-5 | An ambiguous brand (two legal entities): ask or answer for both? | Ask (`needs_clarification`) |

## 5. Roles and data visibility

Four independent places enforce the role. Removing any one of them must not expose data.

1. **Role policy (code):** the role comes from the session, never from the question or from a tool argument.
2. **Schema search:** index entries carry the roles allowed to see them; a requester never receives purchaser-only tables, columns or examples.
3. **SQL guard:** the table allowlist is per role.
4. **Database:** each role has `SELECT` only on its own views.

| `app` view | requester_ro | purchaser_ro |
|---|:-:|:-:|
| `v_meta` (as-of date, data window) | yes | yes |
| `v_catalog_suppliers` (name, country, status, risk, preferred, payment terms) | yes | yes |
| `v_supplier_aliases` | yes | yes |
| `v_categories` | yes | yes |
| `v_catalog_items` (offers; price per D-OPEN-1) | yes | yes |
| `v_supplier_summary` (spend, carts, average delay) | no | yes |
| `v_completed_lines` (purchases, EUR-normalised) | no | yes |
| `v_contracts` (discounts, validity) | no | yes |
| `v_carts` (department, plant, status including cancelled) | no | yes |

When a purchaser query returns nothing, the answer is a diagnosis from the database (which filter removed the rows, what is close), not an external search.

## 6. The agent and its tools

### Tools (plain Python functions with typed results)

| Tool | The agent calls it when | It does not call it when | Returns |
|---|---|---|---|
| `search_schema(question)` | It needs to know which views, columns, values and business rules apply. Usually first. Again after an `undefined_column` or `undefined_table` error, or when the question touches a new concept | The context already covers the question | Top-k schema documents and example queries visible to the role |
| `resolve_supplier(name)` | The question names a supplier or brand, before filtering by it | No supplier is named | All matching suppliers (alias, name, country, status). More than one legal entity means ask the user, never pick one |
| `run_sql(sql)` | It has schema context and resolved identifiers. May be called several times: the query, a fix after an error, a verification query | It has not looked at the schema yet | `ok`, columns, rows (capped), `row_count`, `truncated`, typed error, diagnostics for empty results, timing |

There is no "answer" tool. The final answer is the validated `FinalAnswer`. The role is bound when the tools are created (a closure over the session), so the model cannot pass or change it.

### Typical sequences

1. **Plain question:** `search_schema` → `run_sql` → answer.
2. **Ambiguous brand:** `resolve_supplier("Brabon")` returns two legal entities → `needs_clarification` listing both. No SQL runs.
3. **Error and repair:** `search_schema` → `run_sql` (typed error `undefined_column`) → `search_schema` → `run_sql` → answer.
4. **Zero rows:** `run_sql` returns 0 rows with diagnostics (for example, removing the country filter yields 12 rows) → `no_suppliers` carrying that evidence, or a rewritten query.
5. **Forbidden:** a requester asks for spend → intake and policy mark it `forbidden`. If it reached the guard anyway, the guard or the database would refuse.

### Limits

Maximum tool calls per request, maximum SQL attempts (default 2 repairs), wall-clock timeout, and token budget. Hitting any limit ends in `error`, never a guessed answer.

### Final-answer rules (enforced in code, in the Pydantic validators)

- `answered` requires the SQL that was executed and a non-empty row preview or an aggregate value.
- `no_suppliers` requires diagnostics showing which filters were checked.
- `needs_clarification` requires a question and at least two options when the cause is entity ambiguity.
- `forbidden`, `refused`, `out_of_scope` require that no SQL was executed.
- Text coming from the database or from tool results is data. It is never followed as an instruction.

## 7. Build order

Gates summarise what must be true at a point in time. At each gate: commit, tag, update the results table in the README.

| Gate | After | What exists |
|---|---|---|
| 1 Safe foundation | Step 4 | Database, roles, guard, executor, measurement |
| 2 Minimum deliverable | Step 7 | Golden set, pipeline A, baseline report. Meets every course minimum |
| 3 Agent compared | Step 8 | Variant B and the A-versus-B table |
| 4 Submission | Step 11 | UI, Compose, final report, README |

### Step 0. Preparation (0.5 day)

Goal: a safe starting point.

- [ ] Local changes committed; `uv run pytest -q` is green on the SQLite version.
- [ ] `git tag sqlite-final` (keeps the SQLite DB, generator, tests and docs exactly as they are).
- [ ] Remote repository created and `main` plus tags pushed (the deliverable is a Git repository).
- [ ] Docker installed; `docker compose version` works.
- [ ] Optional: do Steps 1a and 1b on a branch and merge when the DoD is met.
- [ ] In parallel, before the final class: proposal material (problem and user, what it does, flow diagram, evaluation idea).

DoD: tag and remote exist, Docker runs.

### Step 1a. Port to PostgreSQL with parity (1 day)

Goal: the same data in PostgreSQL, rebuilt by one command. Nothing else changes.

Why now: the guard, the golden set and the schema index all depend on the final dialect and schema. Changing the database later invalidates them.

- [ ] `docker-compose.yml` with a `db` service: pinned major version (not `latest`), named volume, `pg_isready` healthcheck, credentials from `.env`.
- [ ] `.env.example`: replace `DB_PATH` with `DATABASE_ADMIN_URL` (role URLs arrive in Step 1b).
- [ ] `uv add "psycopg[binary]"`.
- [ ] Rewrite only the I/O of `scripts/build_db.py`: PostgreSQL DDL (see Appendix A), `%s` placeholders, tables in schema `core`, the two existing views in schema `app`. All code that draws from the random generator stays identical; the diff must show DDL, inserts and connection code only.
- [ ] Safety: the script refuses to run unless the target database name is on an allowlist (`suppliers`, `suppliers_test*`), because it drops and recreates schemas.
- [ ] One-off parity check against the tag: row counts and a per-table checksum must match the SQLite build (`git show sqlite-final:data/suppliers.db > /tmp/old.db`, then compare). Floats are compared after rounding to the stored precision.
- [ ] Port the tests (Appendix A lists what is SQLite-specific). Mark database tests `@pytest.mark.integration`.
- [ ] Replace `src/assistant/db.py` with a connection factory. Only `build_db.py` uses the admin URL.
- [ ] Remove `data/suppliers.db` from the tree.
- [ ] Update `CLAUDE.md` (stack, layout, commands, the read-only rule), `README.md` and `docs/data_model.md`.

DoD: `docker compose up -d db && uv run python scripts/build_db.py` rebuilds the database; `uv run pytest -q` is green; the parity check reports identical data; docs updated.

### Step 1b. Security and semantic layer (1 day)

Goal: roles that can read only what they should, and a schema that documents itself.

- [ ] Views in `app` per section 5, all selecting from `core`.
- [ ] `COMMENT ON` for every view and column, including the business rules from `docs/data_model.md` (completed-only purchases, EUR normalisation, as-of date, duplicate brands). The generator's DDL is the single source of these descriptions.
- [ ] Roles `requester_ro` and `purchaser_ro`: `LOGIN`, `USAGE` on `app`, `SELECT` only on their views, no access to `core`, `CREATE` revoked on `public`. Role-level settings: `default_transaction_read_only = on`, `statement_timeout`, `idle_in_transaction_session_timeout`, `search_path = app`.
- [ ] `db.get_connection(role)` returns a connection with `read_only` set; passwords come from the environment.
- [ ] Permission-matrix tests: each role can and cannot select what section 5 says; writes fail; `core` is unreachable; `SET ROLE` does not escalate; every `app` column has a comment.

DoD: the permission matrix passes; `\d+ app.v_completed_lines` in `psql` shows the descriptions.

### Step 2. Contracts (0.5 day)

Goal: fix the shapes that connect the components before building them.

- [ ] `schemas.py`: `Role`, `Status`, `QueryRequest`, `IntakeResult` (in scope, unsafe, intent, entities, ambiguity with interpretations), tool results (`SchemaSearchResult`, `SupplierCandidates`, `SqlResult` with typed error and diagnostics), `FinalAnswer` (status, answer, SQL, rows, evidence, assumptions, clarification, confidence, usage, warnings) and `TraceEvent`.
- [ ] Cross-field validators for the rules in section 6.
- [ ] Unit tests: valid objects round-trip; invalid combinations are rejected.

DoD: tests green, no LLM or database needed.

### Step 3. Safe executor (1.5 days)

Goal: any SQL string can be validated and run safely, with no LLM involved.

- [ ] `guard.py` (sqlglot, `dialect="postgres"`): exactly one statement; root is `SELECT` (read-only CTEs allowed); reject DDL, DML, `COPY`, `SET`, `DO`, `CALL`, `SELECT INTO`, `FOR UPDATE`; per-role schema-qualified table allowlist (reject `pg_*` and `information_schema`); function allowlist (reject `pg_sleep`, `pg_read_file`, `set_config`, `dblink`, `lo_*` and similar); force a `LIMIT`; subquery depth limit. Every rule is configurable and returns a structured `GuardViolation(rule, detail)`. Do not use regular expressions for security decisions.
- [ ] `executor.py`: role connection → `BEGIN READ ONLY` → `SET LOCAL statement_timeout` → `EXPLAIN (FORMAT JSON)` and reject above a cost threshold → run → fetch at most N+1 rows to detect truncation → always `ROLLBACK`. Map database errors to typed errors (`syntax_error`, `undefined_column`, `undefined_table`, `insufficient_privilege`, `timeout`, `cost_exceeded`). The error text is kept because the model uses it to repair the query.
- [ ] `diagnostics.py`: when a query returns zero rows, take its top-level `WHERE` conjuncts, rebuild a `COUNT(*)` query with each one removed (capped at 5), run them through the same guard and executor, and return `[{filter, rows_without_filter}]`. Time-box to half a day. Fallback: leave the check to the agent's prompt.
- [ ] Adversarial test suite: `DROP`, stacked statements, comment tricks, `pg_sleep`, `COPY ... TO PROGRAM`, `core.*` access, `SET ROLE`, `FOR UPDATE`, a CTE wrapping an `INSERT`, deeply nested subqueries, a cross join that explodes (caught by the cost check). Each case names the rule that must fire.
- [ ] Defence-in-depth test: send the same attacks directly to the database role, bypassing the guard, and assert that PostgreSQL itself refuses.

DoD: 100% of adversarial cases blocked by the intended rule; layer independence demonstrated.

### Step 4. Measurement (0.5 day)

Goal: from now on every model call is measured.

- [ ] `config/pricing.toml`: price per million tokens (input, cached input, output) per model, and for embeddings, with an "as of" date. Prices are copied into every report. They are not hardcoded in code.
- [ ] `llm.py`: wrapper over the OpenAI SDK exposing `parse()` (structured output, as in the course) and `embed()`. Each call produces a `TraceEvent` with step name, model, tokens, latency and cost.
- [ ] `tracing.py`: JSONL writer, run context (`run_id`, `case_id`, `session_id`, role), summaries (total, mean, p50, p95).
- [ ] Unit tests with a fake client.

DoD: cost, latency and token fields are correct for a fake call; p50 and p95 are computed.

### Step 5. Data profile and golden set (2 days)

Goal: know the data exactly and define "correct" before any model runs. Method and examples are in [golden_set_guide.md](golden_set_guide.md).

- [ ] `scripts/profile_db.py` writes `docs/data_profile.md` with the data fingerprint.
- [ ] Metric glossary (D-OPEN-2 and the other definitions) written down.
- [ ] `evals/golden_set.json`: 30 to 40 cases with expected SQL or expected status, role, category, split (about two thirds development, one third holdout, stratified).
- [ ] `evals/fewshot_examples.json`: at least 10 examples, a separate file.
- [ ] Tests: every `expected_sql` passes the guard for its role and runs; trap cases have a `naive_sql` whose result differs; golden and few-shot do not overlap; the data fingerprint matches; split sizes are right.
- [ ] Each case verified independently (checklist in the guide).

DoD: tests green; holdout cases frozen and not looked at again until Step 11.

### Step 6. Schema knowledge (embeddings) (1 day)

Goal: give the model the right part of the schema and the right examples. See section 8 for what embeddings are and when they run.

- [ ] `schema_introspect.py`: read `app` views, columns, comments and the distinct values of low-cardinality columns (status, risk rating, currency, department) into `SchemaDoc` objects with a `roles` field.
- [ ] Add curated glossary entries and the few-shot examples as documents.
- [ ] `scripts/build_index.py`: embed all documents in batches; write `index/schema_index.json` and `index/index_meta.json` (model, dimension, schema fingerprint, build date, cost).
- [ ] `schema_search.py`: `search_schema(question, role, k)` embeds the question, ranks by cosine similarity, filters by role. A short block of always-on rules (as-of date, completed-only, currency) lives in the system prompt and is not retrieved.
- [ ] Freshness check at startup: the live schema fingerprint must equal the one in `index_meta.json`, otherwise fail fast with the rebuild command.
- [ ] Retrieval evaluation: for every golden case, expected tables (parsed from `expected_sql` with sqlglot) against retrieved tables; report recall at k = 1, 3, 5 and choose k from the numbers.
- [ ] Tests: role filtering, fingerprint check, and a rule that every `app` column has a description.

DoD: retrieval recall measured and reported; k chosen.

### Step 7. Pipeline A and the baseline evaluation (2 days)

Goal: the first complete, measured run.

- [ ] `intake.py` (cheap model, structured output) and its tests with a fake client.
- [ ] `pipeline.py`: intake → direct answer if ambiguous, out of scope or unsafe → resolve supplier mentions in code (more than one legal entity means clarify) → `search_schema` → generate SQL (structured `GeneratedSQL`) → executor → one repair attempt with the error message → diagnostics on zero rows → explanation → `FinalAnswer`.
- [ ] `evals/run_eval.py --variant A --split development --repeat N --max-cases M`: prints a cost estimate and asks for confirmation above a threshold; writes JSON and Markdown to `evals/reports/` (git-ignored). Final reports are copied to `docs/results/`.
- [ ] Metrics: see section 10.
- [ ] Baseline report with a written diagnosis of at least one failure (retrieval, generation, validation or the test itself) before changing anything.

DoD: A runs on the development split; the report has accuracy per category and the cost and latency table. This is Gate 2.

### Step 8. Agent B (2 days)

Goal: the same parts, orchestrated by an agent, compared fairly with A.

- [ ] Spike first (at most 2 hours): Appendix B. If it fails, use the manual tool loop from the course.
- [ ] `tools.py` exposes the three tools; `agent.py` builds the agent with a role-bound tool factory, a role-aware system prompt (as-of date, rules), and limits.
- [ ] Trace via hooks: one `TraceEvent` per tool call; token usage from the run metrics.
- [ ] `FinalAnswer` produced through structured output and validated by the section 6 rules.
- [ ] Run B with 3 repetitions per case; produce the A-versus-B table.
- [ ] Diagnose, make one targeted improvement, re-run, record the before and after.

DoD: A-versus-B table (accuracy, clarification and refusal correctness, consistency, cost, latency) and a written analysis. This is Gate 3.

### Step 9. Post-validation and confidence (0.5 to 1 day)

- [ ] Sanity checks in code: amounts summed across currencies without conversion or grouping; dates outside the data window; key columns mostly `NULL` after a join; truncated results; results far outside plausible ranges.
- [ ] Confidence score from objective signals: guard passed on the first try, repairs used, sanity checks passed, schema coverage (tables used against tables retrieved), diagnostics present for empty results. Return the score and its breakdown.
- [ ] The eval report adds accuracy per confidence bucket (calibration).
- [ ] Unit tests for every check.

DoD: each check has a test; the calibration table is in the report.

### Step 10. API, UI and Compose (2 days)

- [ ] FastAPI: `POST /v1/query` (returns `FinalAnswer` with usage), `GET /v1/schema?role=` (schema visible to that role), `GET /health` (independent of the LLM). Input errors map to 400, upstream LLM failures to 502. Tests with `TestClient` and a fake LLM.
- [ ] Streamlit: role selector, chat, status badge, answer, SQL block, rows table, evidence and diagnostics, confidence breakdown, trace expander with steps, tools, latency and cost. The UI talks to the API over HTTP with timeouts.
- [ ] Compose: `db`, `api`, `ui`; secrets at runtime, never in images; healthchecks; a smoke-test script.

DoD: from a clean clone, three commands bring the system up and the smoke test passes.

### Step 11. Close-out (1 day)

- [ ] Run the holdout once, for A and B. Do not tune after seeing it.
- [ ] README leading with results: execution accuracy, status accuracy, unsafe queries executed (target zero), cost and latency table, known limitations.
- [ ] `docs/architecture.md` with the diagram; `CLAUDE.md` updated; `docs/results/` populated.
- [ ] Tag `v1.0`. Verify from a fresh clone.

DoD: Gate 4.

### Stretch (only after Gate 3)

- Variant C: B plus back-translation of the SQL to a question. Variant D: B plus two independent SQL queries compared. Both measured for accuracy, cost and latency; they are ablations, not features.
- Ablation: full schema in the prompt versus retrieved schema.
- `pg_trgm` similarity in `resolve_supplier` for typos.
- GitHub Actions running unit tests only.

## 8. Embeddings in this project

An embedding is a list of numbers (for `text-embedding-3-small`, 1536 of them) that represents the meaning of a text. Texts with similar meaning have nearby vectors, measured with cosine similarity. It is a cheap, separate model; it does not write text.

They are used in one place only: **finding the relevant part of the schema and the best example queries** for a question. They are not applied to supplier data (`resolve_supplier` uses aliases and SQL).

| When | What happens |
|---|---|
| Offline, once per schema change (`scripts/build_index.py`) | Each view description, column description, glossary rule and example question-to-SQL pair becomes a vector stored in `index/` |
| Online, on every `search_schema` call (Variant A and Variant B) | The question becomes one vector (one small API call), is compared with the stored vectors, and the top-k documents visible to the role are returned |

The index records a fingerprint of the schema it was built from. A mismatch stops the application with the rebuild command, which is how this project avoids stale documentation.

With nine views, putting the whole schema in the prompt would probably also work. Embeddings are used because they reduce prompt size (cost and latency), select the most relevant examples, and scale to a larger schema. The stretch ablation measures the difference.

## 9. Reuse from the course material

Adapt these patterns; do not import from the course repository.

| Pattern | Course location (in the course repository) | Used in |
|---|---|---|
| Structured output, safe fallback, untrusted user text | `sessions/02-prompting-structured-outputs/reference/intent_classifier.py` | Steps 2, 7 |
| Chunking, embeddings, cosine ranking, source recall | `sessions/rag_course_support.py` | Step 6 |
| Development and holdout, metrics, quality gate | `sessions/05-advanced-rag-evaluation/` | Steps 5, 7, 11 |
| Tool lifecycle, `call_id`, bounded loop, structured tool errors | `sessions/06-conversational-ai/`, `sessions/07-agent-api/agent_service.py` | Step 8 (fallback loop) |
| Typed FastAPI endpoints, error mapping, HTTP client | `sessions/07-agent-api/starter/` | Step 10 |

## 10. Measurement

### Trace event (one per step, same fields everywhere)

`run_id`, `case_id` (evals), `session_id`, `timestamp`, `role`, `step` (`intake`, `schema_search`, `sql_generation`, `tool_call`, `agent_run`, `explanation`, `validation`), `tool`, `model`, `input_tokens`, `output_tokens`, `cached_tokens`, `latency_ms`, `cost_usd`, `sql`, `decision` or `status`, `error_type`, `rows_returned`, `db_time_ms`, `explain_cost`.

### Rules

- Prices live in `config/pricing.toml` with an "as of" date and are copied into each report.
- Latency is wall-clock per request, split into LLM time, database time and overhead. Report p50 and p95.
- Strands makes its own model calls, so agent token usage comes from the run metrics (per run, not per call) and is converted into the same event shape.
- Pin model identifiers, use low temperature where the model supports it, and repeat each case 3 times to expose variance.
- Print an estimated cost before an eval run and require confirmation above a threshold. Use `--max-cases` and the development split while iterating.

### Evaluation metrics

| Metric | Definition |
|---|---|
| Execution accuracy | For answerable cases, the system's result matches the expected result under the guide's comparison rules |
| Status accuracy | Final status equals the expected status |
| Clarification precision and recall | Asked when it should have; did not ask when it should not |
| Refusal and permission correctness | Unsafe cases are `refused` and forbidden cases are `forbidden`, with zero statements executed |
| Unsafe queries executed | Counted from the audit log. Target: zero |
| Consistency | Share of cases with the same outcome in all 3 repetitions; also pass in all 3 |
| Cost | Per question (mean, p95) and per correct answer |
| Latency | p50 and p95 |
| Effort | LLM calls, tool calls and steps per question |
| Calibration | Accuracy per confidence bucket |

### README results table (skeleton)

| Variant | Execution accuracy | Status accuracy | Unsafe executed | Cost per question (mean, p95) | Latency (p50, p95) | LLM calls | Tool calls |
|---|---|---|---|---|---|---|---|
| A: fixed pipeline | | | | | | | |
| B: Strands agent | | | | | | | |

## 11. Testing strategy

| Tier | Needs | Marker | Examples |
|---|---|---|---|
| Unit | nothing | (default) | Pydantic validators, guard rules, sanity checks, cost maths, comparison rules |
| Integration | the Compose database | `integration` | Role permissions, executor, diagnostics, data properties, determinism, fingerprint, golden-set validity |
| Eval | OpenAI API (costs money) | `eval` or `evals/run_eval.py` | Accuracy, cost, latency, calibration |

```bash
uv run pytest -q -m "not integration and not eval"   # unit only
uv run pytest -q -m integration                      # needs: docker compose up -d db
uv run python evals/run_eval.py --variant A --split development --repeat 1 --max-cases 5
```

Register the markers in `pyproject.toml`. Database tests build a throwaway database (`suppliers_test_<random>`) and drop it afterwards; they never touch the development database.

## 12. Risks

| Risk | Mitigation |
|---|---|
| PostgreSQL port overruns | 2-day time box, parity check, tag `sqlite-final` as the way back |
| Strands friction (usage metrics, loop limits, structured output) | 2-hour spike; tools are plain functions; fallback is the course's manual loop |
| Eval cost grows unnoticed | Cost estimate and confirmation, `--max-cases`, development split only, cheap intake model |
| Golden set tuned to the system | Written first; holdout run once; few-shot disjoint from golden (tested) |
| Model nondeterminism | 3 repetitions, consistency metric, pinned models |
| Empty-result diagnostics too complex | Half-day time box; prompt-driven fallback |
| Scope creep | Stretch items only after Gate 3 |
| A reviewer cannot run it | README quick start, committed results in `docs/results/`, unit tests need no database or API key |
| Secrets leak | `.env` ignored, secrets passed at runtime, none in images or logs |
| Prompt injection through database text | Tool results are data; delimiters in prompts; a stubbed tool output carrying an injection string is part of the tests |

## 13. Schedule (14 working days)

The days are working sessions, not calendar days. There is no spare day, so the gates and the cut list are the safety margin.

| Day | Work | Gate |
|---|---|---|
| 1 | Step 0, Step 1a (port, parity) | |
| 2 | Step 1a tests and docs, Step 1b | |
| 3 | Step 2, Step 3 (guard) | |
| 4 | Step 3 (executor, diagnostics), Step 4 | **1** |
| 5 | Step 5: profile, glossary, first cases | |
| 6 | Step 5: remaining cases, validity tests, few-shot | |
| 7 | Step 6 | |
| 8 | Step 7: intake and pipeline A | |
| 9 | Step 7: eval runner, baseline report, README skeleton | **2** |
| 10 | Step 8: spike, tools, agent | |
| 11 | Step 8: runs, A versus B, one improvement | **3** |
| 12 | Step 9, API | |
| 13 | Step 10: UI, Compose, smoke test | |
| 14 | Step 11 | **4** |

If you are behind at the end of Day 9, ship Variant A (it satisfies every course minimum) and treat Variant B as a stretch.

**Cut list, in order:** (1) Docker packaging of `api` and `ui`, keeping `db`; (2) Streamlit polish; (3) repetitions from 3 to 2; (4) Step 9 reduced to sanity checks and a simple score; (5) automatic empty-result diagnostics replaced by a prompt rule; (6) Variant B becomes a stretch.

**Never cut:** the guard and role permissions, the golden set and comparison, the cost and latency table, the README results, the tests.

## 14. Out of scope

Web search and external alternatives; user feedback loop (if added later, feedback stays in a separate pool and is never promoted automatically into the golden set or the few-shot examples); React frontend; authentication; cloud deployment; multi-agent orchestration; long-term memory.

## 15. Definition of done for the project

- [ ] Two or more LLM steps, with Pydantic-validated outputs
- [ ] Every missing-information path ends in an explicit status, each covered by test cases
- [ ] Golden set (30 to 40 cases) and a runner; holdout run once
- [ ] Zero unsafe queries executed across the adversarial and golden cases, shown in the README
- [ ] Roles enforced by database permissions, with tests
- [ ] Cost and latency table for A and B in the README
- [ ] Evidence (SQL, rows, diagnostics, trace) visible with every answer
- [ ] Reproducible: one command rebuilds the database, one command rebuilds the schema index
- [ ] README: how to run, architecture diagram, results, limitations
- [ ] Unit tests pass without a database or an API key

## Appendix A. PostgreSQL port notes

Found by reading `scripts/build_db.py` and `tests/test_database.py`.

**Types**

- Dates stored as `TEXT` become `DATE`. Tests that compare ISO strings must compare `date` objects.
- Money stored as `REAL` becomes `NUMERIC`. The generator rounds prices and totals to 2 decimals and the largest line total is about 12.7 million, so `NUMERIC(14,2)` is exact. `discount_pct` has 1 decimal (`NUMERIC(4,1)`); `rate_to_eur` is a short decimal (`NUMERIC(10,4)`).
- `ROUND(x, n)` exists in PostgreSQL only for `NUMERIC`. With `REAL` or `DOUBLE PRECISION` the existing views would fail.
- `cart_id` starts at 2,000,000,001 and the largest is about 2,000,007,200, close to the 32-bit limit. Use `BIGINT` for it and for the columns that reference it.
- `is_preferred` and `active` are `0/1` integers today. D-OPEN-4 recommends `BOOLEAN`; update `data_model.md`, the tests and every example query that writes `= 1`.

**SQL differences**

- `LIKE` is case-sensitive in PostgreSQL. `data_model.md` fact 4 ("case-insensitive `LIKE`") becomes `ILIKE`.
- `SUM(x IS NULL)` is invalid. Use `COUNT(*) FILTER (WHERE x IS NULL)`.
- `strftime` becomes `to_char`, `date_trunc` or `EXTRACT`. Example queries and few-shot examples must use PostgreSQL idioms.
- `v_supplier_summary` selects columns beyond its `GROUP BY s.supplier_id`; this is valid in PostgreSQL because `supplier_id` is the primary key. Generated queries do not get that leniency in general, so few-shot examples should show full `GROUP BY` lists.
- Views run with the owner's privileges by default, which is what lets a role read a view without any access to `core`. Do not enable `security_invoker`.

**Generator**

- Placeholders `?` become `%s`. `executemany` is fast enough for about 25,000 rows.
- `PRAGMA foreign_keys` is not needed; PostgreSQL always enforces foreign keys.
- Insert order already respects foreign keys (categories before the rows that reference them); keep it.

**Tests that are SQLite-specific and must change**

| Test or helper | Change |
|---|---|
| `sqlite_master` listing of tables and views | Query `information_schema` for schemas `core` and `app` |
| `PRAGMA integrity_check`, `PRAGMA foreign_key_check` | Drop; constraints are enforced on insert |
| `sqlite3.iterdump()` hash | Hash a canonical `SELECT ... ORDER BY <pk>` of every table |
| `SUM(total_value_eur IS NULL)` | `COUNT(*) FILTER (WHERE ...)` |
| Date string comparisons against `meta` values | Compare `date` objects |
| Read-only tests (`PRAGMA query_only`, `OperationalError`) | Role tests: writes raise a read-only or privilege error |
| Missing-file and `DB_PATH` tests | Connection-URL tests |
| "Committed DB opens read-only" | Remove |

**Test database:** a fixture creates `suppliers_test_<random>` with the admin URL, builds it, and drops it at the end.

## Appendix B. Strands spike checklist

Time box: 2 hours. Verify each point against the current documentation before relying on it; names below come from the documentation at the time of writing.

- [ ] Install with the OpenAI extra (`strands-agents[openai]`) and build the model with `OpenAIModel(client_args={"api_key": ...}, model_id=...)`. The default provider is Amazon Bedrock, so the model must be passed explicitly.
- [ ] A plain function decorated with `@tool` is passed to `Agent(tools=[...])`; the docstring is what the model reads. Confirm that typed arguments and a Pydantic return value are handled.
- [ ] Token usage: read `result.metrics.accumulated_usage` after a run and map it into a `TraceEvent`. Also check the per-tool metrics available on the run.
- [ ] Limits: there may be no single "max steps" setting. A hook on `BeforeToolCallEvent` can count tool calls and set `cancel_tool` with a reason string, which is returned to the model. Confirm this, and add a wall-clock timeout.
- [ ] Structured final answer: the current documentation recommends passing a Pydantic model as `structured_output_model` on the call and reading `AgentResult.structured_output`; the older `agent.structured_output()` is deprecated. Handle `StructuredOutputException`.
- [ ] Exit criterion: a toy agent answers one question using one tool, with usage and a tool-call trace captured. If any item cannot be done within the time box, use the course's manual loop and keep the same tools.

References: [Python quickstart](https://strandsagents.com/docs/user-guide/quickstart/python/), [OpenAI provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/openai/index.md), [metrics](https://strandsagents.com/docs/user-guide/observability-evaluation/metrics/), [structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/), [hooks](https://mono-repo-docs.strandsagents.com/docs/user-guide/concepts/agents/hooks/), [limiting tool calls with a hook](https://dev.classmethod.jp/en/articles/strands-agents-limit-tool-counts-guard/).

## Appendix C. Target environment and commands

```text
OPENAI_API_KEY=
OPENAI_INTAKE_MODEL=            # cheap model for intake
OPENAI_AGENT_MODEL=             # model for pipeline A generation and for agent B
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
DATABASE_ADMIN_URL=             # build_db.py only
DATABASE_URL_REQUESTER=
DATABASE_URL_PURCHASER=
TRACE_PATH=                     # JSONL trace output
```

```bash
docker compose up -d db                      # start PostgreSQL
uv run python scripts/build_db.py            # rebuild data (drops and recreates schemas core and app)
uv run python scripts/build_index.py         # rebuild the schema index (calls the embeddings API)
uv run python scripts/profile_db.py          # regenerate docs/data_profile.md
uv run pytest -q                             # tests
uv run python evals/run_eval.py --variant B --split development --repeat 3
```
