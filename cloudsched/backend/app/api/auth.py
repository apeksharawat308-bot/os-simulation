"""Register / login / who-am-I, plus the FastAPI dependencies the other routers use.

AUTH_REQUIRED=false (default): everything works without a token (the built-in UI has no login screen); if a token is
sent anyway, jobs are attributed to that user.
AUTH_REQUIRED=true: job endpoints need a valid token, VM management / dispatch / automation need an ADMIN token.
Use  POST /api/auth/login  and paste the token into the "Authorize" button on /docs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.services.auth import AuthError, create_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str


def optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[Principal]:
    if creds is None:
        return None
    try:
        c = decode_token(creds.credentials)
        return Principal(int(c["sub"]), str(c["name"]), str(c["role"]))
    except (AuthError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}", headers={"WWW-Authenticate": "Bearer"})


def require_user(user: Optional[Principal] = Depends(optional_user)) -> Optional[Principal]:
    """Logged-in user; None is accepted only while AUTH_REQUIRED=false."""
    if user is None and settings.auth_required:
        raise HTTPException(status_code=401, detail="login required", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_admin(user: Optional[Principal] = Depends(optional_user)) -> Optional[Principal]:
    if not settings.auth_required:
        return user
    if user is None:
        raise HTTPException(status_code=401, detail="login required", headers={"WWW-Authenticate": "Bearer"})
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="admin only")
    return user


class Login(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class Register(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(max_length=100, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    password: str = Field(min_length=8, max_length=128)


@router.post("/register", status_code=201)
def register(data: Register, db: Session = Depends(get_db)):
    """Creates a normal USER account (an admin is made with scripts/set_password.py --admin)."""
    try:
        db.execute(text("INSERT INTO users (username, email, password_hash, role) VALUES (:u, :e, :p, 'USER')"),
                   {"u": data.username, "e": data.email, "p": hash_password(data.password)})
        uid = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="username or email already taken (or e-mail format rejected)") from exc
    return {"id": uid, "username": data.username, "role": "USER"}


@router.post("/login")
def login(data: Login, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT id, username, role, password_hash FROM users WHERE username = :u"),
                     {"u": data.username}).first()
    db.rollback()                                           # nothing to keep; do not hold a transaction open
    if row is None or not verify_password(data.password, row.password_hash):
        verify_password(data.password, None)                # equalise timing for unknown users
        raise HTTPException(status_code=401, detail="invalid username or password")
    return {"access_token": create_token(row.id, row.username, row.role), "token_type": "bearer",
            "expires_in": settings.token_minutes * 60, "role": row.role}


@router.get("/me")
def me(user: Optional[Principal] = Depends(optional_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="not logged in", headers={"WWW-Authenticate": "Bearer"})
    return {"id": user.user_id, "username": user.username, "role": user.role}
