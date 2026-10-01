# AI Run Relay

**This repository contains the public v0.1.5 source release. Use it only within the rights and limitations stated in [LICENSE](LICENSE).**

**工作先排好，等待交給工具，額度恢復自動接續。**

**商業用途須事先取得專案發起人的書面授權；詳見 [LICENSE](LICENSE)。**

AI Run Relay 是本機執行的 AI 工作佇列。它保存每個完成步驟的結果，遇到額度限制便等待，再接續原本的工作階段。中文控制台可新增工作、查看倒數、檢視成果、取消與匯出。

**v0.1.5 / 安裝版測試候選。** 排程與 Codex 通訊流程有自動測試；尚未使用真實月租帳號驗證。第一版接入 **Codex 官方 app-server** 與不消耗額度的模擬模式。Claude、Gemini 接頭尚未實作。Codex 第一版只提供唯讀分析與文字成果，不開放自主寫檔、發信或發布。

## 一般使用者安裝版

目標為 Windows x64 安裝精靈及 Linux x86_64 的 `.deb`／`.tar.gz`；使用者不需裝 Python。
請依 [安裝說明](public/INSTALL.md) 及 [本次驗證報告](docs/VALIDATION_V014.md) 確認實際已產出的平台檔案。
維護者請見 [私有核心建置流程](docs/BUILD_V014.md)。`PUBLIC-INTRO.zip` 仍然只是文件，不能取代安裝檔。
商業書面授權聯絡：runiron.wu@gmail.com。

## 開發者從原始碼試跑

需要 Python 3.10 以上。從原始碼執行不需要安裝 Python 套件。

```bash
cd ai-run-relay
python3 -m relay --demo --open
```

Windows 可改用：

```powershell
py -3 -m relay --demo --open
```

開啟 <http://127.0.0.1:8765>。範例會完成第一步，在第二步模擬額度耗盡，等待 8 秒後完成剩下步驟。模擬輸出有明確標示，不代表 AI 實際做了分析。

首次工作資料夾預設為 `~/AI-Run-Relay-workspace`（Windows 為使用者家目錄下同名資料夾），不再使用程式本身資料夾。可在控制台「工作資料夾」輸入已存在的絕對路徑並保存；舊工作繼續使用原路徑。

也可以只启动空白控制台：`python3 -m relay --open`。按 Ctrl+C 停止。下次使用相同資料目錄启动，就會讀取之前的工作。

## 使用自己的 Codex 月租帳號

1. 依 [Codex 官方文件](https://learn.chatgpt.com/docs/codex-cli) 安裝官方 CLI，確認 `codex` 在 PATH。
2. 在自己的電腦執行 `codex login`，選擇 ChatGPT 登入。工具不提供登入表單、不讀取或轉存憑證檔。
3. 指定允許分析的資料目錄：

   ```bash
   python3 -m relay --workspace /absolute/path/to/research --open
   ```

4. 在控制台選擇 Codex，填入工作名稱及每行一個步驟，例如「整理本目錄文件重點」「比較各方案」「撰寫結論」。成果保存在 Relay 資料庫，可在控制台檢視／匯出。

檢查環境：`python3 -m relay --doctor`。偵測到 CLI 只表示已安裝；登入、配額與協定相容性會在工作開始時檢查。

工具只接受官方 CLI 管理的 ChatGPT 登入。API-key 登入會暫停，**不會自動轉成另外計費的 API**。登入後可用的模型與額度仍由你的方案決定。

## 實際行為

| 情況 | 行為 |
|---|---|
| 工作正常執行 | 依優先權（10 最高），同權重先進先出；一次只執行一個步驟 |
| 額度耗盡且有恢復時間 | 持久保存時間，稍加緩衝再檢查；不寫死 5 或 12 小時 |
| 多個用量窗口耗盡 | 只檢查本接頭對應的 codex bucket；相關主／次窗口採最晚恢復時間，不受其他 bucket 阻塞 |
| 恢復時間未知 | 標示「預估」；約 5、10、20、40、60 分鐘退避；單步最多 6 次自動嘗試 |
| 同平台其他工作 | 共用等待狀態，避免同時重試；模擬與 Codex 不共用額度 |
| 等待中關閉程式 | 保存等待時間與已完成結果，重新启动後繼續排程 |
| 真實執行中斷電或關閉 | 未確認的步驟轉為「需要確認」，人工檢查後續跑，避免盲目重做 |
| 電腦休眠或關機 | 無法在此期間執行；恢復運作並启动服務後再檢查 |
| 暫停排程 | 不再開始新步驟；目前步驟繼續，必要時使用取消 |
| 取消工作 | 先送 turn/interrupt，獨立等待最多 2 秒的停止確認，再清理程序；不會回滾已發生操作 |
| 登入失效、需人工核准、逾時 | 暫停並要求檢查；不會替使用者核准 |
| 單工作超過 7 天 | 預設停止自動排程；若平台明示更晚重置，延長至該時間後一小時（保留上傳版行為） |

「完成」表示官方執行器回報 turn completed，**不是內容正確性驗收**。重要成果仍需使用者檢查。只保存已完成步驟作為檢查點，無法保證接回尚未保存的每一個生成 token。

## 資料與權限

- 預設資料目錄：`~/.ai-run-relay/`，SQLite 保存工作、產出、工作階段 ID 與事件。可用 `--data-dir /path` 更改。
- 資料只在本機；執行 Codex 時提示及選定工作資料會交給官方 Codex 服務處理。
- 控制台只綁定 `127.0.0.1`，有 Host、Origin 及 CSRF 驗證。這不是公開網站或多人服務，不應反向代理到公網。
- 單一資料目錄只允許一個 Relay 程序，利用作業系統鎖避免雙重執行。
- 新工作目錄必須位於目前選定的 workspace 之內；切換 workspace 不改動既有工作路徑。這不是完整的資料隔離沙箱。
- 不保存 API keys，不擷取瀏覽器 Cookie，不輪換帳號繞過配額。
- 不要把私人 SQLite、匯出成果、Codex 設定或登入檔提交到 GitHub。
- Codex 使用既有 CLI 設定，外部 MCP／hooks 的檢查與限制請參考 [架構與限制](docs/ARCHITECTURE.md)。

## 開發與測試

```bash
python3 -m unittest discover -s tests -v
```

測試使用模擬時鐘與 fake app-server，不消耗 AI 額度。沒有真實 CLI 時仍可完整體驗模擬排程。

可選安裝：`python3 -m pip install .`，之後執行 `ai-run-relay --open`。

## 原始碼分享與商業授權

**非商業用途可依 [LICENSE](LICENSE) 免費使用、修改與分享；商業用途須事先聯絡本專案發起人，取得另行書面授權。**

Commercial use includes enterprise operations, customer services, paid deployment, SaaS, and integration into commercial products. Contact: runiron.wu@gmail.com. This public source release is distributed under the accompanying non-commercial license; it is not MIT and is not represented as an OSI-approved open-source license.

The complete source tree is intentionally published in this repository for non-commercial use. Review [CORE_PROTECTION.md](docs/CORE_PROTECTION.md) and [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) before producing derivatives or releases. Complete your own end-to-end testing with your Codex subscription before relying on the software. This is an independent implementation and does not copy unsnooze code.

延伸方向：Gemini／Claude 官方工具接頭、工作依賴、驗收規則、桌面打包、常駐服務。跨平台是架構方向，並非目前已支援所有 AI 月租產品。

## 本次修正與驗證

摘要分頁／增量更新、成果按需讀取、工作目錄設定、優雅中斷、失效 session 選擇性復原、最終訊息過濾、額度範圍判斷。驗證步驟與尚未實測部分見 [VERIFY_V013.md](docs/VERIFY_V013.md)。

## 官方協定參考

- [Codex app-server](https://learn.chatgpt.com/docs/app-server)：初始化、登入模式、用量窗口、thread／turn 協定。
- [Codex 非互動執行](https://learn.chatgpt.com/docs/non-interactive-mode)：自動化與工作階段接續背景。

文件查核日期：2026-10-01。官方工具可能更新，接頭需持續相容性測試。
