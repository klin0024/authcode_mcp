import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)


async def main():
    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a helpful assistant. You have access to tools exposed by "
            "an MCP server. Use them whenever they help answer the user's "
            "request, and explain what you did."
        ),
        mcp_servers={
            # MCP server exposed over HTTP (streamable-http transport).
            "authcode_mcp": {
                "type": "http",
                "url": "http://localhost:8000/mcp",
            }
        },
        allowed_tools=["mcp__authcode_mcp__*"],
    )

    async with ClaudeSDKClient(options=options) as client:
        print("輸入 exit / quit 離開")
        while True:
            user_input = input("\n你: ").strip()
            if user_input.lower() in ("exit", "quit"):
                break
            if not user_input:
                continue

            await client.query(user_input)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"Claude: {block.text}", end="")
                elif isinstance(message, ResultMessage):
                    print()  # 換行收尾


asyncio.run(main())