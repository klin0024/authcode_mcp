import asyncio
import time

from .base import AuditRecord, AuditStore


class InMemoryAuditStore(AuditStore):
    """單一 process 用:重啟即清空。用 list 依寫入順序保存,list_recent 反向取前 N 筆。"""

    def __init__(self, ttl_seconds: int, max_records: int = 10000) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_records = max_records
        self._records: list[tuple[AuditRecord, float]] = []
        self._lock = asyncio.Lock()

    async def record(self, record: AuditRecord) -> None:
        expire_at = time.monotonic() + self._ttl_seconds
        async with self._lock:
            self._records.append((record, expire_at))
            if len(self._records) > self._max_records:
                del self._records[: len(self._records) - self._max_records]

    async def list_recent(self, limit: int) -> list[AuditRecord]:
        now = time.monotonic()
        async with self._lock:
            self._records[:] = [(r, e) for r, e in self._records if e > now]
            recent = self._records[-limit:]
        return [r for r, _ in reversed(recent)]

    async def get_by_action_id(self, action_id: str) -> list[AuditRecord]:
        # 線性掃描,不維護額外索引(見 DESIGN.md 10.7)。
        now = time.monotonic()
        async with self._lock:
            self._records[:] = [(r, e) for r, e in self._records if e > now]
            return [r for r, _ in self._records if r.action_id == action_id]
