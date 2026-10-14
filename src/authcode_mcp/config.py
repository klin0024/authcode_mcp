from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_client_id: str
    google_client_secret: str
    oauth_redirect_uri: str
    state_secret: str

    # gmail.readonly:列信/讀信/讀 thread/讀 label/讀附件、列草稿
    # gmail.send:寄信(messages.send)
    # gmail.modify:label 增刪、archive、trash/untrash(唯獨不含永久刪除)
    # gmail.compose:草稿的建立/更新/刪除/寄送
    # userinfo.email:稽核紀錄要識別使用者,用來查 SessionRecord.google_email(見 DESIGN.md 9.2)
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/userinfo.email",
    ]

    # 逗號分隔,決定要動態註冊哪些 Gmail tool。
    gmail_enabled_tools: str = (
        "gmail_list_messages,gmail_get_message,gmail_get_thread,gmail_list_labels,"
        "gmail_get_attachment,gmail_send_message,gmail_modify_labels,gmail_archive_message,"
        "gmail_trash_message,gmail_untrash_message,gmail_list_drafts,gmail_create_draft,"
        "gmail_update_draft,gmail_delete_draft,gmail_send_draft"
    )

    @property
    def gmail_enabled_tools_list(self) -> list[str]:
        return [name.strip() for name in self.gmail_enabled_tools.split(",") if name.strip()]

    # session 在 CacheStore 裡的存活上限;實際 TTL = min(Google access_token expires_in, 這個值)。
    max_session_ttl_seconds: int = 600

    # state 參數的有效期限,超過就視為 CSRF 驗證失敗,需重新走一次授權連結。
    oauth_state_max_age_seconds: int = 300

    # host/port/log_level 不在這裡:交給 FastMCP 自己讀 FASTMCP_HOST/FASTMCP_PORT/FASTMCP_LOG_LEVEL
    # (https://gofastmcp.com/more/settings),mcp.run() 沒傳這幾個參數時會自動用 fastmcp.settings 的值。

    # 對外可被使用者瀏覽器打到的完整 origin,用來組出 /confirm/{action_id} 連結。
    public_base_url: str = "http://localhost:8000"

    # 待確認動作(見 PendingAction)在 CacheStore 裡的存活時間;逾時要請 Agent 重新產生。
    pending_action_ttl_seconds: int = 300

    # 逗號分隔,決定哪些 tool 呼叫時要先建立待確認動作、而不是直接執行。
    # 原則:新增/修改/刪除(含寄送)一律要經過使用者確認,唯讀查詢不用。
    confirm_required_tools: str = (
        "gmail_send_message,gmail_modify_labels,gmail_archive_message,gmail_trash_message,"
        "gmail_untrash_message,gmail_create_draft,gmail_update_draft,gmail_delete_draft,"
        "gmail_send_draft"
    )

    @property
    def confirm_required_tools_set(self) -> set[str]:
        return {name.strip() for name in self.confirm_required_tools.split(",") if name.strip()}

    # 稽核紀錄(AuditRecord)在 AuditStore 裡的存活時間;InMemoryAuditStore 重啟即清空,
    # 這個設定主要是為了將來換成 RedisAuditStore 才有實際的長期保留意義(見 DESIGN.md 9.4)。
    audit_log_ttl_seconds: int = 2592000  # 30 天
