"""Install the CloudSched MySQL schema WITHOUT the mysql command-line client (works from any terminal / Workbench-less setup).

    cd backend
    python scripts/install_db.py --user root --password YOUR_PASSWORD            # 01..05 (RESETS the cloudsched DB)
    python scripts/install_db.py --user root --password YOUR_PASSWORD --no-seed  # 01..04 only
    python scripts/install_db.py --user root --password YOUR_PASSWORD --patch    # re-create views/procedures/triggers only
                                                                                # (02..04: keeps your data, use after updating)
    python scripts/install_db.py --dry-run                                       # just parse the files and count statements

It understands the DELIMITER lines used by 03_procedures.sql / 04_triggers.sql, which PyMySQL alone cannot run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent.parent.parent / "database"
FULL = ["01_schema.sql", "02_views.sql", "03_procedures.sql", "04_triggers.sql", "05_seed_data.sql"]


def split_statements(sql: str) -> list[str]:
    """Split a mysql-client script into single statements. Handles DELIMITER, '-- ' / '#' / /* */ comments and quotes."""
    stmts: list[str] = []
    buf: list[str] = []
    has_content = False
    delim, i, n, quote = ";", 0, len(sql), None

    def flush():
        nonlocal buf, has_content
        text = "".join(buf).strip()
        if text:
            stmts.append(text)
        buf, has_content = [], False

    while i < n:
        ch = sql[i]
        if quote:                                              # inside '...', "..." or `...`
            buf.append(ch)
            if ch == "\\" and quote != "`" and i + 1 < n:
                buf.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:          # doubled quote = literal quote
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if not has_content and sql[i:i + 9].upper() == "DELIMITER" and i + 9 < n and sql[i + 9] in " \t":
            eol = sql.find("\n", i)
            eol = n if eol == -1 else eol
            delim = sql[i + 9:eol].strip()
            i = eol + 1
            continue
        if ch == "#" or (sql.startswith("--", i) and (i + 2 >= n or sql[i + 2] in " \t\r\n")):
            eol = sql.find("\n", i)
            i = n if eol == -1 else eol                        # keep the newline itself
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if sql.startswith(delim, i):
            flush()
            i += len(delim)
            continue
        if ch in "'\"`":
            quote = ch
        if not ch.isspace():
            has_content = True
        buf.append(ch)
        i += 1
    flush()
    return stmts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="")
    ap.add_argument("--no-seed", action="store_true", help="skip 05_seed_data.sql")
    ap.add_argument("--patch", action="store_true", help="only 02_views, 03_procedures, 04_triggers (no data loss)")
    ap.add_argument("--dry-run", action="store_true", help="parse the files, do not connect")
    args = ap.parse_args()

    files = FULL[1:4] if args.patch else (FULL[:4] if args.no_seed else FULL)
    scripts = {f: split_statements((DB_DIR / f).read_text(encoding="utf-8")) for f in files}
    if args.dry_run:
        for f, st in scripts.items():
            print(f"{f}: {len(st)} statements")
        return 0

    try:
        import pymysql
    except ImportError:
        print("PyMySQL is missing: pip install -r requirements.txt", file=sys.stderr)
        return 2
    conn = pymysql.connect(host=args.host, port=args.port, user=args.user, password=args.password, autocommit=True)
    try:
        with conn.cursor() as cur:
            if args.patch:
                cur.execute("USE cloudsched")
            for f, st in scripts.items():
                print(f"{f} ...", end=" ", flush=True)
                for k, stmt in enumerate(st, 1):
                    try:
                        cur.execute(stmt)
                    except Exception as exc:
                        print(f"\nFAILED in {f}, statement {k}:\n{stmt[:400]}\n-> {exc}", file=sys.stderr)
                        return 1
                print(f"{len(st)} statements OK")
    finally:
        conn.close()
    print("CloudSched database installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
