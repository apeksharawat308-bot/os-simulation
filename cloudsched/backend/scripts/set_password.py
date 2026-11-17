"""Set (or reset) a user's password; the seed users ship with a dummy hash and cannot log in until you run this.

    cd backend
    python -m scripts.set_password admin 'MyStrongPass1' --admin     # also makes the user an ADMIN
    python -m scripts.set_password alice 'AnotherPass2'
"""
import argparse
import sys

from sqlalchemy import text

from app.database.session import SessionLocal
from app.services.auth import hash_password


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("password")
    ap.add_argument("--admin", action="store_true", help="also set role = ADMIN")
    args = ap.parse_args()
    if len(args.password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        res = db.execute(text("UPDATE users SET password_hash = :h" + (", role = 'ADMIN'" if args.admin else "") +
                              " WHERE username = :u"), {"h": hash_password(args.password), "u": args.username})
        db.commit()
    if res.rowcount == 0:
        print(f"no user named {args.username!r}", file=sys.stderr)
        return 1
    print(f"password updated for {args.username}" + (" (ADMIN)" if args.admin else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
