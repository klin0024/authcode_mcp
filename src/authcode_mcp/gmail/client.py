import base64
from email.mime.text import MIMEText
from typing import Any, Optional

import httpx

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise RuntimeError(f"Gmail API error {response.status_code}: {response.text}")


def _build_raw_message(*, to: str, subject: str, body: str) -> str:
    mime = MIMEText(body)
    mime["To"] = to
    mime["Subject"] = subject
    return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")


# ---- 讀取類(不需要使用者確認) ----------------------------------------


async def list_messages(access_token: str, *, query: str = "", max_results: int = 30) -> dict[str, Any]:
    params: dict[str, Any] = {"maxResults": max_results}
    if query:
        params["q"] = query
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}/messages", headers=_headers(access_token), params=params
        )
        _raise_for_status(response)
        return response.json()


async def get_message(access_token: str, *, message_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}/messages/{message_id}",
            headers=_headers(access_token),
            params={"format": "full"},
        )
        _raise_for_status(response)
        return response.json()


async def get_thread(access_token: str, *, thread_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}/threads/{thread_id}",
            headers=_headers(access_token),
            params={"format": "full"},
        )
        _raise_for_status(response)
        return response.json()


async def list_labels(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{GMAIL_API_BASE}/labels", headers=_headers(access_token))
        _raise_for_status(response)
        return response.json()


async def get_attachment(access_token: str, *, message_id: str, attachment_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}/messages/{message_id}/attachments/{attachment_id}",
            headers=_headers(access_token),
        )
        _raise_for_status(response)
        return response.json()


async def list_drafts(access_token: str, *, max_results: int = 30) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{GMAIL_API_BASE}/drafts",
            headers=_headers(access_token),
            params={"maxResults": max_results},
        )
        _raise_for_status(response)
        return response.json()


# ---- 有副作用(預設要走 /confirm 使用者同意流程) --------------------------


async def send_message(access_token: str, *, to: str, subject: str, body: str) -> dict[str, Any]:
    raw = _build_raw_message(to=to, subject=subject, body=body)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/messages/send",
            headers=_headers(access_token),
            json={"raw": raw},
        )
        _raise_for_status(response)
        return response.json()


async def modify_labels(
    access_token: str,
    *,
    message_id: str,
    add_label_ids: Optional[list[str]] = None,
    remove_label_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/messages/{message_id}/modify",
            headers=_headers(access_token),
            json={"addLabelIds": add_label_ids or [], "removeLabelIds": remove_label_ids or []},
        )
        _raise_for_status(response)
        return response.json()


async def archive_message(access_token: str, *, message_id: str) -> dict[str, Any]:
    # Gmail API 沒有專門的 archive 端點,語意上等於「拿掉 INBOX 這個 label」。
    return await modify_labels(access_token, message_id=message_id, remove_label_ids=["INBOX"])


async def trash_message(access_token: str, *, message_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/messages/{message_id}/trash", headers=_headers(access_token)
        )
        _raise_for_status(response)
        return response.json()


async def untrash_message(access_token: str, *, message_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/messages/{message_id}/untrash", headers=_headers(access_token)
        )
        _raise_for_status(response)
        return response.json()


async def create_draft(access_token: str, *, to: str, subject: str, body: str) -> dict[str, Any]:
    raw = _build_raw_message(to=to, subject=subject, body=body)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/drafts",
            headers=_headers(access_token),
            json={"message": {"raw": raw}},
        )
        _raise_for_status(response)
        return response.json()


async def update_draft(
    access_token: str, *, draft_id: str, to: str, subject: str, body: str
) -> dict[str, Any]:
    raw = _build_raw_message(to=to, subject=subject, body=body)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.put(
            f"{GMAIL_API_BASE}/drafts/{draft_id}",
            headers=_headers(access_token),
            json={"message": {"raw": raw}},
        )
        _raise_for_status(response)
        return response.json()


async def delete_draft(access_token: str, *, draft_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(
            f"{GMAIL_API_BASE}/drafts/{draft_id}", headers=_headers(access_token)
        )
        _raise_for_status(response)
        # 成功是 204 No Content,沒有 body 可以解析。
        return {"status": "deleted", "draft_id": draft_id}


async def send_draft(access_token: str, *, draft_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{GMAIL_API_BASE}/drafts/send",
            headers=_headers(access_token),
            json={"id": draft_id},
        )
        _raise_for_status(response)
        return response.json()
