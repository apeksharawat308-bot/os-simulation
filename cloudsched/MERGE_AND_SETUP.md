# What the merge changed

* **One server.** `demo/server.py` (stdlib OS demo) and `static/dbms_dashboard.html` are gone. The OS demo logic lives in
  `app/services/os_lab.py` and is exposed at `/api/os/*`; one UI (`static/index.html`) covers OS + DBMS.
* **OS ↔ DBMS bridge** (`app/api/bridge.py`, `app/services/bridge.py`)
  * `GET /api/bridge/recommend-policy`, `POST /api/bridge/apply-recommended` — OS algorithms on the live waiting queue.
  * `POST /api/bridge/compare` — adaptive-scheduler result stored in `comparison_runs` / `algorithm_results`
    (these tables were previously only filled by seed data).
  * `GET /api/bridge/banker/{job_id}` — Python Banker's vs `sp_bankers_check`; they must agree.
* **Execution + automation** (`executor.py`, `automation.py`, `/api/automation/*`). This also fixes a gap in the old flow:
  `sp_dispatch_waiting` started jobs but never placed them in a VM, and nothing noticed when a job finished.
* **Packaging:** `docker-compose.yml` (+ `docker-compose.docker.yml` for real containers), `backend/Dockerfile`, CI workflow, Makefile.
* `database/schema.sql` is still an unused duplicate of `01_schema.sql`; delete it if you do not need it.

# What the second update added (already merged into this folder)

New files: `app/api/auth.py`, `app/api/vms.py`, `app/services/auth.py`, `app/services/execution_log.py`, `backend/scripts/*`,
`database/08_app_user.sql`, `tests/test_auth_and_installer.py`, `docs/CHANGES.md`, `.vscode/*`.
Overwritten with the newer versions: `main.py`, `config.py`, `api/{automation,bridge,jobs}.py`, `services/{automation,mysql_procedures}.py`,
`static/index.html`, `database/{03_procedures,04_triggers,05_seed_data}.sql`, both `.env.example` files, `requirements.txt`, `docker-compose.yml`.
