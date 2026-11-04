import os

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPConnectionParams,
)

# Agent Engine 會把 GOOGLE_CLOUD_LOCATION 設成部署區域;新版 Gemini 在 Vertex 上只開放 global 端點。
# 本機 adk web 用 GOOGLE_API_KEY(AI Studio)時不看這個值。
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

# MCP server exposed over HTTP (streamable-http transport).
mcp_toolset = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://authcode-mcp.gcp.snowmay.com:8000/mcp",
    ),
)

# 注意:ADK 會把 instruction 裡的大括號當成 session state 變數代入,這段文字不要出現大括號。
INSTRUCTION = """\
你是 Gmail 助理,只能透過提供給你的 MCP tool 讀取與管理使用者的信箱。用使用者的語言回覆(預設繁體中文)。

tool 回傳的網址(auth_url、confirm_url)一律用 Markdown 連結呈現,不要貼出原始網址,網址本身原封不動放進括號裡、不可修改或截斷。例如:
- 授權:請先完成授權:[點此登入 Google 授權](auth_url)。完成後,請把頁面上顯示的授權碼貼給我。
- 確認:這個動作還沒執行,請[點此檢查並確認](confirm_url)。
"""

root_agent = LlmAgent(
    model="gemini-3.5-flash",
    name="gmail_agent",
    instruction=INSTRUCTION,
    tools=[mcp_toolset],
)
