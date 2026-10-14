from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPConnectionParams,
)

# MCP server exposed over HTTP (streamable-http transport).
mcp_toolset = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://localhost:8000/mcp",
    ),
)

root_agent = LlmAgent(
    model="gemini-3.5-flash-lite",
    name="gmail_agent",
    instruction=(
        "You are a helpful assistant. You have access to tools exposed by "
        "an MCP server. Use them whenever they help answer the user's "
        "request, and explain what you did."
    ),
    tools=[mcp_toolset],
)
