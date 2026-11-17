# Setup guide

The authoritative instructions are in the project-root `README.md` ("Quick start (VS Code, without Docker)" or Docker).

Short version (VS Code, Windows/macOS/Linux):
1. `cd backend && python -m venv .venv`, activate it, `pip install -r requirements.txt`
2. copy `backend/.env.example` to `backend/.env` and put your MySQL password in `DATABASE_URL`
3. `python scripts/install_db.py --user root --password YOUR_PASSWORD` (fresh install, resets the DB) or add `--patch` to keep data
4. `uvicorn app.main:app --reload` (or press F5 in VS Code) -> UI `http://127.0.0.1:8000/`, API docs `/docs`
5. `python -m pytest -q` runs the tests that need no database.
