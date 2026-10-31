import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse


def configured() -> bool:
    return all(os.getenv(key, "").strip() for key in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"))


def _require_config() -> tuple[str, str, str, str]:
    issuer = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
    client_id = os.getenv("OIDC_CLIENT_ID", "").strip()
    client_secret = os.getenv("OIDC_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("OIDC_REDIRECT_URI", "").strip()
    if not issuer or not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail={"code": "oidc_not_configured", "message": "OIDC 尚未配置"})
    return issuer, client_id, client_secret, redirect_uri


async def start(request: Request) -> RedirectResponse:
    issuer, client_id, _, redirect_uri = _require_config()
    async with httpx.AsyncClient(timeout=10) as client:
        discovery = (await client.get(f"{issuer}/.well-known/openid-configuration")).raise_for_status().json()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    request.session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier}
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": os.getenv("OIDC_SCOPES", "openid profile email"), "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    return RedirectResponse(f"{discovery['authorization_endpoint']}?{urlencode(params)}")


async def callback(request: Request) -> dict:
    issuer, client_id, client_secret, redirect_uri = _require_config()
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    saved = request.session.pop("oidc", None)
    if not code or not saved or not secrets.compare_digest(state, saved.get("state", "")):
        raise HTTPException(status_code=400, detail={"code": "oidc_callback_invalid", "message": "登录回调无效"})
    async with httpx.AsyncClient(timeout=15) as client:
        discovery = (await client.get(f"{issuer}/.well-known/openid-configuration")).raise_for_status().json()
        token = (await client.post(discovery["token_endpoint"], data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret, "code_verifier": saved["verifier"]})).raise_for_status().json()
        id_token = token.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail={"code": "oidc_id_token_missing", "message": "身份平台未返回 ID Token"})
        jwks = (await client.get(discovery["jwks_uri"])).raise_for_status().json()
        claims = jwt.decode(id_token, JsonWebKey.import_key_set(jwks), claims_options={"iss": {"essential": True, "value": issuer}, "aud": {"essential": True, "value": client_id}, "nonce": {"essential": True, "value": saved["nonce"]}})
        claims.validate()
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        if not userinfo_endpoint or not token.get("access_token"):
            raise HTTPException(status_code=400, detail={"code": "oidc_profile_unavailable", "message": "身份平台未返回用户资料"})
        profile = (await client.get(userinfo_endpoint, headers={"Authorization": f"Bearer {token['access_token']}"})).raise_for_status().json()
    if not profile.get("sub") or profile.get("sub") != claims.get("sub"):
        raise HTTPException(status_code=400, detail={"code": "oidc_subject_missing", "message": "身份平台返回的用户标识无效"})
    return {"issuer": issuer, "subject": profile["sub"], "email": profile.get("email"), "email_verified": bool(profile.get("email_verified")), "display_name": profile.get("name") or profile.get("preferred_username") or "用户", "avatar_url": profile.get("picture")}
