import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from ..config import Settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"


def generate_state(secret: str) -> str:
    """產生帶時間戳、HMAC 簽章的 state,不需要額外儲存就能在 callback 驗證(防 CSRF)。"""
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def verify_state(state: str, secret: str, max_age_seconds: int) -> bool:
    try:
        timestamp_str, signature = state.split(".", 1)
    except ValueError:
        return False

    expected = hmac.new(secret.encode(), timestamp_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False

    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return False

    return 0 <= (time.time() - timestamp) <= max_age_seconds


def build_authorization_url(*, client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def build_google_auth_url(settings: Settings) -> str:
    state = generate_state(settings.state_secret)
    return build_authorization_url(
        client_id=settings.google_client_id,
        redirect_uri=settings.oauth_redirect_uri,
        scopes=settings.gmail_scopes,
        state=state,
    )


async def exchange_code_for_token(
    *, client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict:
    """用一次性 authorization code 向 Google token endpoint 換 access token(單次有效)。"""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Google token exchange 失敗 ({response.status_code}): {response.text}")
        return response.json()


async def get_user_email(access_token: str) -> str:
    """用 access_token 查這個帳號的 email,給稽核紀錄識別使用者用(見 DESIGN.md 9.2)。

    需要 gmail_scopes 裡有 userinfo.email 這個 scope 才會成功。
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Google userinfo 查詢失敗 ({response.status_code}): {response.text}")
        return response.json()["email"]
