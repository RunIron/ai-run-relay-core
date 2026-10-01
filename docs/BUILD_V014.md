# v0.1.4 安裝包建置與公開流程

本原始碼包只交給專案擁有者，應放在私有核心儲存庫。一般使用者下載 native installer。
不會自動推送或公開任何檔案；GitHub Actions 只產出私有 artifacts。

## 編譯

Windows x64：Python 3.12、Visual Studio 2022 C++ build tools、Inno Setup 6。
Linux x86_64/glibc：Python 3.12（含 tkinter）、gcc、patchelf、dpkg-deb。
推薦 Ubuntu 22.04 建置以取得較低 glibc 下限。在 Ubuntu 24.04 建置的包不宣稱支援 22.04。

```sh
python -m pip install -r packaging/build-requirements.txt
python -m unittest discover -s tests -v
python tools/build_native.py
```

fake Codex tests 使用 POSIX executable；完整來源測試在 Linux 執行，Windows 執行編譯後的 smoke test。
建置產物在 `release-native`，每次建置前需手動移走舊產物。Windows 可透過 `--iscc` 指定編譯器。
Nuitka 編譯核心；內含執行所需 Python runtime，不要求終端使用者安裝 Python。
不包含 Codex CLI 或帳號；登入使用者自行持有的官方工具。

## 自動化

將本包內容推入**私有** GitHub 儲存庫，執行 Actions → Build private-core installers → Run workflow。
流程先測試來源，分別在 Windows/Linux 編譯，再安裝／執行模擬自測／解除安裝。
下載兩個 artifacts，確認驗證結果與平台 smoke test，才把安裝檔及 checksum 放到公開產品儲存庫的 Release。
不可把本 OWNER-PRIVATE ZIP、私有核心 commit、Nuitka build 目錄放入公開 repo。
public/ 的文件可以更新至公開 repo；公開 repo 不含核心，因此 GitHub 自動生成的 source archive 也只含文件。
Windows 安裝包目前沒有數位簽章；正式發布前應另行配置擁有者的簽署憑證。

## 驗證界線

`--self-test report.json` 在暫存目錄檢查 HTTP/HTML、SQLite、模擬額度等待、成功成果、重啟資料保留、鎖釋放。
不使用真實 AI，不修改使用者既有資料。不代表真實 Codex、圖形介面或所有 Linux 發行版相容性已通過。
另需在乾淨 Windows/Linux 桌面手動驗證安裝、工作資料夾、開啟瀏覽器、最小化繼續工作、關閉與升級。
核心不隨包附上 .py，但編譯檔可以被逆向分析；這不是無法複製或不可還原的保證。

商業使用須事先書面授權：runiron.wu@gmail.com。
