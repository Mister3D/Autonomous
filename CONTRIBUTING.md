# Contributing

By contributing to Autonomous you agree that your contributions are licensed under the **GNU Affero General Public License v3.0** (`AGPL-3.0-only`), the same license as the project.

## Setup

1. Prefer a venv + `pip install -e ".[dev]"`.
2. Frontend: `cd frontend && npm install && npm run build` (or `serve --dev`).
3. Tests: `pytest tests -q`.
4. Do not commit `data/`, tokens, vault keys, or provider API keys ([SECURITY.md](SECURITY.md)).
5. Behaviour changes: update the matching fiche under `docs/features/` (see [docs/README.md](docs/README.md)).
6. Ask before adding system packages (`apt` / global `pip` / npm globals).

## Pull requests

- Flow: **feature branch → `dev` (PR) → `main` (PR from `dev` only)**. Do not open feature PRs against `main`.
- Keep changes focused; update docs when behaviour changes.
- Prefer French for chat with the maintainer; keep user-facing product strings / README English (with `README-FR.md` in sync when you touch it).
- Do not include personal scenarios, real credentials, absolute home paths, or provider keys.

### Enforce on GitHub (so even the owner cannot bypass)

1. Repo → **Settings → Rules → Rulesets → New branch ruleset** (repeat for `main` and `dev`).
2. Target: include `main` (then another ruleset for `dev`).
3. Enable: **Restrict deletions**, **Block force pushes**, **Require a pull request before merging** (you can set required approvals to 0 if you work alone).
4. **Require status checks to pass**:
   - On `main`: `test` **and** `main-from-dev` (the latter fails unless the PR head is exactly `dev`).
   - On `dev`: `test`.
5. **Bypass list**: leave empty. Turn off any option that lets administrators bypass — otherwise you can still merge by mistake as owner.
6. Do not allow direct pushes to `main` / `dev` outside a PR.

## Security

See [SECURITY.md](SECURITY.md). Prefer a private GitHub Security Advisory over a public issue for vulnerabilities.
