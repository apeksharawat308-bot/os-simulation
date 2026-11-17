# What this update changes (drop the files into your project, same folders, overwrite when asked)

## Problems fixed
| Problem | Fix |
|---|---|
| A job bigger than the biggest VM (the seed's `render-big`: 6 cores vs `vm-large` 4) was granted host resources but never placed -> stuck RUNNING forever, starving the queue | seed job shrunk to 4 cores/8 GB; `POST /api/jobs` rejects jobs bigger than the biggest VM (422); the automation cycle now FAILS a RUNNING job that can never fit any VM (frees its resources) |
| `pip install` could fail on Python 3.14 (old exact pins) | `requirements.txt` uses version ranges; unused `alembic` removed |
| `install.sql` needs the `mysql` client; Workbench safe-update mode rejected the seed's `UPDATE vms ...` | seed `UPDATE` now has `WHERE id > 0`; new `backend/scripts/install_db.py` installs from Python (no client needed) |
| `/api/bridge/apply-recommended` could overlap the background loop (and the Docker executor could remove a just-started container) | it now runs through the automation lock (`automation.run_once(..., reap=False)`) |
| `/complete` and `/fail` hard-coded `PRIORITY_AGING`/60 s | they use `AUTOMATION_POLICY` / `AGING_SECONDS` |
| MySQL deadlock (1213) / lock timeout (1205) surfaced as an error | procedure calls are retried up to 3 times |

## New features
* **Login** (`app/api/auth.py`, `app/services/auth.py`, no extra packages): `POST /api/auth/register`, `/login`, `GET /me`.
  `AUTH_REQUIRED=false` (default) keeps everything open; `true` requires a token for job endpoints (users act on their own
  jobs, ADMIN on all) and an ADMIN token for VMs / dispatch / automation. Seed users have dummy passwords:
  `cd backend && python -m scripts.set_password admin 'MyStrongPass1' --admin`.
  The built-in UI has no login screen, so leave `AUTH_REQUIRED=false` if you use it; use `/docs` -> Authorize otherwise.
* **VM management** (`app/api/vms.py`): `GET/POST /api/vms`, `PUT /api/vms/{id}` (resize), `POST /api/vms/{id}/start|stop|destroy`.
  Capacity and lifecycle rules still come from the MySQL triggers; their message is returned as the HTTP 409 text.
* **Kill a running job**: `POST /api/jobs/{id}/kill` (UI: "Kill" button). New `sp_cancel_job`; triggers now allow
  RUNNING -> CANCELLED, free the allocations and mark the container REMOVED; a real Docker container is removed.
* **Live Gantt / metrics** (`app/services/execution_log.py`): every completed job writes a row to `job_executions`
  (start = sim units since the first job, end = start + est_time, algorithm = active policy), so `v_gantt`, `v_job_metrics`
  and deadline misses now cover live jobs, not only seed data.
* `database/08_app_user.sql` (optional): least-privilege MySQL account instead of `root`.

## Applying it
* **Fresh install:** `docker compose down -v && docker compose up --build`, or `python backend/scripts/install_db.py --user root --password PW`.
* **Existing database, keep the data:** `python backend/scripts/install_db.py --user root --password PW --patch`
  (re-creates views, procedures and triggers only; the seed change only matters for a fresh install).
* Re-install Python packages: `pip install -r backend/requirements.txt`.
* New settings (all optional): `AUTH_REQUIRED`, `SECRET_KEY`, `TOKEN_MINUTES`.

## Verified here vs not verified
Verified: all Python compiles; 33 unit tests pass (OS algorithms, password/token logic, SQL splitter on your real files).
NOT run (no MySQL / FastAPI / Docker in the build sandbox): the SQL changes, the new endpoints, the automation changes.
Run `cd backend && pytest -q`, then the two MySQL tests (see README) on your machine before relying on them.

## Still not done
Login screen in the UI, per-user job listing/ownership shown in the API output, pagination on most lists,
a real hypervisor (VMs stay logical partitions), more than 3 Banker's resource types, non-root Docker image
(blocked by the Docker-socket mount), HTTPS / rate limiting, backups, and tests for the triggers/procedures beyond the two MySQL tests.
