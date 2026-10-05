"""Username/password accounts with server-side sessions stored in MongoDB.

The client receives an opaque random token; only its SHA-256 hash is stored, so a
database leak doesn't expose usable sessions. Logging out deletes the session.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

SESSION_LIFETIME = timedelta(days=30)
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,24}$")

# Used to keep login timing the same whether or not the username exists
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_indexes(db):
    db.users.create_index("username", unique=True)
    db.sessions.create_index("tokenHash", unique=True)
    # MongoDB deletes sessions automatically once expiresAt passes
    db.sessions.create_index("expiresAt", expireAfterSeconds=0)


def public_user(user):
    return {"id": str(user["_id"]), "username": user["username"]}


def validate_credentials(data):
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    if not USERNAME_RE.match(username):
        return None, None, "Username must be 3–24 characters: letters, numbers or underscores."
    if not 8 <= len(password) <= 128:
        return None, None, "Password must be at least 8 characters."
    return username, password, None


def register(db, username, password):
    """Create a user. Returns the user, or None if the username is taken."""
    user = {
        "username": username,
        "passwordHash": generate_password_hash(password),
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        user["_id"] = db.users.insert_one(user).inserted_id
    except DuplicateKeyError:
        return None
    return user


def authenticate(db, username, password):
    user = db.users.find_one({"username": username})
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return None
    if not check_password_hash(user["passwordHash"], password):
        return None
    return user


def create_session(db, user):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.sessions.insert_one({
        "tokenHash": _hash_token(token),
        "userId": user["_id"],
        "createdAt": now,
        "expiresAt": now + SESSION_LIFETIME,
    })
    return token


def _bearer_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def delete_session(db):
    token = _bearer_token()
    if token:
        db.sessions.delete_one({"tokenHash": _hash_token(token)})


def require_auth(db):
    """Decorator factory: rejects the request unless it carries a valid session token."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            token = _bearer_token()
            session = token and db.sessions.find_one({
                "tokenHash": _hash_token(token),
                "expiresAt": {"$gt": datetime.now(timezone.utc)},
            })
            user = session and db.users.find_one({"_id": session["userId"]})
            if not user:
                return jsonify({"error": "Please log in again."}), 401
            g.user = user
            return view(*args, **kwargs)
        return wrapper
    return decorator
