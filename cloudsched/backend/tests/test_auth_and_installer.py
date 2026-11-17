"""No database needed: password/token logic and the SQL-script splitter used by scripts/install_db.py."""
import time
from pathlib import Path

import pytest

from app.services.auth import AuthError, create_token, decode_token, hash_password, verify_password
from scripts.install_db import split_statements

DB = Path(__file__).resolve().parent.parent.parent / "database"


def test_password_roundtrip_and_salting():
    h = hash_password("S3cret-pass")
    assert verify_password("S3cret-pass", h) and not verify_password("wrong", h)
    assert h != hash_password("S3cret-pass")                      # random salt
    assert len(h) < 255                                           # fits users.password_hash VARCHAR(255)


def test_seed_dummy_hash_never_verifies():
    assert not verify_password("anything", "seed-not-a-real-hash")
    assert not verify_password("anything", None)


def test_token_roundtrip_and_rejections():
    t = create_token(7, "alice", "USER", secret="k")
    c = decode_token(t, secret="k")
    assert c["sub"] == "7" and c["name"] == "alice" and c["role"] == "USER"
    with pytest.raises(AuthError):
        decode_token(t, secret="other")                           # wrong key
    head, payload, sig = t.split(".")
    with pytest.raises(AuthError):
        decode_token(f"{head}.{payload}x.{sig}", secret="k")      # tampered payload
    with pytest.raises(AuthError):
        decode_token("not-a-token", secret="k")
    old = create_token(7, "alice", "USER", minutes=1, secret="k", now=time.time() - 3600)
    with pytest.raises(AuthError):
        decode_token(old, secret="k")                             # expired


def test_splitter_delimiters_comments_and_quotes():
    sql = """
    -- it's a comment with an apostrophe;
    USE db;
    INSERT INTO t VALUES ('a;b', 'it''s');   -- trailing; comment
    DELIMITER $$
    CREATE PROCEDURE p()
    BEGIN
      SELECT 1;  /* block; comment */
      SELECT 2;
    END$$
    DELIMITER ;
    SELECT 3;
    """
    st = split_statements(sql)
    assert st[0] == "USE db"
    assert st[1] == "INSERT INTO t VALUES ('a;b', 'it''s')"
    assert st[2].startswith("CREATE PROCEDURE p()") and st[2].endswith("END") and "SELECT 2;" in st[2]
    assert st[3] == "SELECT 3" and len(st) == 4


def test_real_install_files_parse_into_the_expected_objects():
    def count(name, prefix):
        return sum(s.upper().startswith(prefix) for s in split_statements((DB / name).read_text(encoding="utf-8")))
    assert count("01_schema.sql", "CREATE TABLE") == 11
    assert count("03_procedures.sql", "CREATE PROCEDURE") == 9      # incl. sp_cancel_job
    assert count("04_triggers.sql", "CREATE TRIGGER") == 8
    assert count("02_views.sql", "CREATE OR REPLACE VIEW") == 12
