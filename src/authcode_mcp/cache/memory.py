import asyncio
import time
from typing import Generic, Optional, TypeVar

from .base import CacheStore

T = TypeVar("T")


class InMemoryCacheStore(CacheStore[T], Generic[T]):
    """單一 process 用的記憶體快取:重啟即清空,不跨 process 共享。"""

    def __init__(self) -> None:
        self._records: dict[str, tuple[T, float]] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: T, ttl_seconds: int) -> None:
        expire_at = time.monotonic() + ttl_seconds
        async with self._lock:
            self._records[key] = (value, expire_at)

    async def get(self, key: str) -> Optional[T]:
        async with self._lock:
            return self._get_if_not_expired(key)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._records.pop(key, None)

    async def pop(self, key: str) -> Optional[T]:
        async with self._lock:
            value = self._get_if_not_expired(key)
            self._records.pop(key, None)
            return value

    def _get_if_not_expired(self, key: str) -> Optional[T]:
        """呼叫端必須已持有 self._lock。"""
        entry = self._records.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if time.monotonic() >= expire_at:
            del self._records[key]
            return None
        return value
