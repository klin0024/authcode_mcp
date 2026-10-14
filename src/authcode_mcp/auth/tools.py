from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP

from ..cache.base import CacheStore, SessionRecord, generate_session_id
from ..config import Settings
from . import google_oauth


def register_auth_tools(mcp: FastMCP, session_store: CacheStore[SessionRecord], settings: Settings) -> None:
    @mcp.tool()
    async def exchange_google_code(code: str) -> dict:
        """使用一次性授權碼向 Google 換取 access token,並建立一個短效 session。

        授權碼來自 /oauth/callback 頁面(使用者登入 Google 完成授權後,由該頁面顯示、
        使用者手動複製貼回);這個 code 只能被交換一次,交換後即失效。

        Args:
            code: Google 導回 /oauth/callback 時帶的一次性 authorization code。

        Returns:
            dict,包含:
                session_id: 之後呼叫 Gmail 相關 tool 時要帶入的 session 識別碼。
                expires_in: 這個 session_id 的有效秒數,超過就要重新走一次授權流程。
        """
        token_data = await google_oauth.exchange_code_for_token(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.oauth_redirect_uri,
            code=code,
        )

        # 稽核紀錄要識別使用者,這裡就是唯一能拿到 access_token 換 email 的時間點;
        # 失敗就讓整個 exchange_google_code 失敗,不接受「先給 session 之後再補 email」的半殘狀態
        # (見 DESIGN.md 9.2)。
        google_email = await google_oauth.get_user_email(token_data["access_token"])

        expires_in = int(token_data["expires_in"])
        session_ttl = min(expires_in, settings.max_session_ttl_seconds)
        now = datetime.now(timezone.utc)

        record = SessionRecord(
            session_id=generate_session_id(),
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            scope=token_data.get("scope", " ".join(settings.gmail_scopes)),
            google_email=google_email,
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in),
        )

        await session_store.set(record.session_id, record, ttl_seconds=session_ttl)

        return {"session_id": record.session_id, "expires_in": session_ttl}
