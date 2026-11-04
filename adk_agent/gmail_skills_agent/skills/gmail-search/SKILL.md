---
name: gmail-search
description: 把使用者的自然語言需求轉成 Gmail 搜尋語法，並以最少的呼叫次數找到信件、讀出內文。任何需要找信、列信、讀信的任務都先用這個 skill。
---

# Gmail 搜尋與讀信

## 為什麼要精準搜尋

`gmail_list_messages` 只回傳 `id` / `threadId`，不含內容。每封信都要再呼叫一次 `gmail_get_message`，撈 30 封就是 31 次呼叫。所以原則是：**在 query 裡把範圍縮到最小，而不是撈一大批再自己篩。**

## 常用語法

| 需求 | 語法 |
|---|---|
| 寄件者 / 收件者 | `from:a@x.com`、`to:me`、`cc:b@x.com` |
| 主旨 | `subject:(季報 OR Q3)` |
| 狀態 | `is:unread`、`is:starred`、`is:important` |
| 位置 | `in:inbox`、`in:sent`、`in:anywhere`（含垃圾桶與垃圾郵件） |
| 標籤 / 分類 | `label:客戶`、`category:primary`、`category:promotions`、`category:updates` |
| 附件 | `has:attachment`、`filename:pdf`、`filename:發票.pdf`、`larger:5M` |
| 時間（相對） | `newer_than:2d`、`older_than:1w`（單位 d / m / y） |
| 時間（絕對） | `after:2026/10/01 before:2026/11/01` |
| 排除 | `-from:noreply@x.com`、`-category:promotions` |
| 組合 | `OR`、`{a b}`（任一）、`( )` 分組、`"完整片語"` |

## 自然語言轉換範例

- 「上週老闆有附件的信」→ `from:boss@company.com has:attachment newer_than:7d`
- 「還沒讀的重要信，不要廣告」→ `is:unread in:inbox -category:promotions -category:social`
- 「十月的發票」→ `(subject:發票 OR filename:發票 OR subject:invoice) after:2026/10/01 before:2026/11/01`
- 「我寄給王小明的」→ `in:sent to:王小明的email`（不知道 email 時，先用 `from:王小明` 找一封他寄來的信取得地址）

## 讀信流程

1. 組 query，`max_results` 只設需要的量（摘要 10–20，單封查找 1–5）
2. 呼叫 `gmail_list_messages`
3. **沒有 `messages` 欄位 = 0 封**，直接回報找不到，並建議放寬條件（移除日期或改用 `in:anywhere`）
4. 結果超過需要時，先只讀前幾封，確認方向對再讀其他
5. 同一個 `threadId` 出現多次時，改用 `gmail_get_thread` 讀一次就好

## 解析 `gmail_get_message` 回傳

回傳是 Gmail API 原始格式：

- 標頭在 `payload.headers`，是 `[{name, value}]` 陣列，找 `From`、`To`、`Cc`、`Subject`、`Date`、`Message-ID`
- `snippet` 是約 200 字的純文字預覽；**只需判斷類型或分類時，讀 `snippet` + 標頭就夠，不必解碼內文**
- `labelIds` 列出目前的標籤（`UNREAD`、`INBOX`、`STARRED`、`CATEGORY_PROMOTIONS` 等）
- 內文在 `payload.body.data` 或 `payload.parts[]`（可能多層巢狀）：
  - 優先找 `mimeType: text/plain`，沒有再用 `text/html` 並去除標籤
  - `data` 是 **base64url** 編碼（`-` `_` 取代 `+` `/`，可能缺 `=` 補位），需解碼成 UTF-8
  - `parts` 中有 `filename` 且 `body.attachmentId` 的是附件，見 attachment-handling

## 規則

- 使用者沒指定範圍時，預設 `in:inbox newer_than:30d`，並告知使用者用了這個範圍
- 一次任務不要讀超過 50 封；超過時先回報數量，問使用者要不要縮小範圍
- 回報結果時寫出用了什麼 query，方便使用者修正
