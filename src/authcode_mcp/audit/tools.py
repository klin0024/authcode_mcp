from fastmcp import FastMCP

from ..cache.base import CacheStore, PendingAction
from ..config import Settings
from .base import AuditStore


def register_action_status_tool(
    mcp: FastMCP,
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
    settings: Settings,
) -> None:
    @mcp.tool()
    async def get_action_status(action_id: str) -> dict:
        """查詢一個 action_id(某個需要確認的 tool 回傳的那個)後來的狀態。

        用途:呼叫需要確認的 tool(例如 gmail_send_message)後拿到 action_id,顯示
        confirm_url 給使用者;之後(甚至是下一次全新的對話)可以用這個 tool 拿著同一個
        action_id 回頭查「使用者確認了嗎?成功了嗎?」,不需要用其他方式間接推測。

        Args:
            action_id: 之前呼叫某個需要確認的 tool 時,回應裡的 action_id。

        Returns:
            還沒被確認:{"status": "pending_confirmation", "tool_name": ..., "confirm_url": ..., "preview": ...}。
            已經執行完:{"status": "success" | "failed", "tool_name": ..., "timestamp": ..., "params": ...}。
            查無資料:{"status": "not_found", "message": ...}(action_id 打錯、已過期,或從未存在)。
        """
        pending = await pending_action_store.get(action_id)  # 只讀,不消費
        if pending is not None:
            return {
                "status": "pending_confirmation",
                "tool_name": pending.tool_name,
                "confirm_url": f"{settings.public_base_url}/confirm/{action_id}",
                "preview": pending.params,
            }

        records = await audit_store.get_by_action_id(action_id)
        if records:
            latest = max(records, key=lambda r: r.timestamp)
            return {
                "status": latest.outcome,
                "tool_name": latest.tool_name,
                "timestamp": latest.timestamp.isoformat(),
                "params": latest.params,
            }

        return {"status": "not_found", "message": "找不到這個 action_id,可能已過期或從未存在。"}
