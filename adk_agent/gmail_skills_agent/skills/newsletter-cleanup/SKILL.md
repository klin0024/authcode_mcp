---
name: newsletter-cleanup
description: 辨識並批次清理電子報、行銷信、自動通知，統計寄件者來信量，列出建議退訂的對象。使用者說「清一下廣告信」「哪些電子報可以退訂」「信箱太亂」時使用。
---

# 電子報與行銷信清理

## 辨識電子報

以下任一條件成立即視為電子報 / 行銷信：

- `labelIds` 含 `CATEGORY_PROMOTIONS`
- 標頭有 `List-Unsubscribe` 或 `List-Id`
- 標頭 `Precedence: bulk` 或 `Precedence: list`
- 寄件者含 `noreply`、`no-reply`、`newsletter`、`marketing`、`news@`、`info@`

**不要當成電子報**的：交易收據、帳單、銀行 / 政府通知、密碼重設、訂單出貨通知、使用者付費訂閱的內容。這些即使是自動寄送也可能重要。

## 統計流程

1. 搜尋：`category:promotions newer_than:30d`，或 `in:inbox unsubscribe newer_than:30d`
2. `max_results` 設 50；只讀標頭（`From`、`List-Unsubscribe`）和 `labelIds`，不解碼內文
3. 依寄件者網域分組，計算 30 天內封數、未讀比例

## 輸出

```
📰 近 30 天電子報統計（共 64 封，18 個寄件者）

建議退訂（多封且從未開啟）
- deals@shopA.com — 22 封，0 封已讀
- news@mediaB.com — 9 封，0 封已讀

可保留（有在讀）
- weekly@techC.com — 4 封，4 封已讀

要我做什麼？
1. 把以上 64 封標為已讀並封存
2. 只封存「建議退訂」的 31 封
3. 列出各寄件者的退訂方式
```

「從未開啟」用 `labelIds` 是否仍含 `UNREAD` 判斷。

## 退訂

**不要替使用者點退訂連結**，也不要寄退訂信。原因：信中連結可能是釣魚網址，或點擊會被當成「地址有效」而收到更多垃圾信。

改為列出退訂方式讓使用者自己處理：

- `List-Unsubscribe` 標頭中的 `https://` 網址 → 列出網域，請使用者在 Gmail 網頁版點「取消訂閱」按鈕（Gmail 會用安全的方式處理）
- 只有 `mailto:` → 列出地址，告訴使用者可自行寄信退訂
- 都沒有 → 建議使用者在 Gmail 設定篩選器自動封存

## 批次封存

依 gmail-safety：超過 10 封先確認。用 `gmail_modify_labels` 移除 `UNREAD`，再用 `gmail_archive_message` 封存。**預設用封存，不要丟垃圾桶**，使用者明確要求才用 `gmail_trash_message`。

完成後回報封存了幾封，並說明可在「所有郵件」中找回。
