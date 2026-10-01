# 核心保護與發布方式

## 本次已做

1. 完整修正版只放在名稱標示 OWNER-PRIVATE 的原始碼封裝，供專案擁有者保管與開發。它沒有加密，也沒有技術 DRM；持有者能讀取全部程式碼。
2. 新增 `public/` 目錄，只含產品與商業授權說明；不含可執行核心。
3. `tools/package_release.py` 使用明確檔案允許清單產生 PUBLIC-INTRO 封裝。公開包僅兩份 Markdown，不把 `.py`、wheel、測試或其他檔案自動放入。
4. 自動測試故意放入額外「核心」檔案，確認公開包不會將它帶出。SHA-256 清單供交付比對，不是數位簽章。
5. 沒有上傳 GitHub，也没有更動既有儲存庫權限。

## GitHub 建議

- 私有庫 `ai-run-relay-core`：完整核心、測試、內部規格。只授權必要開發人員。
- 公開庫 `ai-run-relay`：只從 PUBLIC-INTRO 包建立；之後可以加入經審核的使用文件與公告。
- 不要直接將 OWNER-PRIVATE、wheel、sdist 或完整 Git 歷史放到公開庫或其 Release 附件。Python wheel 和 PyInstaller 單檔封裝都不能視為原始碼保密保證。
- `.gitignore` 只影響未追蹤檔案，不會刪除歷史或保護已上傳程式。公開後轉私有也不能收回他人已取得的副本。

## 如果要讓大家直接使用

| 方式 | 保護效果與代價 |
|---|---|
| 公開原始碼＋非商業授權 | 可約束商業用途，但不能技術上阻止閱讀、複製；目前條款本身允許非商業複製與修改 |
| 私有原始碼＋編譯後的本機核心 | 提高直接複製門檻；仍可逆向，需 Windows/macOS/Linux 分別建置、測試及簽章 |
| 私有雲端核心＋本機執行代理 | 核心不交付客戶，較適合保護伺服器端策略；需新增認證、資料隔離、服務維運與費用 |

本次只實作私有／公開封裝分離，**沒有**實作編譯混淆、商業金鑰伺服器或雲端核心。不能把目前版本宣稱為「無法抄襲」。

若後續採雲端方案，月租帳號登入憑證應仍由使用者本機的官方 CLI 管理；不要為保護核心而把用戶憑證集中代管。具體接入仍須逐家核對平台規則。

## 授權與權利

0.1.1 起版本的商業使用須另行書面授權；授權聯絡信箱仍未確認。原 0.1.0 曾隨附 MIT，本次不能追溯宣称撤銷已合法授予的權利。

公開程式碼與保密目標有衝突；法律條款不能替代技術保密。正式商業化前，建議由法律專業人員確認權利歸屬、第三方條款、商業授權及保密措施，不能保證本草案在所有法域具有相同效果。

參考：
- GitHub 儲存庫可見性：https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility
- WIPO 商業秘密保護：https://www.wipo.int/en/web/trade-secrets/protection
