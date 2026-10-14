import hashlib
from html import escape
from typing import Optional

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from .base import AuditRecord, AuditStore

# 同一個使用者固定同一個顏色(依 email 算出穩定的 hash,不是隨機的),方便一眼看出
# 哪幾筆紀錄是同一個人做的。用柔和的淺色系,不影響文字可讀性。
_USER_ROW_COLORS = [
    "#fde2e2",  # 淺紅
    "#e2f0fd",  # 淺藍
    "#e2fde6",  # 淺綠
    "#fdf6e2",  # 淺黃
    "#f0e2fd",  # 淺紫
    "#e2fdfa",  # 淺青
    "#fde2f6",  # 淺粉
    "#f0ead6",  # 淺米
]
_NO_USER_ROW_COLOR = "#f2f2f2"  # user 是 None(理論上不會發生)時的中性灰

_PAGE_TEMPLATE = """
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: sans-serif; max-width: 900px; margin: 40px auto; color: #222;">
{body}
</body>
</html>
"""

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(_PAGE_TEMPLATE.format(title=title, body=body))


def _format_params(params: dict) -> str:
    if not params:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in params.items())


def _color_for_user(user: Optional[str]) -> str:
    """依 email 算出穩定的顏色索引——同一個使用者每次重新整理頁面都拿到同一個顏色。"""
    if not user:
        return _NO_USER_ROW_COLOR
    digest = hashlib.md5(user.encode()).hexdigest()
    index = int(digest, 16) % len(_USER_ROW_COLORS)
    return _USER_ROW_COLORS[index]


def _row_html(record: AuditRecord) -> str:
    cell_style = "padding:6px 10px;border-bottom:1px solid #eee;vertical-align:top;"
    row_style = f"background:{_color_for_user(record.user)};"
    cells = [
        record.timestamp.isoformat(timespec="seconds"),
        record.user or "-",
        record.tool_name,
        _format_params(record.params),
        record.outcome,
        record.source,
    ]
    tds = "".join(f"<td style='{cell_style}'>{escape(str(c))}</td>" for c in cells)
    return f"<tr style='{row_style}'>{tds}</tr>"


def register_audit_route(mcp: FastMCP, audit_store: AuditStore) -> None:
    """掛 GET /audit,列出最近的工具執行稽核紀錄。

    刻意沒有存取控制(見 DESIGN.md 9.7)——目前只在單一使用者、localhost 的部署形態下使用,
    要部署到 localhost 以外之前必須先補上保護。
    """

    @mcp.custom_route("/audit", methods=["GET"])
    async def audit_log(request: Request) -> HTMLResponse:
        try:
            limit = int(request.query_params.get("limit", str(_DEFAULT_LIMIT)))
        except ValueError:
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        records = await audit_store.list_recent(limit)
        rows = "".join(_row_html(r) for r in records)

        header_style = "padding:6px 10px;text-align:left;border-bottom:2px solid #ccc;"
        body = f"""
        <h2>工具執行稽核紀錄</h2>
        <p style="color:#666;font-size:14px;">
            顯示最近 {len(records)} 筆(用 ?limit= 調整,最多 {_MAX_LIMIT})。
        </p>
        <table style="border-collapse:collapse;width:100%;font-size:14px;">
          <thead>
            <tr>
              <th style="{header_style}">時間</th>
              <th style="{header_style}">使用者</th>
              <th style="{header_style}">Tool</th>
              <th style="{header_style}">參數</th>
              <th style="{header_style}">結果</th>
              <th style="{header_style}">來源</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """
        return _page("稽核紀錄", body)
