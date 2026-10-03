"""
auth.py — Staff authentication for the Pagsanjan livestock system.

- Stores accounts in a `staff_users` MySQL table (auto-created).
- Hashes passwords with stdlib hashlib.scrypt (no extra dependency).
- Issues signed, timed session cookies via itsdangerous (ships with Starlette).
- Provides a FastAPI dependency `require_staff` to protect endpoints.

Create the first admin with:  python auth.py create-admin <username> <password>
"""

import os
import hmac
import hashlib
import secrets
from datetime import datetime

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, Depends

from database import get_db_connection

# Secret for signing session cookies. MUST be set in production via env var;
# a random one is generated per-process otherwise (sessions reset on restart).
SECRET_KEY = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)
COOKIE_NAME = "pgsn_session"
SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="staff-session")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS staff_users (
    user_id      INT AUTO_INCREMENT PRIMARY KEY,
    username     VARCHAR(80) UNIQUE NOT NULL,
    full_name    VARCHAR(150),
    pw_hash      VARCHAR(255) NOT NULL,
    pw_salt      VARCHAR(64) NOT NULL,
    role         VARCHAR(30) DEFAULT 'staff',
    barangay     VARCHAR(64) NULL,
    is_active    TINYINT(1) DEFAULT 1,
    must_change_password TINYINT(1) DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login   DATETIME NULL
)
"""


def ensure_table():
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(_CREATE_TABLE)
        cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='staff_users'")
        columns = {r[0] if not isinstance(r, dict) else r["COLUMN_NAME"] for r in cur.fetchall()}
        if "role" not in columns:
            cur.execute("ALTER TABLE staff_users ADD COLUMN role VARCHAR(30) DEFAULT 'staff'")
        if "barangay" not in columns:
            cur.execute("ALTER TABLE staff_users ADD COLUMN barangay VARCHAR(64) NULL")
        if "must_change_password" not in columns:
            cur.execute("ALTER TABLE staff_users ADD COLUMN must_change_password TINYINT(1) DEFAULT 0")
        for name, ddl in (("profile_name", "VARCHAR(150) NULL"), ("profile_position", "VARCHAR(150) NULL"),
                          ("signature_sha", "CHAR(64) NULL"), ("seal_sha", "CHAR(64) NULL"),
                          ("profile_updated_at", "DATETIME NULL")):
            if name not in columns:
                cur.execute(f"ALTER TABLE staff_users ADD COLUMN {name} {ddl}")
        conn.commit()
        cur.close()
        return True
    finally:
        conn.close()


# ----------------------------- password hashing -----------------------------

def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Return (hex_hash, hex_salt) using scrypt. Generates a salt if not given."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384, r=8, p=1, dklen=32,
    )
    return dk.hex(), salt


def _verify_password(password: str, pw_hash: str, pw_salt: str) -> bool:
    candidate, _ = _hash_password(password, pw_salt)
    # constant-time compare
    return hmac.compare_digest(candidate, pw_hash)


# ----------------------------- user management ------------------------------

def create_user(username: str, password: str, full_name: str = "", role: str = "staff",
                barangay: str | None = None, must_change: bool = False) -> bool:
    if role not in ("staff", "admin", "barangay"):
        raise ValueError("Unknown account role")
    if role == "barangay":
        from barangays import canonical_barangay
        barangay = canonical_barangay(barangay or "")
    else:
        barangay = None
    ensure_table()
    pw_hash, pw_salt = _hash_password(password)
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO staff_users (username, full_name, pw_hash, pw_salt, role, barangay, "
            "must_change_password) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (username, full_name, pw_hash, pw_salt, role, barangay, int(must_change)),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"create_user failed: {e}")
        return False
    finally:
        conn.close()


def authenticate(username: str, password: str):
    """Return a user dict if credentials are valid and active, else None."""
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM staff_users WHERE username = %s AND is_active = 1",
            (username,),
        )
        user = cur.fetchone()
        if not user:
            return None
        if not _verify_password(password, user["pw_hash"], user["pw_salt"]):
            return None
        cur.execute("UPDATE staff_users SET last_login = %s WHERE user_id = %s",
                    (datetime.now(), user["user_id"]))
        conn.commit()
        cur.close()
        return {"user_id": user["user_id"], "username": user["username"],
                "full_name": user["full_name"], "role": user["role"], "barangay": user.get("barangay"),
                "must_change": bool(user.get("must_change_password"))}
    finally:
        conn.close()


# ----------------------------- sessions -------------------------------------

def make_session_token(user: dict) -> str:
    return _serializer.dumps({"uid": user["user_id"], "u": user["username"], "r": user["role"],
                              "b": user.get("barangay"), "m": bool(user.get("must_change"))})


def read_session_token(token: str):
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def current_user(request: Request):
    """Return the session dict if logged in, else None. Never raises."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_session_token(token)


def require_any(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    if user.get("r") not in ("staff", "admin", "barangay"):
        raise HTTPException(status_code=403, detail="Account role is not permitted")
    if user.get("r") == "barangay" and not user.get("b"):
        raise HTTPException(status_code=403, detail="Account needs a barangay assignment")
    if user.get("m"):
        raise HTTPException(status_code=403, detail="Change your temporary password before continuing.")
    return user


def require_staff(request: Request):
    """Municipal staff and existing admins only."""
    user = require_any(request)
    if user.get("r") not in ("staff", "admin"):
        raise HTTPException(status_code=403, detail="Municipal staff access required")
    return user


def require_admin(request: Request):
    user = require_any(request)
    if user.get("r") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def require_barangay(request: Request):
    user = require_any(request)
    if user.get("r") != "barangay":
        raise HTTPException(status_code=403, detail="Barangay account required")
    return user


# ----------------------------- password management -------------------------

# No 0/O/1/l/I: temporary passwords are read off paper and typed by hand.
_PW_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def password_problem(username: str, password: str):
    """Return a reason the password is unacceptable, or None."""
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    if password.casefold() == (username or "").casefold():
        return "The password cannot be the username."
    if password.isdigit() or password.isalpha():
        return "Mix letters with numbers or symbols."
    return None


def _set_password(cur, user_id: int, password: str, must_change: bool):
    pw_hash, pw_salt = _hash_password(password)
    cur.execute("UPDATE staff_users SET pw_hash=%s, pw_salt=%s, must_change_password=%s "
                "WHERE user_id=%s", (pw_hash, pw_salt, int(must_change), user_id))


def change_password(user_id: int, current: str, new: str):
    """Change one's own password. Returns the refreshed user dict.

    Raises ValueError with a user-facing message on any rejection.
    """
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB unavailable")
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM staff_users WHERE user_id=%s AND is_active=1", (user_id,))
        user = cur.fetchone()
        if not user or not _verify_password(current, user["pw_hash"], user["pw_salt"]):
            raise ValueError("The current password is incorrect.")
        if current == new:
            raise ValueError("Choose a password different from the current one.")
        problem = password_problem(user["username"], new)
        if problem:
            raise ValueError(problem)
        _set_password(cur, user_id, new, must_change=False)
        conn.commit()
        cur.close()
        return {"user_id": user["user_id"], "username": user["username"],
                "full_name": user["full_name"], "role": user["role"],
                "barangay": user.get("barangay"), "must_change": False}
    finally:
        conn.close()


def reset_password(username: str) -> str:
    """Admin reset: issue a temporary password the user must change at sign-in."""
    temp = generate_password()
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB unavailable")
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT user_id FROM staff_users WHERE username=%s", (username,))
        row = cur.fetchone()
        if not row:
            raise KeyError(username)
        _set_password(cur, row["user_id"], temp, must_change=True)
        conn.commit()
        cur.close()
        return temp
    finally:
        conn.close()


def set_active(username: str, active: bool) -> bool:
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB unavailable")
    try:
        cur = conn.cursor()
        # MySQL's rowcount is 0 when the value is unchanged, so check existence separately.
        cur.execute("SELECT 1 FROM staff_users WHERE username=%s", (username,))
        if cur.fetchone() is None:
            cur.close()
            return False
        cur.execute("UPDATE staff_users SET is_active=%s WHERE username=%s", (int(active), username))
        conn.commit()
        cur.close()
        return True
    finally:
        conn.close()


def list_accounts():
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB unavailable")
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT username, full_name, role, barangay, is_active, must_change_password, "
                    "created_at, last_login FROM staff_users ORDER BY role, barangay, username")
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


# ----------------------------- CLI -----------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4 and sys.argv[1] == "create-admin":
        uname, pword = sys.argv[2], sys.argv[3]
        full = sys.argv[4] if len(sys.argv) > 4 else ""
        ok = create_user(uname, pword, full_name=full, role="admin")
        print("Admin created." if ok else "Failed (username may already exist).")
    elif len(sys.argv) >= 4 and sys.argv[1] == "create-staff":
        uname, pword = sys.argv[2], sys.argv[3]
        full = sys.argv[4] if len(sys.argv) > 4 else ""
        ok = create_user(uname, pword, full_name=full, role="staff")
        print("Staff user created." if ok else "Failed (username may already exist).")
    elif len(sys.argv) >= 5 and sys.argv[1] == "create-barangay":
        ok = create_user(sys.argv[2], sys.argv[3], role="barangay", barangay=sys.argv[4],
                         full_name=sys.argv[5] if len(sys.argv) > 5 else "")
        print("Barangay account created." if ok else "Failed to create account.")
    else:
        print("Usage:")
        print('  python auth.py create-barangay <username> <password> "<barangay>" [full name]')
        print("  python auth.py create-admin <username> <password> [full name]")
        print("  python auth.py create-staff <username> <password> [full name]")
