import json
from html import escape

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from ..config import Settings
from . import google_oauth

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


def register_oauth_callback(mcp: FastMCP, settings: Settings) -> None:
    @mcp.custom_route("/oauth/callback", methods=["GET"])
    async def oauth_callback(request: Request) -> HTMLResponse:
        error = request.query_params.get("error")
        if error:
            return _page(
                "授權失敗",
                f"<h2>授權失敗</h2><p>{escape(error)}</p>",
                status_code=400,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return _page(
                "缺少參數",
                "<h2>缺少 code 或 state</h2><p>請重新從授權連結開始。</p>",
                status_code=400,
            )

        if not google_oauth.verify_state(state, settings.state_secret, settings.oauth_state_max_age_seconds):
            return _page(
                "驗證失敗",
                "<h2>state 驗證失敗</h2><p>連結可能已過期,請請 Agent 重新提供授權連結。</p>",
                status_code=400,
            )

        safe_code = escape(code)
        # json.dumps 給我們一個合法的 JS 字串字面值;額外把 "</" 轉義避免提前結束 <script> 標籤。
        code_js = json.dumps(code).replace("</", "<\\/")
        body = f"""
        <h2>授權成功</h2>
        <p>請複製以下授權碼,貼回給 Agent:</p>
        <pre id="auth-code" style="padding:12px;background:#f4f4f4;border-radius:6px;
             word-break:break-all;user-select:all;">{safe_code}</pre>
        <button id="copy-btn" onclick="copyAuthCode()"
                style="padding:8px 16px;border-radius:6px;border:1px solid #ccc;
                       background:#fff;cursor:pointer;">複製</button>
        <script>
        function showCopyResult(text) {{
          var btn = document.getElementById('copy-btn');
          btn.textContent = text;
          setTimeout(function () {{ btn.textContent = '複製'; }}, 1500);
        }}

        // navigator.clipboard 只在 secure context(HTTPS 或 localhost)存在;
        // 用 http + 網域名稱開這頁時它是 undefined,改用 execCommand('copy') 當備案。
        function fallbackCopy(code) {{
          var textarea = document.createElement('textarea');
          textarea.value = code;
          textarea.setAttribute('readonly', '');
          textarea.style.position = 'fixed';
          textarea.style.opacity = '0';
          document.body.appendChild(textarea);
          textarea.select();
          var ok = false;
          try {{ ok = document.execCommand('copy'); }} catch (e) {{}}
          document.body.removeChild(textarea);
          if (ok) {{
            showCopyResult('已複製');
          }} else {{
            // 連備案都失敗:選取授權碼讓使用者自己按 Ctrl+C
            window.getSelection().selectAllChildren(document.getElementById('auth-code'));
            showCopyResult('請按 Ctrl+C 複製');
          }}
        }}

        function copyAuthCode() {{
          var code = {code_js};
          if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(code).then(
              function () {{ showCopyResult('已複製'); }},
              function () {{ fallbackCopy(code); }}
            );
          }} else {{
            fallbackCopy(code);
          }}
        }}
        </script>
        """
        return _page("授權成功", body)
