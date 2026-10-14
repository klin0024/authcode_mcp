import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

AUDIT_ID_PREFIX = "audit_id_"

# 信件實際內容欄位——稽核紀錄只記元數據,這兩個一律濾掉(見 DESIGN.md 9.5)。
_AUDIT_CONTENT_KEYS = {"subject", "body"}


def generate_audit_id() -> str:
    return f"{AUDIT_ID_PREFIX}{secrets.token_urlsafe(32)}"


def redact_for_audit(params: dict) -> dict:
    """把信件實際內容(subject/body)濾掉,只留識別碼/操作參數。"""
    return {k: v for k, v in params.items() if k not in _AUDIT_CONTENT_KEYS}


@dataclass(frozen=True)
class AuditRecord:
    audit_id: str
    action_id: Optional[str]  # 只有經過 _execute_or_defer 建立過 PendingAction 的紀錄才有值(見 DESIGN.md 10.3)
    timestamp: datetime
    user: Optional[str]  # SessionRecord.google_email;理論上不會是 None
    session_id: str
    tool_name: str
    params: dict  # 已經過 redact_for_audit() 處理
    outcome: str  # "success" | "failed" | "pending_confirmation"
    source: str  # "direct"(呼叫當下就執行)| "confirm"(經 /confirm 才執行)


class AuditStore(ABC):
    """稽核紀錄專用的 append-only store。刻意不是 CacheStore[T] 的具現化——

    list_recent() 這種「列出最近幾筆」的語意跟 CacheStore 的單一 key 存取(get/delete/pop)
    完全不同,稽核紀錄本質是附加、不會被單筆取用或消費(見 DESIGN.md 9.8 第 1 點)。
    """

    @abstractmethod
    async def record(self, record: AuditRecord) -> None:
        """新增一筆稽核紀錄。"""

    @abstractmethod
    async def list_recent(self, limit: int) -> list[AuditRecord]:
        """依時間新到舊回傳最近 limit 筆(不含已過期的)。"""

    @abstractmethod
    async def get_by_action_id(self, action_id: str) -> list[AuditRecord]:
        """回傳這個 action_id 底下的所有紀錄(通常是 0~2 筆:pending_confirmation + 終局結果)。"""


async def record_audit(
    audit_store: AuditStore,
    *,
    user: Optional[str],
    session_id: str,
    tool_name: str,
    params: dict,
    outcome: str,
    source: str,
    action_id: Optional[str] = None,
) -> None:
    """建立並寫入一筆 AuditRecord;params 會先經過 redact_for_audit() 處理。"""
    await audit_store.record(
        AuditRecord(
            audit_id=generate_audit_id(),
            action_id=action_id,
            timestamp=datetime.now(timezone.utc),
            user=user,
            session_id=session_id,
            tool_name=tool_name,
            params=redact_for_audit(params),
            outcome=outcome,
            source=source,
        )
    )
