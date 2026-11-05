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

- Keep changes focused; update docs when behaviour changes.
- Prefer French for chat with the maintainer; keep user-facing product strings / README English (with `README-FR.md` in sync when you touch it).
- Do not include personal scenarios, real credentials, absolute home paths, or provider keys.

## Security

See [SECURITY.md](SECURITY.md). Prefer a private GitHub Security Advisory over a public issue for vulnerabilities.
