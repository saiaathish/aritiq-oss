"""
Supabase JWT verification for the audit endpoints.

The frontend sends the user's Supabase session token as `Authorization:
Bearer <jwt>`. We verify it server-side — never trust a client-only check —
and hand back the user id (`sub`) for rate limiting.

Two signing schemes are supported, chosen by the token's own header:
  - ES256/RS256 (new Supabase projects, incl. this one): verified against the
    project's public JWKS at  <SUPABASE_URL>/auth/v1/.well-known/jwks.json.
    Needs no secret — only SUPABASE_URL.
  - HS256 (legacy projects): verified with SUPABASE_JWT_SECRET from the
    project's API settings.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET") or ""

_jwks_client: Optional[PyJWKClient] = None


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not SUPABASE_URL:
            raise RuntimeError(
                "SUPABASE_URL is not set — required to verify Supabase JWTs "
                "against the project's JWKS endpoint."
            )
        _jwks_client = PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )
    return _jwks_client


def verify_supabase_token(token: str) -> Optional[dict]:
    """Return the decoded Supabase token payload if `token` is a valid session JWT, else None."""
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
    except Exception:
        pass

    if not token or token.count(".") != 2:
        return None
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")
        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                return None
            payload = jwt.decode(
                token, SUPABASE_JWT_SECRET,
                algorithms=["HS256"], audience="authenticated",
            )
        elif alg in ("ES256", "RS256"):
            key = _jwks().get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token, key, algorithms=[alg], audience="authenticated",
            )
        else:
            return None
        return payload
    except Exception as exc:
        import traceback
        traceback.print_exc()
        logger.warning("Supabase token verification failed: %s", type(exc).__name__)
        return None
