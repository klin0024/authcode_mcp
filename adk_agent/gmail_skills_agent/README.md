# Gmail Agent Skills

| Skill | 用途 | 何時載入 |
|---|---|---|
| gmail-auth | 授權、session 過期處理 | 每個任務開始 |
| gmail-safety | 寄信 / 刪信確認、防指令注入 | 每個任務開始 |
| gmail-search | 搜尋語法、讀信、解析內文 | 需要找信或讀信時 |
| inbox-triage | 收件匣分類與整理 | 「整理收件匣」 |
| thread-summary | 郵件串摘要 | 「這串在講什麼」 |
| reply-drafting | 擬回覆與新信 | 「幫我回這封」 |
| daily-digest | 每日 / 每週摘要 | 「今天有什麼信」、排程 |
| follow-up-tracker | 追蹤未回覆 | 「誰還沒回我」 |
| attachment-handling | 附件下載與讀取 | 「找發票」「看附件」 |
| label-organization | 標籤管理 | 「貼標籤」「歸檔」 |
| newsletter-cleanup | 電子報清理 | 「清廣告信」 |

## 檔案

- `SYSTEM_PROMPT.md`：agent 的 system prompt。`{{current_date}}`、`{{timezone}}` 由 `agent.py` 在每次請求時代入（時區預設 `Asia/Taipei`，可用環境變數 `AGENT_TIMEZONE` 覆寫）
- `skills/<name>/SKILL.md`：各 skill 全文，`agent.py` 用 ADK 的 `load_skills_from_dir` 載入
- `agent.py`：
  - gmail-auth、gmail-safety 的全文直接接在 system prompt 後面，永遠生效
  - 其餘 9 個交給 `SkillToolset`，模型透過 `list_skills` / `load_skill` 依任務載入
  - `instruction` 用 function 提供，ADK 才不會把 prompt 裡的大括號（`{{current_date}}`、JSON 範例）當成 session state 變數

## 依賴關係

- gmail-auth、gmail-safety 是基礎層，建議放進 agent 的 system prompt 或設為永遠載入
- 其他 skill 都會用到 gmail-search
- reply-drafting、follow-up-tracker 的寄信步驟依 gmail-safety

## 撰寫時的假設（請依實際 tool 調整）

已確認的介面：`gmail_list_messages`（有 `query`、無分頁）、`gmail_get_message`（回傳 Gmail API 原始格式）、`gmail_send_message`（純文字、無 thread 參數、預設回傳 `confirm_url`）。

未確認、skill 中以 Gmail API 慣例撰寫的：

- `gmail_create_draft` 是否支援 `threadId` 與 `In-Reply-To` 標頭 → 影響 reply-drafting 能否接在同一串
- `gmail_modify_labels` 參數名稱（推測為 add / remove label IDs）
- `gmail_get_attachment` 回傳是否為 base64url 的 `data`
- `gmail_send_draft` 是否也在 `CONFIRM_REQUIRED_TOOLS` 名單中；若是，gmail-safety 的草稿流程同樣要顯示 `confirm_url`
