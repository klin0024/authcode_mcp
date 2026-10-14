import logging
from html import escape
from typing import Awaitable, Callable, Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from ..audit.base import AuditStore, record_audit
from ..cache.base import CacheStore, PendingAction

logger = logging.getLogger(__name__)

_PAGE_TEMPLATE = """
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 60px auto; color: #222;">
{body}
</body>
</html>
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE_TEMPLATE.format(title=title, body=body), status_code=status_code)


# tool_name / 參數名稱 -> 中文顯示文字。找不到對應的就直接顯示原字串(forward-compatible)。
_TOOL_NAME_LABELS = {
    "gmail_send_message": "寄送信件",
    "gmail_modify_labels": "修改信件 Label",
    "gmail_archive_message": "封存信件",
    "gmail_trash_message": "移入垃圾桶",
    "gmail_untrash_message": "從垃圾桶還原",
    "gmail_create_draft": "建立草稿",
    "gmail_update_draft": "更新草稿",
    "gmail_delete_draft": "刪除草稿",
    "gmail_send_draft": "寄出草稿",
}

_PARAM_LABELS = {
    "to": "收件人",
    "subject": "主旨",
    "body": "內容",
    "message_id": "信件 ID",
    "thread_id": "對話串 ID",
    "draft_id": "草稿 ID",
    "attachment_id": "附件 ID",
    "add_label_ids": "新增的 Label",
    "remove_label_ids": "移除的 Label",
}


# 這些欄位是 Gmail 資源的識別碼——是「這次要確認的動作是哪一個」的一部分,
# 不是內容,所以鎖定不給編輯(反灰 + disabled),不是靠使用者自己填對。
# "to" 不在這裡:收件人算內容,使用者應該可以自己改(例如改寄給別人、修正打錯的地址)。
_LOCKED_KEYS = {"message_id", "draft_id", "thread_id", "attachment_id"}

_FIELD_STYLE = (
    "width:100%;box-sizing:border-box;padding:6px;border:1px solid #ccc;border-radius:4px;"
    "font-family:inherit;font-size:inherit;"
)
_FIELD_STYLE_LOCKED = _FIELD_STYLE + "background:#eee;color:#888;cursor:not-allowed;"


def _list_to_field_value(value: list) -> str:
    return ", ".join(str(v) for v in value)


def _field_html(key: str, value: object) -> str:
    """依參數型別畫出欄位:list 用逗號分隔的文字輸入,body 用多行 textarea,其他用單行輸入。

    _LOCKED_KEYS 裡的欄位加上 disabled,瀏覽器會反灰、不給編輯,送出表單時也不會帶這個
    欄位——_apply_form_edits 對「表單沒有這個 key」的處理本來就是直接沿用原始值,兩邊剛好接得上。
    """
    name = escape(key)
    locked = key in _LOCKED_KEYS
    style = _FIELD_STYLE_LOCKED if locked else _FIELD_STYLE
    disabled_attr = " disabled" if locked else ""

    if isinstance(value, (list, tuple)):
        raw = escape(_list_to_field_value(list(value)))
        return f"<input type='text' name='{name}' value='{raw}' style='{style}'{disabled_attr}>"
    if key == "body":
        raw = escape(str(value))
        return f"<textarea name='{name}' rows='6' style='{style}'{disabled_attr}>{raw}</textarea>"
    raw = escape(str(value))
    return f"<input type='text' name='{name}' value='{raw}' style='{style}'{disabled_attr}>"


def _preview_form_fields(params: dict) -> str:
    rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0;color:#666;vertical-align:top;white-space:nowrap;'>"
        f"{escape(_PARAM_LABELS.get(k, k))}</td>"
        f"<td style='padding:6px 0;width:100%;'>{_field_html(k, v)}</td></tr>"
        for k, v in params.items()
    )
    return f"<table style='border-collapse:collapse;width:100%;'>{rows}</table>"


def _apply_form_edits(original_params: dict, form: dict) -> dict:
    """用使用者在確認頁上送出的表單值覆蓋原本的參數,型別(list vs str)沿用原參數的型別。"""
    edited: dict = {}
    for key, original_value in original_params.items():
        raw = form.get(key)
        if raw is None:
            edited[key] = original_value
        elif isinstance(original_value, (list, tuple)):
            edited[key] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            edited[key] = raw
    return edited


# 送出時不可以是空字串的欄位:_LOCKED_KEYS(反灰、擋的是繞過表單的異常請求)
# 再加上 "to"(可以編輯,但清空了 Gmail 一定會拒絕,所以還是要驗證)。
_REQUIRED_NON_EMPTY_KEYS = _LOCKED_KEYS | {"to"}


def _validate_params(params: dict) -> Optional[str]:
    """回傳錯誤訊息(驗證失敗時)或 None(通過)。

    _LOCKED_KEYS 那幾個在表單上是 disabled,使用者透過瀏覽器正常操作不可能把它們清空,
    這裡留著是防禦性檢查,擋的是有人繞過表單直接發 POST(例如手動 curl)的情況;
    "to" 則是使用者可以編輯、但清空了一定會執行失敗,所以正常操作也可能觸發這個檢查。
    """
    for key in _REQUIRED_NON_EMPTY_KEYS:
        value = params.get(key)
        if isinstance(value, str) and not value.strip():
            label = _PARAM_LABELS.get(key, key)
            return f"「{label}」不可留空。"
    return None


def register_confirm_route(
    mcp: FastMCP,
    pending_action_store: CacheStore[PendingAction],
    audit_store: AuditStore,
    action_executors: dict[str, Callable[[str, dict], Awaitable[dict]]],
) -> None:
    @mcp.custom_route("/confirm/{action_id}", methods=["GET", "POST"])
    async def confirm_action(request: Request) -> HTMLResponse:
        action_id = request.path_params["action_id"]

        if request.method == "GET":
            # 只讀,不消費——避免連結預抓/掃毒機器人一開連結就把動作執行掉(見 DESIGN.md 8.4)。
            pending = await pending_action_store.get(action_id)
            if pending is None:
                return _page(
                    "連結已失效",
                    "<h2>連結已失效</h2><p>這個確認連結不存在、已過期,或已經被使用過。"
                    "請回去請 Agent 重新產生一次。</p>",
                    status_code=404,
                )

            tool_label = _TOOL_NAME_LABELS.get(pending.tool_name, pending.tool_name)
            body = f"""
            <h2>確認執行:{escape(tool_label)}</h2>
            <p style="color:#666;font-size:14px;">可以直接修改下面的內容,送出時會用你修改後的版本執行(反灰的欄位是識別碼,不能改)。</p>
            <form method="post">
              {_preview_form_fields(pending.params)}
              <div style="margin-top:16px;display:flex;gap:8px;">
                <button type="submit" name="decision" value="confirm"
                        style="padding:8px 16px;border-radius:6px;
                               border:1px solid #ccc;background:#fff;cursor:pointer;">
                  確認送出
                </button>
                <button type="submit" name="decision" value="cancel"
                        style="padding:8px 16px;border-radius:6px;
                               border:1px solid #ccc;background:transparent;color:#888;cursor:pointer;">
                  取消
                </button>
              </div>
            </form>
            """
            return _page("請確認", body)

        form = await request.form()
        decision = form.get("decision", "confirm")  # 沒帶這個欄位理論上不會發生,保守當作要確認

        if decision == "cancel":
            # 取消不需要看欄位合不合法,使用者就算清空必填欄位也應該能取消。
            # 一樣用 pop() 原子取出並刪除,道理跟確認一樣:避免手滑點兩下造成競態(見 8.4)。
            cancelled = await pending_action_store.pop(action_id)
            if cancelled is None:
                return _page(
                    "連結已失效",
                    "<h2>連結已失效</h2><p>這個動作已經被執行過或取消過,或連結已過期。</p>",
                    status_code=409,
                )
            await record_audit(
                audit_store, user=cancelled.user, session_id=cancelled.session_id,
                tool_name=cancelled.tool_name, params=cancelled.params, outcome="cancelled", source="confirm",
                action_id=cancelled.action_id,
            )
            return _page("已取消", "<h2>已取消</h2><p>這個動作不會被執行,可以關閉這個頁面了。</p>")

        # decision == "confirm":先用 get()(只讀)驗證表單值合不合法,合法才 pop() 消費。
        # 這樣使用者清空必填欄位送出時,連結不會被白白浪費掉——可以回上一頁修正再送一次。
        peeked = await pending_action_store.get(action_id)
        if peeked is None:
            return _page(
                "連結已失效",
                "<h2>連結已失效</h2><p>這個動作已經被執行過,或連結已過期。</p>",
                status_code=409,
            )

        final_params = _apply_form_edits(peeked.params, form)

        error = _validate_params(final_params)
        if error:
            return _page(
                "欄位有誤",
                f"<h2>欄位有誤</h2><p>{escape(error)}</p><p>請返回上一頁修正後再送出,連結還沒失效。</p>",
                status_code=400,
            )

        # 驗證通過才真的原子取出並刪除,確保同一個連結只能真的執行一次(見 DESIGN.md 8.4)。
        pending = await pending_action_store.pop(action_id)
        if pending is None:
            return _page(
                "連結已失效",
                "<h2>連結已失效</h2><p>這個動作已經被執行過,或連結已過期。</p>",
                status_code=409,
            )

        executor = action_executors.get(pending.tool_name)
        if executor is None:
            return _page(
                "設定錯誤",
                f"<h2>設定錯誤</h2><p>找不到 {escape(pending.tool_name)} 對應的執行邏輯。</p>",
                status_code=500,
            )

        try:
            await executor(pending.access_token, final_params)
        except Exception as exc:
            logger.exception(
                "confirm 執行失敗: action_id=%s tool_name=%s params=%s",
                action_id, pending.tool_name, final_params,
            )
            await record_audit(
                audit_store, user=pending.user, session_id=pending.session_id,
                tool_name=pending.tool_name, params=final_params, outcome="failed", source="confirm",
                action_id=pending.action_id,
            )
            return _page("執行失敗", f"<h2>執行失敗</h2><p>{escape(str(exc))}</p>", status_code=502)

        await record_audit(
            audit_store, user=pending.user, session_id=pending.session_id,
            tool_name=pending.tool_name, params=final_params, outcome="success", source="confirm",
            action_id=pending.action_id,
        )
        return _page("已完成", "<h2>已送出</h2><p>動作已經執行完成,可以關閉這個頁面了。</p>")
