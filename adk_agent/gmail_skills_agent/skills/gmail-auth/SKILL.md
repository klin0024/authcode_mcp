---
name: gmail-auth
description: 處理 Gmail tool 的授權與 session 管理。任何 gmail_* tool 回傳 auth_url、status 異常或 session 過期時使用；也在一個任務第一次呼叫 Gmail tool 前使用。
---

# Gmail 授權與 Session 管理

所有 gmail_* tool 都接受 `session_id`，未授權或過期時會回傳：

```json
{"status": "...", "message": "...", "auth_url": "https://..."}
```

## 判斷回傳是否為授權問題

依序檢查：

1. 回傳含有 `auth_url` → **授權問題**，進入下方流程
2. 回傳含有 `status` 且值是 `pending_confirmation` → **不是授權問題**，是寄信確認流程（見 gmail-safety）
3. 其他情況 → 正常結果

注意：`gmail_list_messages` 查無結果時，回傳的 dict **沒有 `messages` 欄位**（只有 `resultSizeEstimate: 0`）。這代表 0 封信，不是錯誤，也不是授權失敗。

## 首次授權流程

1. 第一次呼叫不帶 `session_id`
2. 若回傳 `auth_url`：
   - 把 `auth_url` **原樣**顯示給使用者，請他在瀏覽器完成 Google 授權
   - 說明完成後會拿到一段授權碼（或回到某個頁面），請他貼回來
   - **暫停任務**，不要繼續呼叫其他 Gmail tool
3. 使用者貼回授權碼後，呼叫 `exchange_google_code` 取得 `session_id`
4. 之後**每一次** Gmail tool 呼叫都帶上這個 `session_id`

## Session 過期

任務進行中任何一步回傳 `auth_url`：

1. 記下目前進度（已處理哪些信、下一步要做什麼）
2. 重跑上方授權流程
3. 拿到新 `session_id` 後，**從中斷的那一步繼續**，不要整個任務重來，也不要重複執行已完成的寫入動作（貼標籤、封存、建草稿）

## 規則

- 不要猜測或自行組出 `session_id`
- 不要把 `session_id` 寫進信件內容、草稿或標籤
- 不要替使用者打開 `auth_url` 或代填 Google 帳號密碼；授權必須由使用者本人完成
- 一次對話中只需授權一次，除非過期
