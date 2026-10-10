# CLAUDE.md

## Project
Supplier Search Assistant: a Text-to-SQL assistant for procurement questions (a bootcamp
final project, graded on this repo). Planned pipeline: an intake step (Pydantic structured
output), then a Strands Agents tool-calling agent that writes read-only SQL against SQLite,
self-corrects, asks for clarification and explains the results. FastAPI, Streamlit and Docker come later.
Status: the data layer is done. The LLM, API and UI are not started.

## Roadmap
Follow `docs/ROADMAP.md` (ordered steps, each with a definition of done) and
`docs/golden_set_guide.md` (how to profile the data and build the evaluation set).
Planned change: the database moves from SQLite to PostgreSQL in roadmap Step 1a. Until that
step is merged, the Stack, Layout, Commands and Rules sections below describe the working
state and stay accurate. When Step 1a lands, update them in the same series of commits.
Do not start a step before the previous one meets its definition of done.

## Stack
- Python 3.12 via uv (`requires-python >= 3.10`), src layout, package `assistant`
- SQLite (stdlib `sqlite3`)
- pytest (pinned in `pyproject.toml` `[dependency-groups].dev`, locked in `uv.lock`)

## Layout
- `scripts/build_db.py`: deterministic synthetic data generator. Standard library only.
- `data/suppliers.db`: generated DB (seed 42). It is committed, so rebuild it after any generator change.
- `src/assistant/db.py`: `get_readonly_connection()` (mode=ro URI + `PRAGMA query_only`)
- `tests/`: pytest. Fixtures build a fresh DB in tmp_path.
- `docs/data_model.md`: tables, views and the quirks the agent must know

## Commands
```bash
uv sync                                   # set up .venv
uv run python scripts/build_db.py         # rebuild data/suppliers.db (deletes it first)
uv run pytest -q                          # run tests
uv run pre-commit install                 # once per clone: checks on commit, tests on push
uv run pre-commit run --all-files         # run every check the way CI does
```

## Rules
- **Data stays synthetic.** Never add real company, supplier, product or employer names
  anywhere (data, prompts, examples, docs).
- **SQL access is read-only.** Always go through `assistant.db.get_readonly_connection`.
  Never open the DB writable outside `scripts/build_db.py`.
- `build_db.py` unlinks its output path. Only point `--out` at `data/` or a temp dir.
- The generator must stay deterministic. Never iterate sets or rely on hash order, and keep
  RNG draw order stable. The tests compare `iterdump()` hashes across `PYTHONHASHSEED` values.
- **The golden set (evaluation questions) must never be mixed with the few-shot or example
  queries** given to the model. Keep them in separate files, with no overlap.
- **No secrets in the repo.** Commit only `.env.example` and never `.env`. Read keys from env vars.
- "Today" in the data is `meta.as_of_date` (2026-10-03). Only `status='completed'` carts are purchases.
- Work on `dev` with small, focused commits. Merge `dev` into `main` through a pull request
  (merge commit, not squash) once `uv run pytest -q` is green. Never push directly to `main`.
- Never bypass the hooks with `--no-verify`. If a hook reformats files, run `git add -u` and
  commit again, so no separate "fix formatting" commit is needed. CI runs the same checks.
- Do not reformat or lint-fix `scripts/build_db.py` (exempt in `pyproject.toml`).
