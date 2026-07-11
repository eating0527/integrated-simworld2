# Repository Guidelines

## Project Structure & Module Organization

- `frontend/` is the React/Vite client: UI in `src/components/`, effects in `src/hooks/`, and helpers in `src/utils/`.
- `backend/app/` is the FastAPI and simulation service; backend tests are in `backend/tests/`.
- Frontend tests are in `frontend/tests/` or colocated as `*.test.tsx`. Operational and conversion scripts live in `tools/`.
- Put generated assets under `backend/app/static/` or `frontend/public/`, never in source folders.

## Build, Test, and Development Commands

- `.\start.ps1 -NoTunnel` starts the backend on `:8888` and Vite on `:5173`; add `-Reload` for backend auto-reload.
- `cd frontend; npm run dev` runs the client; `npm test` runs Vitest; `npm run build` type-checks and bundles it.
- `cd backend; .\.venv\Scripts\python -m unittest discover -s tests` runs backend tests.
- `python tools\test_pi_radio_stack.py` checks the Raspberry Pi radio-stack integration when that hardware is available.

## Coding Style & Naming Conventions

Use two spaces in TypeScript/TSX and four in Python. Components use PascalCase (`GPSStatus.tsx`), hooks `useThing.ts`, helpers camelCase, and Python `snake_case`. Name tests `test_<behavior>.py` or `<Component>.test.tsx`. No formatter or linter is configured; match the edited file.

## Testing Guidelines

Add the smallest relevant regression test. Frontend tests use Vitest/jsdom and backend tests use `unittest`. Run the affected suite, then `npm run build` for frontend changes. Avoid hardware-dependent tests unless changing that integration.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects, such as `feat(ui): add status summaries`. Keep commits focused and imperative. PRs need the user-visible change, tests run, linked issue (if any), and UI screenshots. Never commit secrets, logs, or large derived output.

## Git Ignore Rules

Keep secrets in `.env` or `frontend/.env.local`. Existing rules already ignore dependencies, caches, logs, temporary files, mission captures, and generated models or scenes. Add only `/.claude/worktrees/` for disposable agent worktrees. Do not broadly ignore `.claude/`, `.playwright/`, `.superpowers/`, `incoming/`, or `output/`: each contains tracked configuration, fixtures, or scripts. Check a candidate with `git status --ignored --short` and `git check-ignore -v <path>` before adding it.
