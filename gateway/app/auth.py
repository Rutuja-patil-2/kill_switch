import os
import time
import uuid

import jwt
from fastapi import HTTPException

SECRET = os.environ["JWT_SECRET"]
ALGO = "HS256"


def issue_token(agent_id: str, ttl_seconds: int = 24 * 3600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": agent_id, "iat": now, "exp": now + ttl_seconds, "jti": str(uuid.uuid4())},
        SECRET,
        algorithm=ALGO,
    )


def verify_token(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        return jwt.decode(authorization[7:], SECRET, algorithms=[ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}")
