"""Registration, login, password hashing and admin helpers."""
import re
from datetime import timedelta

import bcrypt
from sqlalchemy import func, select

import config
from db import AuditLog, User, utcnow

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3-30 characters: letters, digits, '_', '.' or '-'."
    return None


def validate_password(password: str) -> str | None:
    if len(password or "") < 8:
        return "Password must have at least 8 characters."
    if len(password.encode()) > 72:
        return "Password is too long (maximum 72 bytes)."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def register_user(session, username: str, email: str, password: str, role: str = "user"):
    """Returns (user, error_message)."""
    username = (username or "").strip()
    email = (email or "").strip().lower() or None
    error = validate_username(username) or validate_password(password)
    if error:
        return None, error
    if email and not EMAIL_RE.match(email):
        return None, "Email address is not valid."
    taken = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if taken:
        return None, "This username is already taken."
    if email and session.scalar(select(User).where(User.email == email)):
        return None, "This email is already registered."
    user = User(username=username, email=email, password_hash=hash_password(password), role=role)
    session.add(user)
    session.commit()
    return user, None


def authenticate(session, username: str, password: str):
    """Returns (user, error_message). Locks the account after repeated failures."""
    generic = "Wrong username or password."
    user = session.scalar(
        select(User).where(func.lower(User.username) == (username or "").strip().lower())
    )
    if user is None:
        # same work as a real check so timing does not reveal valid usernames
        verify_password(password or "", hash_password("dummy-password"))
        return None, generic
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        return None, f"Too many failed attempts. Try again in about {minutes} minute(s)."
    if not verify_password(password or "", user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= config.MAX_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=config.LOCKOUT_MINUTES)
            user.failed_attempts = 0
        session.commit()
        return None, generic
    if not user.is_active:
        return None, "This account has been deactivated. Contact an administrator."
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    session.commit()
    return user, None


def ensure_admin(session) -> str | None:
    """Creates the first admin from ADMIN_USERNAME / ADMIN_PASSWORD when none exists.
    Returns a warning message when it could not."""
    if session.scalar(select(func.count()).select_from(User).where(User.role == "admin")):
        return None
    username = config.get("ADMIN_USERNAME", "admin")
    password = config.get("ADMIN_PASSWORD")
    email = config.get("ADMIN_EMAIL", "")
    if not password:
        return "No admin account exists yet. Set ADMIN_USERNAME and ADMIN_PASSWORD, then restart."
    existing = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if existing:
        existing.role = "admin"
        existing.is_active = True
        session.commit()
        return None
    _, error = register_user(session, username, email, password, role="admin")
    return error


def count_active_admins(session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    )


def log_action(session, admin: User, action: str, detail: str = "") -> None:
    session.add(
        AuditLog(admin_id=admin.id, admin_username=admin.username, action=action, detail=detail[:500])
    )
    session.commit()
