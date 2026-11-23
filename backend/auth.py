from __future__ import annotations
import os
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)

def supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))

def verify_access_token(token: str) -> dict:
    """Validate a Supabase access token against Supabase Auth (never trust client claims)."""
    url=os.getenv("SUPABASE_URL","").rstrip("/")
    anon=os.getenv("SUPABASE_ANON_KEY","")
    if not url or not anon:
        raise HTTPException(status_code=503, detail="Authentication is not configured on this server")
    try:
        response=httpx.get(url+"/auth/v1/user",headers={"apikey":anon,"Authorization":"Bearer "+token},timeout=8.0)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired login session",headers={"WWW-Authenticate":"Bearer"})
    user=response.json()
    if not user.get("id") or user.get("aud") not in (None,"authenticated"):
        raise HTTPException(status_code=401, detail="Invalid authenticated user")
    return {"id":str(user["id"]),"email":user.get("email"),"phone":user.get("phone")}

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401,detail="Sign in required",headers={"WWW-Authenticate":"Bearer"})
    return verify_access_token(credentials.credentials)
