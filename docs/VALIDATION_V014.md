# v0.1.4 本次交付驗證

日期：2026-10-01。狀態：測試候選，未推送 GitHub，未宣告正式發布。

## 已完成

- 42 項 unittest 通過，最後完整執行約 8.065 秒。
- Linux x86_64：Nuitka 4.2.2 + Python 3.12，於 Ubuntu 24.04 編譯成功。
- 已產出 `AI-Run-Relay-0.1.4-linux-amd64.deb` 和 `AI-Run-Relay-0.1.4-linux-x86_64.tar.gz`。
- 編譯後自測通過：Tcl 載入、HTML/HTTP、SQLite、模擬額度等待、成果保存、重啟後成果及工作路徑保留。
- `.deb` 經 dpkg-deb 資訊檢查、解開至另一目錄，再以 PATH=/nonexistent、清除 PYTHONPATH/PYTHONHOME 執行自測通過。這證明自測不依赖外部 Python 指令，不等於乾淨系統已完成套件安裝測試。
- ELF 相依檢查未出現找不到的函式庫。Tcl 9 動態庫已補齊；Tcl/Tk 公開 C 範例不納入 runtime。
- runtime audit 排除 `.py`、`.pyc`、核心 C 原始碼、憑證、資料庫與 Git 資料。
- 以無桌面環境啟動時顯示 `--server` 使用提示。
- 私有 OWNER 包包含 Windows/Linux 建置腳本及 GitHub Actions；公开文件包不含核心。

## 平台範圍與未完成項目

- 本次 Linux 包要求 glibc >= 2.39；優先供 Ubuntu 24.04 x64 測試。未驗證其他發行版，不支援 Alpine/musl、ARM。
- 沒有可用的 Windows runner：尚未產出 `.exe`，Windows 安裝、解除安裝與 GUI 未測。
- Linux 桌面 GUI 未實際顯示與點選測試：環境沒有顯示伺服器。Tcl 載入與無桌面提示已驗證，不能取代視覺／操作測試。
- 本環境不能完成 apt 系統安裝，僅驗證 deb 格式及解包後執行。
- 真實 Codex CLI、月租登入、真實額度恢復與 turn/interrupt 均尚未實機驗證。
- GitHub 連接器重新確認仍為 DISABLED_BY_ADMIN / NOT_AVAILABLE，沒有推送、建 repo、上傳 Release 或執行遠端 Actions。
- GitHub workflow 只經靜態檢查，尚未執行。編譯不保證不可逆向或不可複製。

## 下一個發布關卡

1. 管理員啟用 GitHub 連接後，將 OWNER 內容推入私有核心 repo。
2. 執行 Build private-core installers，通過 Windows/Linux 的安裝及 smoke 工作。
3. 在乾淨 Windows 與 Ubuntu 桌面人工操作，接上真實 Codex 小型工作。
4. 將通過驗證的安裝檔及 checksum 發布到公開產品 repo；不要公開核心原始碼。
