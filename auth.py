import os

import jwt
from jwt import PyJWKClient
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing in backend/.env")

ISSUER = f"{SUPABASE_URL}/auth/v1"
jwks_client = PyJWKClient(f"{ISSUER}/.well-known/jwks.json")

bearer_scheme = HTTPBearer()


class TokenError(Exception):
    """Raised when a token is missing, invalid or expired."""


def verify_token(token: str) -> dict:
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=ISSUER,
        )
    except jwt.PyJWTError as e:
        print("JWT verification failed:", repr(e))
        raise TokenError("Invalid or expired token") from e

    if "sub" not in payload:
        raise TokenError("Token has no subject")

    return {"id": payload["sub"], "email": payload.get("email")}


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    try:
        return verify_token(credentials.credentials)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")