import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Optional, TypeVar

SESSION_ID_PREFIX = "session_id_"
ACTION_ID_PREFIX = "action_id_"


def generate_session_id() -> str:
    """產生不可預測、與 access_token 脫鉤的 session id。"""
    return f"{SESSION_ID_PREFIX}{secrets.token_urlsafe(32)}"


def generate_action_id() -> str:
    """產生不可預測的待確認動作 id;本身即憑證,見 DESIGN.md 8.5。"""
    return f"{ACTION_ID_PREFIX}{secrets.token_urlsafe(32)}"


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    access_token: str
    refresh_token: Optional[str]
    scope: str
    google_email: Optional[str]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class PendingAction:
    """呼叫某個 tool 時建立、等使用者到 /confirm/{action_id} 按下確認才會真的執行的動作。"""

    action_id: str
    access_token: str  # 從 session 快照下來,不依賴 session 是否還活著(見 DESIGN.md 8.3)
    user: Optional[str]  # 從 session.google_email 快照下來,confirm 時才知道要記給誰(見 DESIGN.md 9.6)
    session_id: str  # 同樣是快照,confirm 執行時的稽核紀錄要用
    tool_name: str  # confirm route 用這個查 ACTION_EXECUTORS,找出該怎麼真正執行
    params: dict
    created_at: datetime


T = TypeVar("T")


class CacheStore(ABC, Generic[T]):
    """通用的短效 key-value 快取,session_id/action_id -> T。"""

    @abstractmethod
    async def set(self, key: str, value: T, ttl_seconds: int) -> None:
        """寫入,ttl 到期後應自動失效(TTL 由實作自行處理)。"""

    @abstractmethod
    async def get(self, key: str) -> Optional[T]:
        """查無資料或已過期 → 回傳 None。"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """主動撤銷/登出時呼叫。"""

    @abstractmethod
    async def pop(self, key: str) -> Optional[T]:
        """原子地「取出並刪除」,確保同一個 key 只能被成功消費一次(見 DESIGN.md 8.4)。"""
