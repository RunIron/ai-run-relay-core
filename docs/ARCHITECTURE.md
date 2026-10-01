# 架構與限制

## 模組

- `relay/core.py`：SQLite 工作佇列、狀態轉移、共用平台等待、檢查點、程序鎖。
- `relay/codex.py`：以官方 `codex app-server` 子程序及 JSON-RPC 執行；不直接呼叫私人 HTTP 端點。
- `relay/server.py`：本機 HTTP 服務，使用每次啟動隨機 CSRF token。
- `relay/static/index.html`：無 CDN 或前端框架的中文控制台。

## 狀態

`queued → running → queued / succeeded`

額度不足：`running → waiting_quota → running`。

未確認的中斷：`running → needs_review`。檢查後由使用者確認回到 `queued`。失敗也需要確認才重試。取消為終止狀態。

## 檢查點與續跑

每個成功步驟在同一 SQLite transaction 內保存結果與新的 step_index。先保存官方 thread ID，再執行 turn；恢復時以此 ID 接續，既有 thread 沿用上下文，避免每步重送全部成果。明確失效時只新建一次 thread，附上已保存成果；登入或一般 RPC 錯誤不自動新建。

如果 AI 已完成但 Relay 尚未保存就中斷，不能宣稱 exactly-once。重啟時真實工作轉為 needs_review；請先查官方工作階段與外部結果。模型生成的中途輸出不能當作成功檢查點。

## 配額

run 前讀取 `account/rateLimits/read`；控制台數值為最近一次工作查詢的快照，不是持續即時監控。預設只選 codex bucket，不以無關 bucket 的 100% 阻塞執行。未知對應不猜測，若實際請求仍受限才做有限退避。未知資料顯示未知。官方用量窗口與恢復時間優先；缺失時採有限退避。第一版一個 Relay 程序對應一個本機 Codex 登入，無帳號池。

## 權限與整合

第一版只開放唯讀工作，禁止額外權限核准。檔案系統唯讀不代表外部工具沒有副作用：請使用不含私人外部 MCP、plugins、hooks、notify 的 Codex 設定。接頭透過官方 config/read 與 configRequirements/read 檢查設定，發現啟用的這些整合或 hooks.json 檔案時會暫停，亦在子程序停用 Apps。這不會修改使用者的設定檔。接頭會對無法自動處理的權限／互動要求暫停，不會代答。

thread sandbox 使用官方 schema 的 `read-only`，turn policy 使用 `readOnly` 且 `networkAccess:false`。這是官方協定中的兩種不同列舉拼法。尚未完成真實 CLI 端對端測試；不相容或不能檢查設定的 CLI 會停在人工確認。

工作目錄限制不是完整機密隔離；官方沙箱的讀取範圍由 Codex 實作決定。不要指派本身需要更高權限的任務並期待工具繞過限制。

## 目前邊界

只有 Codex 與 mock 接頭；尚無跨主機排程、任務相依圖、費用估算、token 預算、OS 常駐服務安裝、郵件／手機推播。瀏覽器通知需自行開啟且頁面保持開啟。只有內建全域與平台串行執行；不是分散式佇列。

第一版有 15 分鐘每次執行 timeout、6 次單步自動嘗試、預設 7 天等待期限；平台明示更晚重置時延長至重置後一小時。資料庫不會自動刪除歷史產出；長期使用請備份與管理容量。

## 摘要與詳情 API

`GET /api/state?page=0&page_size=50&since=revision` 回傳摘要變更、該頁 job_order、總數與狀態統計。初次或換頁不帶 since。若 job_order 出現本機未快取且沒有摘要的 ID（新增資料使頁面成員改變），再補抓該頁一次不帶 since 的快照。`GET /api/jobs/{id}` 才取得完整步驟與成果。

SQLite 保存 summary/status/revision 投影，輪詢與排程掃描不解析所有已完成工作的 outputs。前端保留 keyed DOM 卡片及成果 pre 節點；只有文字真的變動才修改 textContent。

`POST /api/workspace` 需相同 CSRF 驗證；切換預設目錄只影響新工作。全量匯出仍使用 `/api/export`，由使用者主動執行。
