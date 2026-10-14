from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastmcp import FastMCP

from ..audit.base import AuditStore, record_audit
from ..auth.google_oauth import build_google_auth_url
from ..cache.base import CacheStore, PendingAction, SessionRecord, generate_action_id
from ..config import Settings
from . import client as gmail_client


async def _resolve_session(
    session_store: CacheStore[SessionRecord], settings: Settings, session_id: Optional[str]
) -> SessionRecord | dict:
    """回傳有效的 SessionRecord;若未授權/已過期,回傳可直接當 tool 結果回給 Agent 的 dict。"""
    if not session_id:
        return {
            "status": "unauthenticated",
            "message": "請先完成授權",
            "auth_url": build_google_auth_url(settings),
        }

    record = await session_store.get(session_id)
    if record is None:
        return {
            "status": "session_expired",
            "message": "授權已過期,請重新驗證",
            "auth_url": build_google_auth_url(settings),
        }

    return record


async def _execute_and_audit(
    audit_store: AuditStore,
    session: SessionRecord,
    tool_name: str,
    params: dict,
    call: Callable[[], Awaitable[dict]],
) -> dict:
    """執行實際的 Gmail API 呼叫,並記一筆稽核紀錄(成功/失敗都記,見 DESIGN.md 9.6)。

    跟 _resolve/_defer 一樣是一般函式呼叫,不是 decorator,不影響外層 tool 的參數簽章。
    """
    try:
        result = await call()
    except Exception:
        await record_audit(
            audit_store, user=session.google_email, session_id=session.session_id,
            tool_name=tool_name, params=params, outcome="failed", source="direct",
        )
        raise

    await record_audit(
        audit_store, user=session.google_email, session_id=session.session_id,
        tool_name=tool_name, params=params, outcome="success", source="direct",
    )
    return result


async def _execute_or_defer(
    audit_store: AuditStore,
    pending_action_store: CacheStore[PendingAction],
    settings: Settings,
    tool_name: str,
    session: SessionRecord,
    params: dict,
    execute: Callable[[], Awaitable[dict]],
) -> dict:
    """依 settings.confirm_required_tools 決定:直接執行,或先建立待確認動作、回傳確認連結。

    不用 decorator 包這一層,是為了讓每個 tool 保留自己完整、具名的參數簽章給 fastmcp 產生
    schema(理由跟 _resolve_session 旁邊那段一樣,見 DESIGN.md 5.1/8.4)。
    """
    if tool_name not in settings.confirm_required_tools_set:
        return await _execute_and_audit(audit_store, session, tool_name, params, execute)

    action_id = generate_action_id()
    pending = PendingAction(
        action_id=action_id,
        access_token=session.access_token,
        user=session.google_email,
        session_id=session.session_id,
        tool_name=tool_name,
        params=params,
        created_at=datetime.now(timezone.utc),
    )
    await pending_action_store.set(action_id, pending, ttl_seconds=settings.pending_action_ttl_seconds)

    # 這裡只記「準備要做」這件事本身;真正的 success/failed 要等使用者到 /confirm 按下確認才記
    # (見 DESIGN.md 9.6)——這個時間點還沒有任何 Gmail 帳號狀態被改變。
    # action_id 帶進去,讓 get_action_status(action_id) 之後查得到這筆(見 DESIGN.md 10.3)。
    await record_audit(
        audit_store, user=session.google_email, session_id=session.session_id,
        tool_name=tool_name, params=params, outcome="pending_confirmation", source="direct",
        action_id=action_id,
    )

    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "confirm_url": f"{settings.public_base_url}/confirm/{action_id}",
        "expires_in": settings.pending_action_ttl_seconds,
        "preview": params,
    }


def build_action_executors() -> dict[str, Callable[[str, dict], Awaitable[dict]]]:
    """tool_name -> 「用 access_token + 參數 dict 真正執行」的函式,給 /confirm 這個 route 用。"""
    return {
        "gmail_send_message": lambda token, params: gmail_client.send_message(token, **params),
        "gmail_modify_labels": lambda token, params: gmail_client.modify_labels(token, **params),
        "gmail_archive_message": lambda token, params: gmail_client.archive_message(token, **params),
        "gmail_trash_message": lambda token, params: gmail_client.trash_message(token, **params),
        "gmail_untrash_message": lambda token, params: gmail_client.untrash_message(token, **params),
        "gmail_create_draft": lambda token, params: gmail_client.create_draft(token, **params),
        "gmail_update_draft": lambda token, params: gmail_client.update_draft(token, **params),
        "gmail_delete_draft": lambda token, params: gmail_client.delete_draft(token, **params),
        "gmail_send_draft": lambda token, params: gmail_client.send_draft(token, **params),
    }


def _build_readonly_gmail_tools(
    session_store: CacheStore[SessionRecord],
    audit_store: AuditStore,
    settings: Settings,
) -> dict[str, Callable[..., Awaitable[dict]]]:
    """唯讀查詢類 tool(不需要使用者確認)。獨立成一個小 factory,純粹是為了讓人(以及靜態
    分析工具)一次只需要盯著 6 個 tool,而不是跟有副作用的 9 個混在一起的 15 個。"""

    async def _resolve(session_id: Optional[str]) -> SessionRecord | dict:
        return await _resolve_session(session_store, settings, session_id)

    async def gmail_list_messages(
        session_id: Optional[str] = None, query: str = "", max_results: int = 30
    ) -> dict:
        """列出使用者 Gmail 信件(只回傳 id/threadId,不含信件內容)。

        首次呼叫不需帶 session_id;若未授權或 session 已過期,會回傳授權連結,
        請使用者完成授權後,改呼叫 exchange_google_code 取得 session_id 再重試。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            query: Gmail 搜尋語法,例如 "is:unread"、"from:someone@example.com"。留空表示不過濾。
            max_results: 最多回傳幾封信,預設 30。

        Returns:
            成功時為 Gmail API 的原始 messages 列表(dict);未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"query": query, "max_results": max_results}
        return await _execute_and_audit(
            audit_store, session, "gmail_list_messages", params,
            lambda: gmail_client.list_messages(session.access_token, query=query, max_results=max_results),
        )

    async def gmail_get_message(session_id: Optional[str] = None, message_id: str = "") -> dict:
        """讀取單一 Gmail 信件的完整內容。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 信件 ID,通常來自 gmail_list_messages 回傳結果裡的 "id" 欄位。

        Returns:
            成功時為 Gmail API 的完整信件內容(dict);未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"message_id": message_id}
        return await _execute_and_audit(
            audit_store, session, "gmail_get_message", params,
            lambda: gmail_client.get_message(session.access_token, message_id=message_id),
        )

    async def gmail_get_thread(session_id: Optional[str] = None, thread_id: str = "") -> dict:
        """讀取一個完整的 Gmail 對話串(thread),包含裡面所有信件。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            thread_id: 對話串 ID,通常來自 gmail_list_messages/gmail_get_message 的 "threadId" 欄位。

        Returns:
            成功時為 Gmail API 的完整 thread 內容(dict);未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"thread_id": thread_id}
        return await _execute_and_audit(
            audit_store, session, "gmail_get_thread", params,
            lambda: gmail_client.get_thread(session.access_token, thread_id=thread_id),
        )

    async def gmail_list_labels(session_id: Optional[str] = None) -> dict:
        """列出這個 Gmail 帳號的所有 label(系統內建的 INBOX/TRASH/UNREAD 等,以及使用者自訂的)。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。

        Returns:
            成功時為 Gmail API 的 labels 列表(dict);未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        return await _execute_and_audit(
            audit_store, session, "gmail_list_labels", {},
            lambda: gmail_client.list_labels(session.access_token),
        )

    async def gmail_get_attachment(
        session_id: Optional[str] = None, message_id: str = "", attachment_id: str = ""
    ) -> dict:
        """取得信件附件的內容(base64url 編碼)。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 附件所屬的信件 ID。
            attachment_id: 附件 ID,來自 gmail_get_message 回傳內容裡的 attachmentId 欄位。

        Returns:
            成功時為 {"size": ..., "data": "<base64url>"};未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"message_id": message_id, "attachment_id": attachment_id}
        return await _execute_and_audit(
            audit_store, session, "gmail_get_attachment", params,
            lambda: gmail_client.get_attachment(
                session.access_token, message_id=message_id, attachment_id=attachment_id
            ),
        )

    async def gmail_list_drafts(session_id: Optional[str] = None, max_results: int = 30) -> dict:
        """列出這個 Gmail 帳號的草稿。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            max_results: 最多回傳幾筆草稿,預設 30。

        Returns:
            成功時為 Gmail API 的 drafts 列表(dict);未授權/過期時回傳
            {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"max_results": max_results}
        return await _execute_and_audit(
            audit_store, session, "gmail_list_drafts", params,
            lambda: gmail_client.list_drafts(session.access_token, max_results=max_results),
        )

    return {
        "gmail_list_messages": gmail_list_messages,
        "gmail_get_message": gmail_get_message,
        "gmail_get_thread": gmail_get_thread,
        "gmail_list_labels": gmail_list_labels,
        "gmail_get_attachment": gmail_get_attachment,
        "gmail_list_drafts": gmail_list_drafts,
    }


def _build_mutating_gmail_tools(
    session_store: CacheStore[SessionRecord],
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
    settings: Settings,
) -> dict[str, Callable[..., Awaitable[dict]]]:
    """有副作用(新增/修改/刪除/寄送)類 tool,預設要走 /confirm 使用者同意流程。
    同樣獨立成一個小 factory,理由同 _build_readonly_gmail_tools 上面的註解。"""

    async def _resolve(session_id: Optional[str]) -> SessionRecord | dict:
        return await _resolve_session(session_store, settings, session_id)

    async def _defer(tool_name: str, session: SessionRecord, params: dict, execute) -> dict:
        return await _execute_or_defer(
            audit_store, pending_action_store, settings, tool_name, session, params, execute
        )

    async def gmail_send_message(
        session_id: Optional[str] = None, to: str = "", subject: str = "", body: str = ""
    ) -> dict:
        """寄送一封 Gmail 信件(純文字內容)。

        若 "gmail_send_message" 在 CONFIRM_REQUIRED_TOOLS 名單中(預設是),
        呼叫這個 tool 並不會真的寄出信,而是建立一個待確認動作並回傳 confirm_url;
        要等使用者親自打開這個連結、按下確認,信才會真的送出。請把 confirm_url 原樣顯示給使用者。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            to: 收件人 email 地址。
            subject: 信件主旨。
            body: 信件純文字內容。

        Returns:
            若需要使用者確認:{"status": "pending_confirmation", "confirm_url": ..., "preview": ...}。
            若不需要確認就直接寄出:Gmail API 回傳的已寄出信件資訊(dict,含 id/threadId)。
            未授權/過期時回傳 {"status": ..., "message": ..., "auth_url": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"to": to, "subject": subject, "body": body}
        return await _defer(
            "gmail_send_message", session, params,
            lambda: gmail_client.send_message(session.access_token, **params),
        )

    async def gmail_modify_labels(
        session_id: Optional[str] = None,
        message_id: str = "",
        add_label_ids: Optional[list[str]] = None,
        remove_label_ids: Optional[list[str]] = None,
    ) -> dict:
        """新增或移除一封信的 label(例如加上/拿掉星號、已讀狀態、自訂 label)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 要修改的信件 ID。
            add_label_ids: 要加上的 label ID 列表,例如 ["STARRED"]。可留空。
            remove_label_ids: 要移除的 label ID 列表,例如 ["UNREAD"]。可留空。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的更新後信件資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {
            "message_id": message_id,
            "add_label_ids": add_label_ids or [],
            "remove_label_ids": remove_label_ids or [],
        }
        return await _defer(
            "gmail_modify_labels", session, params,
            lambda: gmail_client.modify_labels(session.access_token, **params),
        )

    async def gmail_archive_message(session_id: Optional[str] = None, message_id: str = "") -> dict:
        """封存一封信(從收件匣移除,但不放進垃圾桶)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 要封存的信件 ID。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的更新後信件資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"message_id": message_id}
        return await _defer(
            "gmail_archive_message", session, params,
            lambda: gmail_client.archive_message(session.access_token, **params),
        )

    async def gmail_trash_message(session_id: Optional[str] = None, message_id: str = "") -> dict:
        """把一封信移到垃圾桶(不是永久刪除,之後還能還原)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 要移到垃圾桶的信件 ID。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的更新後信件資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"message_id": message_id}
        return await _defer(
            "gmail_trash_message", session, params,
            lambda: gmail_client.trash_message(session.access_token, **params),
        )

    async def gmail_untrash_message(session_id: Optional[str] = None, message_id: str = "") -> dict:
        """把一封信從垃圾桶還原。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            message_id: 要還原的信件 ID。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的更新後信件資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"message_id": message_id}
        return await _defer(
            "gmail_untrash_message", session, params,
            lambda: gmail_client.untrash_message(session.access_token, **params),
        )

    async def gmail_create_draft(
        session_id: Optional[str] = None, to: str = "", subject: str = "", body: str = ""
    ) -> dict:
        """建立一封新的 Gmail 草稿(不會寄出)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            to: 收件人 email 地址。
            subject: 信件主旨。
            body: 信件純文字內容。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的草稿資訊(dict,含 id)。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"to": to, "subject": subject, "body": body}
        return await _defer(
            "gmail_create_draft", session, params,
            lambda: gmail_client.create_draft(session.access_token, **params),
        )

    async def gmail_update_draft(
        session_id: Optional[str] = None,
        draft_id: str = "",
        to: str = "",
        subject: str = "",
        body: str = "",
    ) -> dict:
        """更新一份既有草稿的內容(整封信會被取代,不是增量修改)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            draft_id: 要更新的草稿 ID,來自 gmail_list_drafts/gmail_create_draft 的 "id" 欄位。
            to: 收件人 email 地址。
            subject: 信件主旨。
            body: 信件純文字內容。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的更新後草稿資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"draft_id": draft_id, "to": to, "subject": subject, "body": body}
        return await _defer(
            "gmail_update_draft", session, params,
            lambda: gmail_client.update_draft(session.access_token, **params),
        )

    async def gmail_delete_draft(session_id: Optional[str] = None, draft_id: str = "") -> dict:
        """永久刪除一份草稿(無法復原)。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            draft_id: 要刪除的草稿 ID。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 {"status": "deleted", "draft_id": ...}。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"draft_id": draft_id}
        return await _defer(
            "gmail_delete_draft", session, params,
            lambda: gmail_client.delete_draft(session.access_token, **params),
        )

    async def gmail_send_draft(session_id: Optional[str] = None, draft_id: str = "") -> dict:
        """寄出一份既有草稿。

        預設要經過使用者確認才會真的執行,見 gmail_send_message 的說明。

        Args:
            session_id: exchange_google_code 回傳的 session 識別碼;未授權時可留空。
            draft_id: 要寄出的草稿 ID。

        Returns:
            需要確認時回傳 {"status": "pending_confirmation", "confirm_url": ..., ...};
            不需確認時為 Gmail API 回傳的已寄出信件資訊。
        """
        session = await _resolve(session_id)
        if isinstance(session, dict):
            return session
        params = {"draft_id": draft_id}
        return await _defer(
            "gmail_send_draft", session, params,
            lambda: gmail_client.send_draft(session.access_token, **params),
        )

    return {
        "gmail_send_message": gmail_send_message,
        "gmail_modify_labels": gmail_modify_labels,
        "gmail_archive_message": gmail_archive_message,
        "gmail_trash_message": gmail_trash_message,
        "gmail_untrash_message": gmail_untrash_message,
        "gmail_create_draft": gmail_create_draft,
        "gmail_update_draft": gmail_update_draft,
        "gmail_delete_draft": gmail_delete_draft,
        "gmail_send_draft": gmail_send_draft,
    }


def _build_gmail_tools(
    session_store: CacheStore[SessionRecord],
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
    settings: Settings,
) -> dict[str, Callable[..., Awaitable[dict]]]:
    """回傳「工具名稱 -> 未註冊的函式」對照表,實際要不要註冊由 settings.gmail_enabled_tools 決定。

    純粹是兩個子 factory 的合併;個別 tool 的參數簽章、行為完全不變,對
    register_gmail_tools()/mcp.add_tool() 而言這個函式的輸出跟拆分前一模一樣。
    """
    return {
        **_build_readonly_gmail_tools(session_store, audit_store, settings),
        **_build_mutating_gmail_tools(session_store, pending_action_store, audit_store, settings),
    }


def register_gmail_tools(
    mcp: FastMCP,
    session_store: CacheStore[SessionRecord],
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
    settings: Settings,
) -> None:
    """依 settings.gmail_enabled_tools(.env 的 GMAIL_ENABLED_TOOLS)動態註冊 Gmail tool。"""
    available = _build_gmail_tools(session_store, pending_action_store, audit_store, settings)
    enabled = settings.gmail_enabled_tools_list

    unknown = [name for name in enabled if name not in available]
    if unknown:
        raise ValueError(
            f"GMAIL_ENABLED_TOOLS 有未知的 tool 名稱: {unknown};"
            f"可用的有: {sorted(available)}"
        )

    for name in enabled:
        mcp.add_tool(available[name])
