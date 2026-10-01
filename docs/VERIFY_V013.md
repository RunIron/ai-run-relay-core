# v0.1.3 驗證方式

本版以使用者上傳的 v0.1.2.zip 為基底。原封裝內版本號仍為 0.1.1，已統一改成 0.1.3。

## 已執行的自動驗證

```bash
python3 -m unittest discover -s tests -v
```

Windows PowerShell 將 `python3` 改為 `py -3`。假 CLI 測試使用 POSIX 腳本；Windows 全套測試請在 WSL 執行。產品本身的 Windows 啟動與程序終止仍須 Windows 實機驗證。

| 問題 | 修正 | 自動驗證 |
|---|---|---|
| 輪詢帶回所有成果 | SQLite 摘要投影、每頁 50 筆、revision 增量；詳情另取 | 200 筆×16 KiB 成果，輪詢不含 outputs／steps／partial_output，摘要回應小於 100 KB |
| 前端整頁重建 | 以工作 ID 保留節點，只更新變動值，展開才讀成果 | 已提供真瀏覽器測試腳本；本環境沒有 Chromium，未完成實際 DOM 驗證 |
| 啟動時分析 Relay 原始碼 | 初始工作目錄固定為使用者家目錄的 AI-Run-Relay-workspace；UI 可切換並保存 | mock cwd 不可使用、預設路徑、持久化、明確覆寫、舊工作路徑不被更動 |
| 取消與逾時直接終止 | 先 turn/interrupt，獨立等待最多 2 秒的停止事件，再清理程序 | 假 CLI 檢查 RPC 順序、停止事件、延遲 turn/start 回覆競態 |
| 舊 session 失效反覆失敗 | 只有明確不存在／過期錯誤才建立新 thread 一次，加入已保存成果 | 新 thread ID 保存、檢查點附入；登入失敗不得觸發新建 |
| commentary 混入成果 | 優先最後一則完成的 final_answer；舊協定取最後無 phase 的完成訊息 | commentary/delta 不算 final；沒有成果轉 needs_review |
| 無關額度造成整體等待 | 只選本接頭對應的 codex limit_id | 其他 bucket 100% 不阻塞；相關主／次窗口仍須等恢復；未知對應不猜測 |
| 公開封裝洩漏核心 | 明確公開檔案允許清單 | 放入額外核心檔仍不會進公開包 |

分頁另覆蓋：停在第二頁時新增第一頁工作，頁面成員可能改變而 revision 沒變；前端發現未知 ID，會補抓一次該頁完整摘要。

## 真瀏覽器自動測試（待執行）

有 Node.js、Playwright 與 Chromium 的開發機可執行：

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser_smoke.cjs
```

這個測試使用攔截 HTTP 的假資料，不會呼叫 AI 或修改帳號。它實際檢查：未展開不載入成果、3 次輪詢後 DOM 節點／文字選取／成果捲動位置保留、第二頁新增資料補齊、390px 手機寬度無橫向溢出。

本次只完成該腳本與前端 JS 語法檢查，不能寫成瀏覽器測試已通過。

## 真實 Codex 月租驗證（待在你的電腦執行）

1. 記錄 `codex --version`、作業系統與 Relay 版本；使用自己的官方 ChatGPT 登入，不提供 Token 給別人。
2. 建立獨立測試資料夾，放入 `sample.txt`（內容可為不敏感的專案筆記）。先在控制台改選這個資料夾。
3. 新增兩步唯讀工作：「讀取 sample.txt，列三項重點」「根據上一步寫一段摘要」。確認內容不是 Relay 原始碼，兩步成果保存、沒有過程訊息。
4. 執行另一個較長的唯讀工作並按取消。檢查事件紀錄的「工作階段停止確認」。這與僅收到 interrupt RPC 成功不同；若逾時則確認顯示停止未確認，不能宣稱乾淨停止。
5. 逾時可在測試 Python 程式中使用 `CodexAdapter(timeout=短秒數)`；請在獨立測試資料與資料庫進行，不改主要工作。
6. session 失效以假 CLI 測試為主要驗證，不要刪除真實帳號的重要工作階段。若自然遇到失效，確認新 ID、恢復事件與原成果仍在；其它錯誤仍應暫停。
7. 遇到真實額度不足時，核對官方顯示與 Relay 的 bucket／恢復時間，觀察下一次重置後接續。不要為測試刻意消耗大量額度。沒有足夠證據時保留「尚未真實驗證」。

## 升級

先停止舊版服務，備份 `~/.ai-run-relay/`（或你的 --data-dir）再啟動新版。SQLite 會加入摘要與 revision 欄位；遷移測試確認成果與原始排序保留。回退舊版請使用備份，不要讓新舊服務同時開啟同一個資料目錄。

## 性能數據範圍

自動測試列印本次 HTTP 回應 bytes 與時間，時間只供參考，沒有不穩定的毫秒通過門檻。摘要每頁最多 100 筆；預設 50 筆。事件最多 100 筆。完整匯出及單件詳情仍可能很大，這些只在使用者主動要求時讀取。

## 官方參考

- https://learn.chatgpt.com/docs/app-server （turn/interrupt、agentMessage phase、rateLimitsByLimitId）
