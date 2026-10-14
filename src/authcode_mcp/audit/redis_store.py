import json
from dataclasses import asdict, fields
from datetime import datetime

from .base import AuditRecord, AuditStore

try:
    from redis.asyncio import Redis
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "RedisAuditStore 需要 'redis' 套件,請安裝 authcode-mcp[redis] 或 `pip install redis`。"
    ) from exc


def _serialize(record: AuditRecord) -> str:
    data = asdict(record)
    for f in fields(record):
        if f.type is datetime and isinstance(data.get(f.name), datetime):
            data[f.name] = data[f.name].isoformat()
    return json.dumps(data)


def _deserialize(raw: str) -> AuditRecord:
    data = json.loads(raw)
    for f in fields(AuditRecord):
        if f.type is datetime and isinstance(data.get(f.name), str):
            data[f.name] = datetime.fromisoformat(data[f.name])
    return AuditRecord(**data)


class RedisAuditStore(AuditStore):
    """多 process 共享用。用 Redis List(LPUSH + LTRIM)保存,最新的一律在最前面,
    超過上限自動裁切——比 CacheStore 那種泛型 Sorted Set 索引方案更直接(見 DESIGN.md 9.8)。

    注意:List 沒有「單筆過期」的概念,所以 settings.audit_log_ttl_seconds 對這個實作不生效,
    只有 max_records(筆數上限)在裁切,沒有時間上限。要做到真正的時間保留期限,需要改成
    每筆各自一個帶 EXPIRE 的 key + 另外維護一個索引,目前先不做這個複雜度。
    """

    def __init__(self, client: "Redis", key: str = "authcode_mcp:audit_log", max_records: int = 10000) -> None:
        self._client = client
        self._key = key
        self._max_records = max_records

    async def record(self, record: AuditRecord) -> None:
        await self._client.lpush(self._key, _serialize(record))
        await self._client.ltrim(self._key, 0, self._max_records - 1)

    async def list_recent(self, limit: int) -> list[AuditRecord]:
        raws = await self._client.lrange(self._key, 0, limit - 1)
        return [_deserialize(raw) for raw in raws]

    async def get_by_action_id(self, action_id: str) -> list[AuditRecord]:
        # 線性掃描全部紀錄,不額外維護 action_id 索引(見 DESIGN.md 10.7)。
        raws = await self._client.lrange(self._key, 0, -1)
        records = (_deserialize(raw) for raw in raws)
        return [r for r in records if r.action_id == action_id]
