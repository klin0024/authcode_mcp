import json
from dataclasses import asdict, fields
from datetime import datetime
from typing import Generic, Optional, Type, TypeVar

from .base import CacheStore

try:
    from redis.asyncio import Redis
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "RedisCacheStore 需要 'redis' 套件,請安裝 authcode-mcp[redis] 或 `pip install redis`。"
    ) from exc

T = TypeVar("T")


def _serialize(value: object) -> str:
    data = asdict(value)
    for f in fields(value):
        if f.type is datetime and isinstance(data.get(f.name), datetime):
            data[f.name] = data[f.name].isoformat()
    return json.dumps(data)


def _deserialize(value_type: Type[T], raw: str) -> T:
    data = json.loads(raw)
    for f in fields(value_type):
        if f.type is datetime and isinstance(data.get(f.name), str):
            data[f.name] = datetime.fromisoformat(data[f.name])
    return value_type(**data)


class RedisCacheStore(CacheStore[T], Generic[T]):
    """多 process/多 replica 共享用;TTL 交給 Redis 的 EXPIRE 處理。"""

    def __init__(self, client: "Redis", value_type: Type[T], key_prefix: str) -> None:
        self._client = client
        self._value_type = value_type
        self._key_prefix = key_prefix

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    async def set(self, key: str, value: T, ttl_seconds: int) -> None:
        await self._client.set(self._key(key), _serialize(value), ex=ttl_seconds)

    async def get(self, key: str) -> Optional[T]:
        raw = await self._client.get(self._key(key))
        if raw is None:
            return None
        return _deserialize(self._value_type, raw)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def pop(self, key: str) -> Optional[T]:
        # Redis >= 6.2 的 GETDEL:一個指令完成原子的「取出並刪除」,不用另外上鎖。
        raw = await self._client.getdel(self._key(key))
        if raw is None:
            return None
        return _deserialize(self._value_type, raw)
