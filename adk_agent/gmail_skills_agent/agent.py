import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.skills import load_skills_from_dir
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPConnectionParams,
)
from google.adk.tools.skill_toolset import SkillToolset

# Agent Engine 會把 GOOGLE_CLOUD_LOCATION 設成部署區域;新版 Gemini 在 Vertex 上只開放 global 端點。
# 本機 adk web 用 GOOGLE_API_KEY(AI Studio)時不看這個值。
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

AGENT_DIR = Path(__file__).parent

# SYSTEM_PROMPT.md 的 {{current_date}}、{{timezone}} 用這個時區在每次請求時代入。
TIMEZONE = os.environ.get("AGENT_TIMEZONE", "Asia/Taipei")

# 基礎層 skill(見 README「依賴關係」):全文直接接在 system prompt 後面、永遠生效,
# 不放進 SkillToolset,避免模型忘了載入。
ALWAYS_ON_SKILLS = ("gmail-auth", "gmail-safety")

# MCP server exposed over HTTP (streamable-http transport).
mcp_toolset = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://authcode-mcp.gcp.snowmay.com:8000/mcp",
    ),
)

skills = load_skills_from_dir(AGENT_DIR / "skills")
always_on = [s for s in skills if s.name in ALWAYS_ON_SKILLS]
on_demand = [s for s in skills if s.name not in ALWAYS_ON_SKILLS]

# 模型透過 list_skills / load_skill 依任務載入其餘 skill 的全文。
skill_toolset = SkillToolset(skills=on_demand)

SYSTEM_PROMPT = (AGENT_DIR / "SYSTEM_PROMPT.md").read_text(encoding="utf-8")
BASE_RULES = "\n\n".join(
    f"# 基礎規則：{s.name}\n\n{s.instructions}" for s in always_on
)


def build_instruction(_: ReadonlyContext) -> str:
    # instruction 用 function 提供時,ADK 不會把大括號當成 session state 代入,
    # SYSTEM_PROMPT.md 與 skill 裡的 JSON 範例、{{current_date}} 才不會被誤判。
    now = datetime.now(ZoneInfo(TIMEZONE))
    prompt = SYSTEM_PROMPT.replace("{{current_date}}", now.strftime("%Y-%m-%d (%A)"))
    prompt = prompt.replace("{{timezone}}", TIMEZONE)
    return f"{prompt}\n\n{BASE_RULES}"


root_agent = LlmAgent(
    model="gemini-3.5-flash",
    name="gmail_skills_agent",
    instruction=build_instruction,
    tools=[mcp_toolset, skill_toolset],
)
