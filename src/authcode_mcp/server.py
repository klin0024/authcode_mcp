from fastmcp import FastMCP

from .audit.base import AuditStore
from .audit.memory import InMemoryAuditStore
from .audit.route import register_audit_route
from .audit.tools import register_action_status_tool
from .auth.callback import register_oauth_callback
from .auth.tools import register_auth_tools
from .cache.base import CacheStore, PendingAction, SessionRecord
from .cache.memory import InMemoryCacheStore
from .config import Settings
from .gmail.confirm import register_confirm_route
from .gmail.tools import build_action_executors, register_gmail_tools


def build_server(
    settings: Settings,
    session_store: CacheStore[SessionRecord],
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
) -> FastMCP:
    mcp = FastMCP(name="authcode-mcp")

    register_oauth_callback(mcp, settings)
    register_auth_tools(mcp, session_store, settings)
    register_gmail_tools(mcp, session_store, pending_action_store, audit_store, settings)
    register_confirm_route(mcp, pending_action_store, audit_store, build_action_executors())
    register_audit_route(mcp, audit_store)
    register_action_status_tool(mcp, pending_action_store, audit_store, settings)

    return mcp


settings = Settings()
session_store: CacheStore[SessionRecord] = InMemoryCacheStore()
pending_action_store: CacheStore[PendingAction] = InMemoryCacheStore()
audit_store: AuditStore = InMemoryAuditStore(ttl_seconds=settings.audit_log_ttl_seconds)
mcp = build_server(settings, session_store, pending_action_store, audit_store)


def main() -> None:
    # transport 寫死 http,不讀 FASTMCP_TRANSPORT(它預設 stdio,stdio 不會暴露 /oauth/callback、
    # /confirm、/audit 這些 route);host/port/log_level 交給 FastMCP 從 FASTMCP_HOST/PORT/LOG_LEVEL 讀。
    mcp.run(transport="http")


if __name__ == "__main__":
    main()
