# Rino — Steps 1–9 (complete)

Local monorepo for the Rino AI debugging agent (copy via Context / `rino.zip`).

| Step | Capability |
|------|------------|
| 1 | Auth + Admin/Developer roles |
| 2 | GitHub App install + Repository Setup |
| 3 | `SandboxRunner` (clone → setup → pytest/JUnit) |
| 4 | pylint + bandit, triage (`rules.yaml`), Repository Dashboard |
| 5 | LLM root-cause, Confirm GitHub Issue (Critical) |
| 6 | Fix generation + verify (local `rino/fix-<n>`) |
| 7 | Approve & Open Draft PR + Testing Dashboard |
| 8 | `GitHubActionsRunner` (workflow_dispatch → JUnit artifact) |
| 9 | Performance Dashboard (SVG charts), Admin Settings, audit log, 3 samples |

No chat / conversational AI. Issues and PRs are only created after Developer approval.

## Quick start

```bash
cd docs/rino   # or wherever you unpacked rino.zip — must contain docker-compose.yml AND backend/
cp .env.example .env
# Fill secrets below, then:
docker compose up --build
```

**Important:** run `docker compose` from the folder that contains `docker-compose.yml` and a populated `backend/app/api/` (including `admin_repos.py`). Compose no longer bind-mounts source over the image, so a wrong working directory will not wipe `/app` — but you still need a full unzip for `./samples`.

- App: http://localhost:3000  
- Admin setup: http://localhost:3000/admin  
- Developer: http://localhost:3000/app  

## Create a GitHub OAuth App (login)

1. https://github.com/settings/developers → **OAuth Apps** → New  
2. Homepage: `http://localhost:3000`  
3. Callback: `http://localhost:8000/auth/github/callback`  
4. Copy Client ID / Secret → `.env` as `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`

## Create a GitHub App (repos / Issues / Actions / webhooks)

1. https://github.com/settings/apps → **New GitHub App**  
2. Permissions (at minimum):
   - Repository contents: Read & write  
   - Issues: Read & write  
   - Pull requests: Read & write  
   - Actions: Read & write  
   - Metadata: Read  
3. Webhook URL (local): `https://<ngrok-host>/webhooks/github`  
   Secret → `GITHUB_APP_WEBHOOK_SECRET`  
   Events: `workflow_run`, `installation`, `ping`  
4. Generate a private key → paste PEM into `GITHUB_APP_PRIVATE_KEY` (use `\n` for newlines) or set `GITHUB_APP_PRIVATE_KEY_PATH`  
5. Set `GITHUB_APP_ID`, `GITHUB_APP_SLUG`  
6. Install the App on your org/user, then connect repos in Rino Admin → Repository Setup  

### ngrok for webhooks

```bash
ngrok http 8000
# Point the GitHub App webhook at https://<id>.ngrok-free.app/webhooks/github
```

## Environment variables

See `.env.example`. Important groups:

| Vars | Purpose |
|------|---------|
| `DATABASE_URL`, `REDIS_URL` | Postgres + Redis (compose defaults work) |
| `SESSION_SECRET`, `FRONTEND_URL`, `BACKEND_URL`, `NEXT_PUBLIC_API_URL` | Sessions + CORS |
| `GITHUB_CLIENT_*` | User OAuth login |
| `GITHUB_APP_*` | App install, Issues, PRs, Actions, webhooks |
| `BOOTSTRAP_ADMIN_GITHUB_USERNAMES` | First Admin login(s) |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | Root-cause / fix LLM (optional; stubs offline) |
| `GITHUB_ISSUE_DRY_RUN`, `GITHUB_PR_DRY_RUN`, `GITHUB_ACTIONS_DRY_RUN` | Default **true** — no live GitHub writes |
| `RINO_SAMPLES_DIR`, `RINO_SANDBOX_*` | Sandbox worker |
| `RINO_ACTIONS_*` | Actions poll timeout / artifact name hint |

## Sample repos (`samples/`)

Seeded via Admin **Seed local samples** (or `POST /api/admin/repos/seed-local-samples`):

| Local name | Seeded bugs |
|------------|-------------|
| `local/junit-demo` | Bandit `B602` shell=True, pylint E0602, env ImportError |
| `local/payments-core` | Failing test under `src/payments/` (always Critical) |
| `local/auth-service` | Hardcoded password (Bandit), import probe |

## How to demo (dry-run end-to-end)

1. **Login** as a bootstrap Admin → `/admin`  
2. **Seed local samples** (or connect a real repo)  
3. Open **Developer** `/app` → select `local/junit-demo` → **Start Analysis**  
4. Wait for triage + explain (+ auto-queued Critical fix)  
5. Open Critical finding → **Code Review** → **Confirm GitHub Issue** (dry-run URL)  
6. When `fix_status=verified`, inspect diff → optional **Testing** before/after  
7. **Approve & Open Draft PR** → `dry-run://…/pull/<n>` (nothing pushed)  
8. Check **Performance** `/app/performance` for counts / charts / costs  
9. As Admin, open **Settings** `/admin/settings` — roles, triage/core modules/fix limits, **Audit log**

## Unit tests

```bash
docker compose exec -e PYTHONPATH=/app backend python -m unittest \
  tests.test_triage_rules tests.test_fix_safety tests.test_pr_safety \
  tests.test_actions_runner tests.test_secrets_and_issues -v
```

## Architecture notes

- **Sandbox** vs **Actions**: chosen by repo `test_env`  
- Rino only pushes **`rino/*`** branches, and only after Approve  
- Triage rules live in `backend/app/triage/rules.yaml` (editable from Settings)  
- LLM never sets severity; Issues/PRs never auto-create without Confirm / Approve  
