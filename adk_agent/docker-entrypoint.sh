#!/bin/sh
set -e

# agent.json 裡的 url 是給 A2A client 連的對外網址,ADK 不會自動改寫。
# 有給 A2A_BASE_URL(例如 https://xxx.run.app)就改成 <A2A_BASE_URL>/a2a/<agent 資料夾名稱>。
if [ -n "$A2A_BASE_URL" ]; then
  python - <<'EOF'
import json
import os
from pathlib import Path

base = os.environ["A2A_BASE_URL"].rstrip("/")
for card_path in Path("/app/agents").glob("*/agent.json"):
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["url"] = f"{base}/a2a/{card_path.parent.name}"
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"A2A card url -> {card['url']}")
EOF
fi

exec "$@"
