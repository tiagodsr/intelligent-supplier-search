## What and why
<!-- What changes, and which roadmap step it belongs to. -->

## How to verify
<!-- Commands or steps a reviewer can run, for example `uv run pytest -q`. -->

## Checklist
- [ ] `uv run pytest -q` passes locally
- [ ] Pre-commit hooks passed (not bypassed with `--no-verify`)
- [ ] The step's Definition of Done in `docs/ROADMAP.md` is met
- [ ] Docs updated if behaviour changed (`README.md`, `CLAUDE.md`, `docs/`)
- [ ] No secrets, real company names or real data added (data stays synthetic)
- [ ] The golden set and the few-shot examples were not mixed (if evaluation files were touched)
