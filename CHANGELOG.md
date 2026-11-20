# Changelog

## [Unreleased]

## [4.25.2] - 2026-11-20

### Changed
- 模組解耦（SPEC-090），功能與畫面不變：唯讀統計 `analytics.py`、`goals.py`、`reports.py` 移入 `read_models/`（`insights.py`、`goal_progress.py`、`report_snapshot.py`）；改密碼通知移到共用的 `routers/password_notices.py`，架構檢查禁止 router 互相 import；`app-monthly-charts.js` 拆出 `app-trend-charts.js`，`app-pace-charts.js` 拆出 `app-race-goal.js`。Asset 4.25.2／shell v99，schema 12 不變。

## [4.25.1] - 2026-11-20

### Added
- 以 MIT 授權釋出（`LICENSE`）。

### Security
- 內建的 Chart.js 4.4.7 與 marked 15.0.12 以相同版本列入 npm 鎖定檔，`verify` 與 `audit-deps` 會稽核 npm 套件，GitHub 的相依套件警示也看得到它們（SPEC-089）。

### Changed
- 跑鞋資料表加上擁有者索引，啟動時自動建立。Asset 4.25.1／shell v98，schema 12 不變。

## [4.25.0] - 2026-11-20

### Added
- 「資料與同步」新增「登出所有裝置」（SPEC-088）：手機遺失或懷疑別人登入過時，不用換密碼也能讓所有裝置（包括這一台）重新登入。

### Security
- 邀請制註冊改為先檢查邀請碼再檢查名稱，沒有有效邀請碼時無法試出哪些帳號名稱已被使用。Asset 4.25.0／shell v97，schema 12 不變。

## [4.24.2] - 2026-11-20

### Security
- 登入 token 綁定帳號本身（SPEC-087）：帳號刪除後有人用同一個名稱重新註冊，被刪帳號裝置上還沒過期的登入不能進入新帳號。之前簽發的 token 照常有效到期，不需要重新登入。
- GitHub Actions 全部釘選到 commit SHA（含第三方的 `superfly/flyctl-actions`），標籤被移動也不會改變部署 job 執行的程式。

### Fixed
- 瀏覽器封鎖網站資料（例如封鎖所有 Cookie 與網站資料）時頁面打不開；現在照常啟動，登入只保存在這個頁面，重新整理後要再登入。
- 403 回應的 `error.code` 改為 `forbidden`，原本一律是 `capacity`；畫面訊息不變。Asset 4.24.2／shell v96，schema 12 不變。

## [4.24.1] - 2026-11-20

### Fixed
- AI 對話的「已思考 N 秒」改從這一輪開始算（送出訊息或上一個工具完成），接續泡泡裡已經數到的秒數（SPEC-086）。原本從第一個思考片段才開始計時，模型等了 30 幾秒才一口氣送出思考內容時，每個區塊都只顯示「已思考 1 秒」。Asset 4.24.1／shell v95，schema 12 不變。

## [4.24.0] - 2026-11-20

### Added
- AI 對話即時顯示思考過程（SPEC-086）：推理模型回答前的思考內容會在答案上方即時出現，開始回答或查資料時收合成「💭 已思考 N 秒」，點開可再看；還沒有任何內容時，泡泡顯示「思考中… N 秒」。思考內容不保存、不送回下一輪，也不改變模型的推理設定。Asset 4.24.0／shell v94，schema 12 不變。

## [4.23.1] - 2026-11-20

### Security
- 寄信的 STARTTLS 改為驗證 Gmail 的憑證與主機名稱；原本 Python 預設不驗證，攔截連線的人可以讀到應用程式密碼和驗證碼（SPEC-085）。
- 邀請制下不能註冊 `ADMIN_USERNAMES` 裡的名稱，管理員帳號也不能刪除：管理員權限跟著名稱走，空出來的名稱會讓下一個註冊的人成為管理員。第一個管理員仍在 `REGISTRATION_MODE=open` 時註冊。
- 驗證碼的次數在比對前就計入，同時送出的猜測不能超過每組 5 次；每個帳號每天最多試 10 次驗證碼（帳號與 email 共用），重寄不重算。Asset 4.23.1／shell v93，schema 12 不變。

## [4.23.0] - 2026-11-19

### Added
- 新帳號引導（SPEC-084）：跑步頁最上方顯示「開始使用：三個步驟」（新增第一雙鞋、記錄跑步或匯入 Strava、設定月目標），每步有直接開啟表單的按鈕，完成的步驟打勾；三步都完成或按「略過引導」後不再顯示。已經有鞋子、跑量與目標的帳號看不到。Asset 4.23.0／shell v92，schema 12 不變。

## [4.22.1] - 2026-11-18

### Added
- 密碼變更通知信（SPEC-083）：登入後更改密碼、用 email 驗證碼重設、管理員產生臨時密碼時，都寄信到綁定的 email，寫明帳號、台灣時間與方式；不是本人操作時提示用「忘記密碼？」重設。寄信在回應後進行，失敗不影響密碼變更。
- 登入／註冊頁也可以選「淺色／深色／跟隨系統」（SPEC-082）。

### Changed
- 正式站移除用不到的 `MIGRATION_PASSWORD` secret（只在升級極舊的資料庫或啟用範例資料時需要）。Asset 4.22.1／shell v91，schema 12 不變。

## [4.22.0] - 2026-11-18

### Added
- 外觀主題改為「淺色／深色／跟隨系統」三選一（SPEC-082），預設跟隨裝置設定，裝置切換淺色／深色時畫面與圖表即時更新；啟動畫面依同樣規則顯示，手機狀態列顏色也跟著主題。原本存過淺色或深色的裝置維持原選擇。Asset 4.22.0／shell v90，schema 12 不變。

## [4.21.3] - 2026-11-18

### Changed
- 個人資料清理第二輪（SPEC-081）：比賽準備的測試與版面假資料改成虛構的比賽日期、參考成績與跑步；時間輸入的提示範例改為 `5200 → 52:00`、參考距離提示改為 10；範例資料與舊版升級的預設帳號名稱改為 `Demo`；邀請碼範例改為 `RUNNER24`；README 的 clone 網址不再寫 GitHub 帳號，CHANGELOG 移除發版連結。Asset 4.21.3／shell v89，schema 12 不變。

## [4.21.2] - 2026-11-18

### Changed
- 公開 repo 的個人資料清理（SPEC-081）：範例資料（`SEED_DATA`）改成虛構的鞋款與月跑量；管理員備註與鞋款尺寸的提示不再用真實帳號或尺寸；文件與測試的真實跑步總計、單鞋里程與鞋名改成虛構例子。git 歷史未改寫。Asset 4.21.2／shell v88，schema 12 不變。

## [4.21.1] - 2026-11-18

### Changed
- 登入頁移除「更改密碼」，只留登入、註冊與「忘記密碼？」；知道目前密碼時改到「資料與同步」→「更改密碼」，更改後所有裝置重新登入（SPEC-080）。管理員臨時密碼的說明指向新位置。
- README 的備份範例路徑改成通用的 `~/.local/share/...`。Asset 4.21.1／shell v87，schema 12 不變。

## [4.21.0] - 2026-11-18

### Added
- Email 驗證碼找回密碼（SPEC-079）：「資料與同步」可以綁定 email（輸入寄到信箱的驗證碼才綁定），登入頁新增「忘記密碼？」，用帳號或 email 收驗證碼並重設密碼。寄信使用專用 Gmail 的應用程式密碼（`SMTP_USERNAME`／`SMTP_PASSWORD`），沒設定時自動隱藏。
- 新 API：`POST /api/auth/email/request|confirm|remove`、`POST /api/auth/password-reset/request|confirm`；`/api/auth/registration` 新增 `mail_enabled`，`/api/auth/me` 新增 `email`。

### Security
- 驗證碼 6 位數、10 分鐘、最多試 5 次，只存 HMAC；忘記密碼不論帳號是否存在都回同樣結果，信在回應後才寄；每個 IP／帳號／全站都有寄送上限。Schema 12，asset 4.21.0／shell v86。

## [4.20.4] - 2026-11-18

### Fixed
- 每日加密異地備份的第一次執行在「上傳前解密檢查」失敗：`grep -q` 提早結束讓 `tar` 寫入中斷，在 `pipefail` 下整步失敗。現在先讀完整份清單，再確認 `.db`、`.sha256`、`manifest.json` 都在（SPEC-078）。Asset 4.20.4／shell v85，schema 11 不變。

## [4.20.3] - 2026-11-18

### Added
- 每日加密異地備份（SPEC-078）：`offsite-backup.yml` 每天 03:30（台北）從 Fly 下載正式資料庫、驗證並做還原演練，以 `BACKUP_PASSPHRASE` 用 AES-256 加密後存成 GitHub artifact，保留 30 天；只上傳加密檔。Asset 4.20.3／shell v84，schema 11 不變。

## [4.20.2] - 2026-11-18

### Changed
- 管理員的邀請碼與重設密碼功能從「資料與同步」移到側邊欄的「邀請碼管理」按鈕與獨立視窗，只有管理員看得到；關閉視窗時清掉畫面上的邀請碼與臨時密碼（SPEC-077）。Asset 4.20.2／shell v83，schema 11 不變。

## [4.20.1] - 2026-11-18

### Changed
- 註冊表單的邀請碼提示改為「向管理員索取」，不再顯示像真的邀請碼的範例（SPEC-076）。
- 管理員可以自訂好記的邀請碼（4～20 個英文字母或數字，不分大小寫）；留空仍自動產生 8 碼。Asset 4.20.1／shell v82，schema 11 不變。

## [4.20.0] - 2026-11-18

### Added
- 邀請制註冊（SPEC-075）：註冊預設需要邀請碼（`REGISTRATION_MODE`：invite／open／closed）。管理員（`ADMIN_USERNAMES`）在「資料與同步」產生、查看與停用邀請碼，並可替忘記密碼的人產生臨時密碼。
- 「資料與同步」新增「刪除帳號」：輸入密碼後永久刪除帳號與所有資料。登入與註冊頁新增隱私說明。
- 新 API：`GET /api/auth/registration`、`POST /api/auth/delete-account`、`GET/POST /api/admin/invites`、`DELETE /api/admin/invites/{invite_id}`、`POST /api/admin/reset-password`；`GET /api/auth/me` 新增 `is_admin`。

### Changed
- 帳號名稱不分大小寫（`Runner` 與 `runner` 是同一個帳號），登入失敗鎖定也不分大小寫。
- AI 每個帳號每天的預設上限從 50 次降為 20 次（全站 200 次不變）。Schema 11（`invites` 與 `lower(username)` 唯一索引），asset 4.20.0／shell v81。

## [4.19.4] - 2026-11-18

### Security
- 登入、註冊、改密碼的預設上限從每個 IP 每分鐘 120 次、全站 300 次降為 20／60 次：每次都要做約 0.2～0.3 秒的 bcrypt，原本的全站額度可以吃滿唯一的 CPU（SPEC-074）。
- Strava 預覽與匯入同時只處理一個上傳（忙碌時回 429），並限制每個帳號每分鐘 10 次（`STRAVA_UPLOAD_RATE_LIMIT_PER_MINUTE`），避免同時解析多個 10 MB 檔案撐爆 256 MB 記憶體。Asset 4.19.4／shell v80，schema 10 不變。

## [4.19.3] - 2026-11-18

### Security
- 所有 API 新增每個來源位址每分鐘 600 次的上限（`API_RATE_LIMIT_PER_MINUTE`），在驗證與資料庫之前以記憶體計數，超過回 429；`fly.toml` 設定同時請求上限（soft 25／hard 50），被大量請求灌入時由 Fly 先擋下（SPEC-073）。Asset 4.19.3／shell v79，schema 10 不變。

## [4.19.2] - 2026-11-18

### Added
- 每週跑量與每週最長一次新增「‹ 較早／較晚 ›」，在選定年份內一次切換 16 週；過去的年份不再只看得到 9～12 月（SPEC-072）。`GET /api/analytics/trends` 新增選填的 `weeks_end` 與回應的 `weekly_window`。

### Fixed
- 年度月跑量對比在沒有資料的月份斷線（SPEC-072）：Strava 紀錄從 2024 年 9 月開始，2024 年的線只從 9 月畫起。現在已經開始的月份沒有資料就畫 0，還沒到的月份才留白。
- 過去年份的每週跑量說明寫「本週 0.0 km」；現在只有今天所在的週叫本週，被 12/31 截斷的最後一週標示「只算到 12/31」。Asset 4.19.2／shell v78，schema 10 不變。

## [4.19.1] - 2026-11-18

### Security
- AI 對話與月報新增每日額度：每個帳號每天 50 次、全站每天 200 次，可用 `AGENT_DAILY_LIMIT_PER_USER`、`AGENT_GLOBAL_DAILY_LIMIT` 調整，避免公開註冊的帳號整天消耗 OpenRouter 額度（SPEC-071）。
- 正式站關閉 Swagger UI（`/docs`）與 ReDoc（`/redoc`），`/openapi.json` 保留給部署檢查；所有回應加上 `Strict-Transport-Security`。Asset 4.19.1／shell v77，schema 10 不變。

## [4.19.0] - 2026-11-18

### Added
- 跑鞋分頁新增「跑步里程」卡：所有跑步紀錄的合計與筆數，和 Strava 個人頁的跑步總計一致（例如 1,234.5 km · 210 次跑步），由新的 `GET /api/runs/totals` 提供（SPEC-070）。

### Changed
- 「總里程」卡改名為「跑鞋里程」並註明含步行、健行；移除「需補鞋類別」卡，摘要維持六張。Asset 4.19.0／shell v76，schema 10 不變。

## [4.18.4] - 2026-11-18

### Fixed
- 偶爾才穿的鞋（健行鞋、比賽鞋）近 90 天沒有紀錄時，退役日改用計畫月跑量（預設 60 km）推算，得出不合理的日期（SPEC-069）。現在穿過但近 90 天沒穿的鞋不預估，清單與單鞋分析顯示「—」；還沒穿過的新鞋才用計畫月跑量。API 的 `forecast_source` 新增 `idle_90_days`。Asset 4.18.4／shell v75，schema 10 不變。

## [4.18.3] - 2026-11-18

### Changed
- 跑鞋里程改成和 Strava 完全相同的顯示方式：無條件捨去到小數點第一位（SPEC-068）。Strava 把 512.352 km 顯示成 512.3，先前 App 四捨五入成 512.4。套用到現役／退役清單、首頁總里程、單鞋分析、壽命圖與輪替時間軸；儲存值與行內編輯不變。README 新增「里程如何與 Strava 對帳」。Asset 4.18.3／shell v74，schema 10 不變。

## [4.18.2] - 2026-11-18

### Fixed
- 輪替時間軸的里程和跑鞋清單對不上（SPEC-067）。時間軸只算跑步紀錄，清單是鞋子總里程，還包含記在鞋上的步行與暖身（Strava 的「步行」活動不會匯入成跑步）。提示框現在顯示鞋子里程，並拆成跑步與步行與暖身；跑鞋清單的里程和 Strava 一樣顯示到小數點第一位。Asset 4.18.2／shell v73，schema 10 不變。

## [4.18.1] - 2026-11-17

### Fixed
- 手機數字鍵盤沒有冒號，跑步時間、目標時間與參考成績時間打不出 `52:00`（SPEC-066）。現在直接打數字會從右邊每兩位自動補上冒號：`5200` → `52:00`、`15959` → `1:59:59`；一、兩位數仍是整數分鐘。Asset 4.18.1／shell v72，schema 10 不變。

## [4.18.0] - 2026-11-17

### Added
- 訓練分析新增「比賽準備」（SPEC-065）：設定目標賽事（日期、距離、目標時間，選填參考成績與氣溫）後，顯示倒數、目標配速、依 Riegel 公式預估的完賽時間、近 8 週強度分布（輕鬆／穩定／比賽配速／更快），以及長距離是否足夠（比賽距離 75% 為門檻、建議至少 2 次、最後一次在賽前 14 天前）。配速趨勢依強度上色並畫出目標配速。新增 `GET/PUT/DELETE /api/race-goal` 與 `GET /api/analytics/race`。

### Removed
- 移除只描述資料、無法指導訓練的「月跑量與配速」「累積跑量與配速」「距離與配速」「配速分布」；星期幾跑量與配速保留。Asset 4.18.0／shell v71，schema 10，回滾見 `scripts/rollback_schema_ten.sql`。

### Security
- 開發用依賴升級：`filelock` 4.1.1 → 4.2.7、`pip` 25.3 → 26.2.2，關閉 22 個 Dependabot 警告（只影響 `requirements-dev.txt`，正式環境依賴不變）。已不再使用 pip-tools，移除舊的 pip 版本限制說明。Repo 開啟 Dependabot security updates。
- 發版 workflow 的 commit 清單改以 UTF-8 解碼，Windows 本機跑測試時不再因中文 commit 訊息失敗。

## [4.17.1] - 2026-11-17

### Changed
- 分頁改名：「月跑量」改為「訓練分析」（目標、年度回顧、訓練趨勢與配速分析都是長期資料），「AI」改為「AI 教練」（對話與月報）。README 改寫成作品集形式，加上專案簡介、架構、核心流程、安全、設計取捨與開發歷程。Asset 4.17.1／shell v70，schema 9 不變。

## [4.17.0] - 2026-11-17

### Added
- 月跑量分頁新增「配速分析」（SPEC-064），涵蓋全部紀錄：配速趨勢（每次跑步與近 30 天平均）、月跑量與配速、累積跑量與配速（前 4 週平均週跑量對當週配速，含趨勢線與各區間差距）、距離與配速、配速分布。訓練趨勢的星期幾跑量同時顯示每個星期幾的平均配速。所有數字由後端計算，新增 `GET /api/analytics/pace`。Asset 4.17.0／shell v69，schema 9 不變。

## [4.16.1] - 2026-11-17

### Fixed
- Strava 繁中匯出的時段不只「上午／下午」（SPEC-063）。「晚上 11:30」（UTC）這類活動先前被記到前一天，現在換算成台灣的隔天清晨；凌晨、清晨、中午、傍晚等時段與 24 小時制也都能解析。已經記錯日期的紀錄重新匯入時會修正日期。Asset 4.16.1／shell v68，schema 9 不變。

## [4.16.0] - 2026-11-17

### Fixed
- Strava 匯入不再重複新增手動輸入過的跑步（SPEC-062）。同一天只有一筆距離接近（0.3 km 或 5% 以內）的手動紀錄時，改為連結到那筆紀錄並補上缺少的跑步時間，距離、鞋款與里程不變；同一天有手動紀錄但無法確定是同一次時不匯入，預覽列出筆數與例子。連結後的紀錄之後會被當成已匯入。Asset 4.16.0／shell v67，schema 9 不變。

## [4.15.0] - 2026-11-17

### Added
- 跑步紀錄可以填跑步時間，自動算配速（SPEC-060）：新增與編輯表單多一欄「跑步時間（選填）」，接受 `32:15`、`1:05:30` 或整數分鐘，邊輸入邊顯示配速。跑步列表新增時間與配速欄，月份卡片與單雙鞋分析顯示平均配速（總時間 ÷ 有時間的距離）。
- Strava 匯入讀取移動時間；重新匯入同一份 CSV 會替既有紀錄補上還沒有的時間，不覆寫已有的時間。
- 帳號備份升為 v4，包含跑步時間；舊版無法讀取 v4。Asset 4.15.0／shell v66，schema 9，回滾見 `scripts/rollback_schema_nine.sql`。

### Changed
- CI 更嚴謹（SPEC-061）：任何分支的 push、pull request（測試合併後的結果）與每週排程都跑完整測試，只改文件也跑。`main` 改由 ruleset 保護：只能透過 PR 合併，5 個測試 job 全部通過且分支跟上 `main` 才能合併，不能直接 push 或 force push。部署、發版流程不變。

## [4.14.1] - 2026-11-16

### Fixed
- 「每週最長一次」的近期平均改為只算已結束的週（過去 4 週，不含本週）；本週還沒跑長距離時不再當成 0 km 拉低平均，折線也不再掉到 0。每週跑量圖的 4 週平均同樣不為進行中的週畫點（SPEC-056 修訂）。

### Changed
- 週目標說明列出計算依據「年度目標 ÷ 52.1 週」（一個月約 4.35 週，不是每月目標 ÷ 4）。
- 星期幾跑量改為「跑最多的是週六：270.3 km、30 次，平均每次跑 9.0 km」，tooltip 顯示天數、次數與平均每次距離。Asset 4.14.1／shell v65，schema 8 不變。

## [4.14.0] - 2026-11-16

### Changed
- 新版裝好後在安全時自動套用（SPEC-059）：App 在背景、剛回到前景還沒操作，或閒置 5 分鐘時自動重新載入成新版，不必在每台裝置按「立即更新」。AI 正在回答、月報產生中、有彈窗或行內編輯、有請求還沒完成、輸入框還有文字時先等待；使用中的畫面仍可按提示馬上更新。
- 完成的 AI 對話保存在分頁的 sessionStorage，重新載入或自動更新後還在；關閉分頁、登出或換帳號會清除。
- 第一次升到 v4.14.0 時，各裝置仍需手動更新一次。Asset 4.14.0／shell v64，schema 8 不變。

## [4.13.0] - 2026-11-15

### Added
- 訓練趨勢新增週目標、每週最長一次與星期幾分析（SPEC-056）：每週跑量圖加上週目標虛線（年度目標 × 7 ÷ 全年天數）與達標週數，新增「每週最長一次（近 16 週）」與「星期幾跑量」兩張圖。
- AI 助手新增 4 個工具（SPEC-057）：`running_goal_progress`、`training_trends`、`year_review`、`spending_summary`，直接引用首頁與月跑量分頁相同的後端統計，共 12 個工具。
- README 新增完整的「API 一覽」（48 個端點），`docs-check` 會擋下漏列的端點（SPEC-058）。

### Fixed
- 刪掉的 Strava 跑步不再因重新匯入同一份 CSV 而回來（SPEC-055）。刪除時記住 Strava 活動 ID（schema 8），預覽顯示「另有 N 筆先前刪除過的活動不會重新匯入」；升級前刪除的活動在稽核紀錄還在時一併回填。需要找回時從異動歷史復原。
- 年度回顧在年份進行中時改與前一年同期比較，不再拿今年到今天的里程比去年全年。
- 已退役的鞋不再顯示「預估退役日期」，AI 使用分析也一樣。
- 換鞋提醒門檻統一為 80% 注意、90% 準備換鞋；跑步日誌頁的洞察原本要到 100% 才標為緊急。
- 跑步日誌卡片改顯示所選月份（例如「9 月總里程」），不再寫死「本月」。
- 登入、註冊與改密碼欄位改用標準 `autocomplete`，密碼管理器可以填入帳密（取代 SPEC-005 停用自動完成的決定，登出時仍清空欄位）；加上標準的 `mobile-web-app-capable` meta。

### Changed
- README 的版本說明移到 [`docs/release-notes.md`](docs/release-notes.md)，「## 測試」整理為「開發與測試」與「統計與操作規則」（SPEC-058）。
- 依賴更新：`opentelemetry-api` 1.45.1 → 1.45.2（CVE-2026-126360）。Asset 4.13.0／shell v63，schema 8，回滾見 `scripts/rollback_schema_eight.sql`。

## [4.12.0] - 2026-11-13

### Security
- 頁面加上嚴格的 Content-Security-Policy（SPEC-054）：只允許同源 script，以及建置時以 SHA-256 雜湊放行的三段啟動 script，inline 事件屬性、`eval` 與外部 script 都會被擋下。樣式表上的 inline `onload` 改為可雜湊的 script；離線頁改用不需 script 的「重新連線」連結。
- 所有回應加上 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`／`frame-ancestors 'none'`、`Referrer-Policy: same-origin`、`Cross-Origin-Opener-Policy: same-origin` 與 `Permissions-Policy`；`.js`／`.mjs` 固定以 `text/javascript` 提供。
- 移除 `allow_origins=["*"]` 的 CORS 設定，API 只接受同源呼叫。
- 正式的認證只用 app 注入的密鑰解碼，不再有退回環境預設密鑰的簽章 helper（SPEC-053）。

### Changed
- `docs-check` 會檢查 README 目錄樹列出每個後端／前端模組與 script、SDD 安排每個應用模組、README 寫了每個執行環境變數（SPEC-053）。README 補上 `OR_MODEL`、`ENVIRONMENT`、`DB_DIR`、`DATABASE_URL`、`FRONTEND_DIR` 與 `FLY_APP_NAME` 的說明。
- 瀏覽器 E2E、40 組版面與部署後 release-check 遇到任何 CSP 違規都會失敗。
- 合併重複的 legacy tool-call 掃描、月跑量查詢與 schema 驗證器，行為不變。

### Fixed
- 在 Windows（CRLF checkout、cp950、Python 3.11）上 5 個測試失敗：前端的 SPEC-052 圖示斷言，以及讀 workflow 與產生中文 release notes 的 Python 測試。共用 helper 改以 LF 讀取來源，Python 測試一律以 UTF-8 讀寫。Asset 4.12.0／shell v62，schema 7 不變。

## [4.11.0] - 2026-11-13

### Changed
- 主畫面與分頁圖示改版（SPEC-052）：PWA、iOS 主畫面圖示改為碳黑底配 volt「速度線＋箭頭」標誌與磨耗進度環，瀏覽器分頁的 `favicon.svg` 改用同一個標誌（取代紫色「R」）。圖示有向量來源 `frontend/icons/app-icon.svg`，以 `node scripts/render_icons.cjs` 產生 PNG。已加入 iOS 主畫面的捷徑需刪除後重新「加入主畫面」才會換圖示。Asset 4.11.0／shell v61，schema 7 不變。

## [4.10.0] - 2026-11-13

### Changed
- 運動科技風視覺改版（SPEC-051）：碳黑底加細格線、螢光黃綠（volt）主色、DIN 風格數字字體、斜線速度條標記與英文區塊小標；登入頁、開機畫面與側欄使用新的「速度線＋箭頭」標誌，分頁圖示由 emoji 改為線條 SVG。
- 亮色主題重新配色：螢光黃綠只當底色，文字與線條改用深綠；圖表、跑鞋磨耗色階、熱力圖與跑步月曆都改讀 CSS 主題 token，修正白底上淺綠文字看不清楚的問題。版面尺寸、操作與資料都不變。Asset 4.10.0／shell v60，schema 7 不變。

## [4.9.0] - 2026-11-12

### Changed
- 跑鞋頁的「月跑量佔比」改為「近 90 天月均里程佔比」（SPEC-050）：每雙現役鞋改用近 90 天跑步紀錄算出的實際月均（與單鞋分析的「實際月均」相同），不再使用手動填的計畫月跑量；圓餅中間顯示「近 90 天月均」合計。跑鞋清單 API 新增唯讀欄位 `actual_monthly_km_90_days`。
- 現役跑鞋表格移除「月跑量」欄。計畫月跑量仍可在編輯視窗修改，近 90 天沒有跑步紀錄的鞋，退役預估仍以它回退。

### Fixed
- 跑鞋頁的「跑鞋輪替時間軸」與「每雙鞋的距離分布」偶爾只剩標題和說明、圖是空白，要重新整理才回來。這兩張圖用跑步紀錄算，畫圖前會先清掉舊圖再讀資料；讀取期間跑步紀錄或目標資料才到，會把這次讀取作廢，但跑鞋頁沒有被標記成要重畫。現在這兩種資料到達時都會重畫跑鞋頁。讀取期間切到別的分頁再切回來也會重畫，不再留下空白。Asset 4.9.0／shell v59，schema 7 不變。

## [4.8.0] - 2026-11-11

### Added
- 新版部署提示（SPEC-049）：App 開著時，回到前景、視窗取得焦點、網路恢復及每 30 分鐘會檢查新部署；偵測到新版時顯示「有新版本 v<版號>」，按「立即更新」才重新載入，按「稍後」先隱藏。重新載入時表單草稿會保留，AI 對話會清除。

### Changed
- 不再於偵測到新版時自動重新載入頁面（v4.0.0 起的行為），避免中斷正在進行的 AI 對話。Asset 4.8.0／shell v58，schema 7 不變。

## [4.7.3] - 2026-11-11

### Security
- 帳號備份還原預覽不再能被一份刻意做大的檔案耗盡記憶體（SPEC-047 修訂）：上限從 20 MB 降為 10 MB，跑步與異動歷史各從 50,000 筆降為 10,000 筆，仍容納帳號配額內最大的真實資料（約 7 MB）。預覽加上每帳號每分鐘 20 次、全站 60 次的限制（可用環境變數調整），每個伺服器程序一次只處理一個預覽或還原，忙碌時立即回 429。

### Changed
- push 到 main 自動部署與發版（SPEC-048）：全部測試通過後，先在 Fly 主機建立並驗證資料庫快照，再 `flyctl deploy`、跑匿名 release-check；`package.json` 版號還沒有 tag 時自動打 tag 並以本檔對應段落發 GitHub Release。只有部署 job 拿得到 `FLY_API_TOKEN`，只有發版 job 能寫入 repo。browser 測試遇到 CI WebKit 偶發錯誤會自動重跑一次並留下警告。
- 預覽不再同時保留兩份完整 Python 副本，上傳緩衝交出後即釋放；近上限檔案的預覽記憶體峰值從約 262 MiB（舊上限 18 MiB 檔）降為約 57 MiB（10 MiB 檔）。每帳號暫存預覽上限從 64 MiB 降為 30 MiB。Asset 4.7.3／shell v57，schema 7 不變。

## [4.7.2] - 2026-11-09

### Fixed
- 帳號備份 JSON 的檔名改用台灣時間；Fly 主機在 UTC，原本晚上 0～8 點下載的備份會標成前一天（SPEC-047 修訂）。前端備用檔名也改用本地日期。

### Security
- AI 對話與月報不再把模型供應商的原始錯誤內容（可能含上游細節與帳號識別碼）顯示給使用者，改顯示依狀況整理的訊息（額度已滿、逾時、服務暫停等）；詳細內容只寫進伺服器 log。

### Changed
- 跑鞋清單、月跑量清單與已存月報的查詢從 router 移到 read model，`/health/ready` 的資料庫探測移到 `migrations.ready_schema_version()`；新增測試確保 router 不再自行查詢資料庫。Asset 4.7.2／shell v56，schema 7 不變。

## [4.7.1] - 2026-11-09

### Fixed
- 匯入含異動歷史的備份不再擠掉本機可「復原誤刪」的紀錄：本機異動與備份帶入的唯讀歷史改為各自保留最新 5,000 筆（SPEC-047 修訂）。
- 過期的還原預覽（每帳號最多 64 MiB）改在每次啟動時清除，不必等同一帳號再次預覽。
- 年目標固定兩位小數（月 12.3 km → 年 147.6 km），API、資料庫與備份匯出不再出現浮點尾數。
- `MODEL_REFRESH_COOLDOWN_SECONDS` 上限為 3600，與限流紀錄保留時間一致，避免冷卻被提早清除。

### Changed
- 移除三處沒有作用的 `except Exception: raise`；補上歷史復原衝突分支與 `/health/ready` 503 分支的測試。Asset 4.7.1／shell v55，schema 7 不變。

## [4.7.0] - 2026-11-09

### Fixed
- Strava 日期（SPEC-047）：匯出的 UTC 時間改換算為台灣日期，清晨跑步不再記到前一天或上個月；重新匯入時會修正仍停在舊 UTC 日期的紀錄並移動月跑量，手動改過的日期保留。
- `PUT /api/runs/{id}` 送 `expected_version: null` 改回 422，不再誤報 409「已被更新」；匯出檔名改用台灣時間；同月份新增跑步不再浪費月跑量 ID。
- 稽核 trigger 每次啟動依目前欄位重建，避免日後增刪欄位造成復原缺欄或寫入失敗。
- 測試的 SyntaxWarning（無效跳脫字元）與 330 個未關閉 SQLite 連線警告。

### Security
- 登入鎖定改為兩層：同一來源對同一帳號輸錯 10 次只暫停該來源，跨來源累計 100 次才暫停整個帳號，避免他人把已知帳號鎖在外面。
- 正式環境要求 `SECRET_KEY` 至少 32 bytes，缺少或太短時拒絕啟動；開發用預設密鑰也達 32 bytes。

### Changed
- Schema 6 → 7：新增 `run_tombstones`（刪除身分不再由稽核紀錄推導），替 `mutation_receipts` 加上 `recorded_at`，移除被取代的 `run_creation_requests`；提供 `scripts/rollback_schema_seven.sql`。
- 每個帳號保留最新 5,000 筆異動紀錄、1,000 筆操作回執與 50,000 筆刪除身分，資料庫不再無上限成長。
- 解耦：
  - 匯入 backend 模組不做 I/O，`create_app()` 唯一驗證密鑰並建立 engine。
  - 限流只用 SQLite、在獨立交易中 all-or-nothing 計數，限額來自注入設定。
  - 跑步清單與 Strava 歷史查詢移到 read model；上傳上限文字依實際限制產生。
  - 鞋款驗證規則各只定義一次；操作分派改為固定註冊表；`change_password` 改經 `write_transaction`。
- 前端以 `app-actions.js` 委派 `data-*` 動作，移除約 80 個 inline 事件。Asset 4.7.0／shell v54、51 個 release assets。

## [4.6.0] - 2026-11-09

### Added
- 購買日前跑步提醒（SPEC-046）：新增／編輯跑步的日期早於所選鞋款購買日時提醒確認，仍可儲存；Strava 匯入預覽每個鞋款群組回傳最早日期，配對鞋款較晚購買時提醒。

### Changed
- 冷啟動加速（SPEC-046）：後端啟動不載入 OpenAI SDK（本機載入時間約 600 → 385 ms），Docker image 預先編譯 `backend/`。Asset 4.6.0／shell v53。
- 瀏覽器檢查以 `scripts/browser_probe.cjs` 實際啟動 Chromium／WebKit 判斷；缺 Linux 系統函式庫時 `verify-all` 與 Stop hook 跳過並提示 `install-deps`，release-check 仍要求可用瀏覽器。

## [4.5.1] - 2026-11-09

### Changed
- 清除舊空表與已刪除鞋款標籤（SPEC-045）：啟動時刪除不再使用的空表 `operation_history`、`app_settings`（仍有資料則保留），資料庫 19 → 17 張表、schema 維持 6；年度堆疊圖把已刪除鞋款合併為灰色「已刪除的鞋款」，不再顯示內部編號，日曆標籤改為「已刪除」。Asset 4.5.1／shell v52。

## [4.5.0] - 2026-11-09

### Changed
- 月跑量年度目標總覽（SPEC-044）：移除「查看月份」選單，年度目標卡依上方年份一次顯示 12 個月達標狀態、年度累計與今天應有的進度、年底前每週需求及本月進度；目標設定收進「調整目標」，開始年份改為年份選單並附說明。新增唯讀 `GET /api/running-goal/year`。Asset 4.5.0／shell v51。

### Fixed
- 資料庫備份保留：同一個檔案系統時鐘刻度內連續建立的備份 mtime 相同時，改以檔名中的 UTC 時間排序，不會誤刪最新備份。
- `test_import_paths` 不再受開發者本機 `.env` 的 `SECRET_KEY` 影響。

## [4.4.0] - 2026-11-09

### Changed
- 支出併入跑鞋分頁（SPEC-043）：移除「支出」分頁，支出卡片、年度支出總覽、年度月支出與支出明細移到跑鞋分頁最下方，內容不變；導覽剩 4 個分頁，手機底部分頁列 4 欄。Asset 4.4.0／shell v50。

## [4.3.0] - 2026-11-09

### Changed
- 跑步日誌移除頂端四張摘要卡（本週、連續跑步、本月目標、累計跑量）、里程碑標籤與個人紀錄；保留「今天穿哪雙」。`GET /api/analytics/home` 只回傳選鞋建議（SPEC-042）。
- 每雙鞋的距離分布改為 5 km 一段（<5、5–10、10–15、15–20、≥20 km），依序以紅、黃、綠、藍、紫標示。
- AI 助手與月報合併為一個「AI」分頁，面板上方切換「對話／月報」；手機底部分頁列改為 5 欄。
- Asset 4.3.0／shell v49，schema 6 不變。

## [4.2.0] - 2026-11-09

### Added
- 月跑量分頁「年度回顧」：總跑量與前一年比較、年度目標達成率、跑步次數與天數、平均距離、最長連續、最長一次、最多的一週與月份、最常穿的鞋、買鞋數量與每 km 成本（SPEC-040）。
- 跑步日誌頂端摘要：本週跑量、連續天數、本月目標進度環、累計跑量與下一個里程碑，以及近 30 天的里程碑與個人新紀錄。
- 「今天穿哪雙」：依休息天數建議現役鞋（快到退役里程的鞋排最後），一鍵選入新增跑步表單。
- 跑鞋分頁「每雙鞋的距離分布」與月跑量分頁「年度月跑量對比」。
- API：`GET /api/analytics/home`、`GET /api/analytics/year-review`、`GET /api/analytics/shoe-distance-mix`。

### Changed
- 月跑量分頁只剩頂端一個年份選單，目標、回顧、趨勢與所有年度圖表一起切換。
- 同一雙鞋在所有圖表與表格使用相同顏色。
- 手機版改為固定底部分頁列；標題列「帳號」選單只保留同步、主題與登出。
- Asset 4.2.0／shell v48，schema 6 不變。

### Fixed
- Windows 上瀏覽器 E2E 結束時暫存資料夾偶爾被鎖住而刪除失敗，改為重試。

## [4.1.3] - 2026-11-09

### Changed
- 跑鞋輪替時間軸只列出現役鞋，已退役的鞋不再顯示；`GET /api/analytics/shoe-timeline` 不再回傳退役鞋與 `is_retired` 欄位（SPEC-038 修訂）。Asset 4.1.3／shell v47。

### Fixed
- CI 瀏覽器工作固定在 `ubuntu-24.04`：`ubuntu-latest` 改為 26.04 後，掛進 Playwright noble 容器的 tool-cache Python 缺少 ssl 模組，pip 無法安裝依賴。

## [4.1.2] - 2026-11-07

### Removed
- 月跑量分頁的「月跑量紀錄」表格、新增表單與月份編輯對話框（`app-monthly.js`）。既有月跑量與歷史／手動調整資料保留，圖表、目標、報告、備份與 API 不變；舊裝置上的月份草稿升級後被忽略（SPEC-039）。Asset 4.1.2／shell v46，release asset 50 個。

### Fixed
- Claude Code Stop hook 不再對未變更的工作區重播快取的失敗：回應 hook 回饋時不重複阻擋，之後的停止點重新驗證，避免暫時性網路錯誤（例如 pip-audit 連不到 PyPI）造成無限循環。

## [4.1.1] - 2026-11-06

### Changed
- 月跑量分頁的「月跑量紀錄」表格預設收合，只列出「年度月跑量」選擇的年份（最多 12 列），新增月份後切到該年份（SPEC-039）；Asset 4.1.1／shell v45。

### Fixed
- Claude Code Stop hook 以 UTF-8 讀取事件 JSON，不再因 Windows 主控台字碼頁（cp950）遇到中文或 emoji 時誤判為無效 JSON。

## [4.1.0] - 2026-11-06

### Added
- 月跑量分頁「訓練趨勢」：年度跑步熱力圖與有跑天數／最長／目前連續天數、近 16 週每週跑量與 4 週平均（比前 4 週平均多 30% 以上標示暴增）、年度累計跑量對照目標線與全年推估（SPEC-038）。
- 跑鞋分頁「跑鞋輪替時間軸」：每雙鞋首次到最後一次跑步的期間，標出超過 30 天沒穿的現役鞋（SPEC-038）。
- API：`GET /api/analytics/trends`、`GET /api/analytics/shoe-timeline`；Asset 4.1.0／shell v44，schema 6 不變。

## [4.0.3] - 2026-11-05

### Changed
- 依賴升級：certifi 2026.10.23、python-dotenv 1.2.4、httpx2 2.16.0、ruff 0.17.2、types-openpyxl 3.1.5.20261017；鎖定檔以 `uv pip compile --universal` 重編，保留 Windows 條件（取代 Dependabot #17–#21）。

### Fixed
- 本機工作區 IndexedDB 連線被瀏覽器關閉（iPhone Safari 背景、記憶體壓力或 versionchange）後，下一次讀寫自動重新連線，不再需要重新整理才能存取離線待送跑步與草稿（SPEC-037）。
- 瀏覽器測試的非同步等待改用 `waitForAsync`：Playwright `waitForFunction` 不會等待 async predicate，造成 WebKit 離線佇列測試間歇失敗；新增防回歸檢查。
- PWA 測試：失敗升級後先把 fixture 回復到已安裝版本並等候背景更新與流量結束才模擬斷線；改用 `serviceWorker.ready`；WebKit 偶發（約 1/70）更新佇列永久卡住且未送出請求時，於新瀏覽器重試一次（第二次或已送出未完成仍失敗）。
- Asset 4.0.3／shell v43；schema 6 不變，無資料 migration。

## [4.0.2] - 2026-11-05

### Changed
- 應用時區與「今天」集中於 `backend/clock.py`，取代 8 處各自寫死的 UTC+8；行為不變。
- 統計用四捨五入集中為 `backend/read_models/rounding.py` 的 `round_metric`，取代 4 份重複的 `_round`；輸出數值不變。
- Asset 4.0.1／shell v42 與 schema 6 不變，前端無需更新，無資料 migration。

## [4.0.1] - 2026-11-04

### Security
- AI 回覆與月報的 Markdown 改在 inert document 解析並以屬性 allowlist 清理，修正 `<img onerror>` 可在清理前執行的 XSS（SPEC-036）。
- 已超過自身上限的 IP／帳號不再消耗全站登入與 AI 額度，避免單一來源讓所有人無法登入。
- 新密碼至少 8 字元；同一帳號 15 分鐘內密碼錯誤 10 次後暫停登入與改密碼；不存在的帳號也執行 bcrypt，避免以回應時間推知帳號。
- 非預期的模型錯誤不再把例外原文傳給瀏覽器。

### Fixed
- 鎖定檔改為跨平台編譯：`uvloop` 只在非 Windows 安裝，並鎖定 Windows 需要的 `colorama`；Windows 可直接執行 `task.py setup`。
- Asset 4.0.1／shell v42，schema 6 不變。

## [4.0.0] - 2026-10-25

### Changed
- 資料與同步依狀態顯示操作；草稿、備份、歷史與本機清理區預設收合。
- PWA 偵測到新部署後會自動載入最新版，不再顯示確認更新提示。
- 跑步紀錄及鞋款選單移除使用者無法辨識的資料庫數字編號。
- Asset 4.0.0／shell v41，schema 6 不變。

### Release status
- 目前上線測試的穩定版；預期不再特別調整。

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

## [3.10.4] - 2026-10-25

### Fixed
- 來源網站復原手動跑步後再搬移，保留同一紀錄身分，不再重複計算跑量。
- 相同小數里程備份不因浮點尾差誤判更新；新的累積值保持兩位精度。
- 手動同步、前景與另一分頁提交後重新讀取雲端，保持未送出輸入與帳號隔離。

### Changed
- 帳號下載使用 archive v3，附有界、原生來源的跑步 aliases；仍讀取 v1/v2 並保留舊指紋。舊 App 需更新才能匯入 v3。
- Asset 3.10.4／shell v39，schema 6 不變。

## [3.10.3] - 2026-10-25

### Fixed
- 同帳號備份不再重建已刪除跑步；明確復原後保留所有來源別名，後續匯入可正確更新。
- 離線佇列每次送出使用獨立租約，舊請求不再覆寫重新登入後的同步狀態。
- 同步及誤刪復原區分提交成功與畫面刷新失敗，復原可單獨重試讀取。

### Changed
- 抽出跑步來源身分 service 與共用核心資料刷新驗證，補上組合流程回歸及使用指南。
- Asset 3.10.3／shell v38；schema 6 不變。

## [3.10.2] - 2026-10-24

### Fixed

- 匯入提交與畫面刷新分離；刷新失敗提供只讀重試，舊視窗／帳號的回呼不會改寫新狀態。
- 帳號匯出與匯入共用契約、集合與 20 MiB 限制，超限明確拒絕，不再產生無法匯入的檔案。
- 下載預設包含歷史，可明確取消歷史並於檔名／畫面揭露；不靜默截斷業務資料。
- 匯入計畫包含實際欄位差異及最終里程，預覽與執行共用，區分新增、實際變更、相同及保留刪除。
- 跑步月曆移除鞋款旁的次數文字，保留鞋款、每日里程與日期操作。

### Changed

- 新增 query-free `account_import_changes.py`，executor 只套用計畫 patch；時間比較、里程投影與差異統計集中。
- Asset 3.10.2／shell v37，schema 6 不變、51 個 release assets。

## [3.10.1] - 2026-10-24

### Fixed

- 非同步本機清除綁定 session 與操作，舊成功／失敗不修改新帳號，等待期間新輸入與編輯草稿保留。
- 匯入只更新有差異的欄位與里程，無變更／額外紀錄不增加版本、revision 或異動，避免假衝突。
- 每份預覽使用獨立 token，較早請求晚完成不再覆蓋最新預覽。關窗／過期回收，最多每人 8 份、合計 64 MiB。

### Changed

- 匯入規劃／來源辨識與寫入分離，預覽與套用共用計畫；交易與回執仍由 application service 管理。
- 原生 account restore controller 注入 session、transport 與 key，DOM bridge 只呈現；新增本人預覽 DELETE。
- Asset 3.10.1／shell v36、51 個 release assets；schema 6 僅調整預覽主鍵，保留現有 token。備份、升級與回滾步驟見 README／SPEC-030。

## [3.10.0] - 2026-10-24

### Added

- 帳號資料下載與匯入 UI 明示目前網站／帳號、來源與匯出時間。保留只新增模式，新增 v2「新增並更新同來源資料」，可更新先前匯入的鞋款、跑步、月份調整、目標及月報，保留額外資料與已刪除跑步。
- 繁體中文使用指南，說明雲端下載→本機版登入→選檔與模式→預覽→確認匯入，以及瀏覽器暫存與本機版資料庫的差異。

### Fixed

- 立即同步顯示空清單、離線、未就緒、進行中、完成及待處理結果，舊帳號完成不污染新帳號。
- 帳號資料下載在資料與同步視窗顯示進度／結果／錯誤，不再把失敗訊息放到隱藏的匯出視窗。
- 匯入更新後由後端重新彙總里程，支援跑步換鞋／換月份，並撤銷被更新月報的舊生成資格。

### Changed

- 預覽模式與內容共同綁定 hash、本人 revision 與操作回執；預設 merge 及舊預覽相容，update 僅接受 v2。
- Asset 3.10.0／shell v35，維持 schema 5 與 50 個 release assets；回滾可部署 v3.9.0 image，無須修改資料庫 schema。

## [3.9.0] - 2026-10-24

### Added

- SPEC-027：依帳號保存表單與編輯版本、最近資源快照；側欄「資料與同步」可恢復／捨棄草稿及清除目前帳號的本機資料。
- 新增跑步的 IndexedDB 同步佇列，原子消耗對應草稿、多分頁 lease、相同操作重播、登入過期暫停及明確刪鞋配對；離線重開可保留。
- 帳號備份 v2 及 v1 相容匯入：有界驗證、本人預覽、revision 檢查、來源 mapping、保留既有內容及一次交易合併；同檔／來源重複不重建。
- SQLite 同交易異動事件、本人歷史分頁及防衝突誤刪復原；匯入歷史唯讀，復原同步重算里程與配額。

### Changed

- 原生 workspace controller 注入 storage／session／transport，IndexedDB 與 DOM adapters 分離；移除年度、目標、洞察舊快取鏡像。
- 新 `/api/operations` 統一身分、版本與回執；既有 HTTP adapters 保持相容，錯誤補機器可讀 code。Schema 5 增加 metadata／歷史／mapping，run／month 主鍵不重用。
- README、SPEC-027、ADR-0010、SDD、測試策略與 harness 同步；Asset 3.9.0／shell v34、50 assets；本機驗收 508 Python、124 Node、94.66% 後端分支覆蓋率，包含 40 組版面與雙引擎 E2E／PWA，沒有 browser skip。正式 migration 須先完成備份與隔離還原，部署後執行匿名 release-check。

## [3.8.0] - 2026-10-23

### Fixed

- 新增跑步選定鞋款遭刪除後保留「請重新選擇」，重繪不默默改記其他鞋款。
- 鞋款／月跑量行內編輯保留 DOM、草稿與顯示列快照；背景來源、主題與跨日重繪不自動提交部分數字，明確提交仍檢查原版本。
- 月報以最新開始的生成身分驗證保存，舊請求不能覆蓋新內容與統計；失敗／取消保留之前成功報告。
- Strava 匯入期間停用配對，失敗只解鎖同一視窗；延後資源 dispatch 在發送前拒絕過期 session。

### Changed

- 依來源失效相依分頁；年度彙總、目標進度與洞察讀取由 resource store 合併 pending／快取與拒絕過期結果，格式錯誤可重試。
- 月報 application service、條件持久化、統計、LLM adapter 與 SSE 分離；月報 router 納入交易邊界檢查。
- Schema 4 僅新增 user／月份最新身分表，不改寫既有報告／里程；同步 README、SPEC-025／026、ADR-0009、SDD、測試策略與 rollback。
- Asset 3.8.0／shell v33，45 個 release assets；驗收基線為 475 Python、113 Node，完整 browser／CI 與部署證據見 GitHub Release。

## [3.7.2] - 2026-10-23

### Fixed

- v3.7.1 tag E2E 發現首次月跑量 panel 的延後 render 可能在使用者輸入後才建立 goal baseline，把 180 覆蓋回 125。現在切換分頁時先同步準備表單，再延後繪製圖表。
- Node 回歸與雙引擎 E2E 固定暫停第一個 panel frame，驗證先輸入／失焦、釋放 render 及晚到 server goal 仍保留草稿；不以重跑通過取代修正。
- Asset revision 3.7.2／shell v32，schema 3、44 個 release assets；v3.7.0／v3.7.1 tags 保留原始內容。
- 本機 verify：464 Python、106 Node；雙引擎 E2E／PWA 及匿名 44 資產 release-check 通過。

## [3.7.1] - 2026-10-23

### Fixed

- v3.7.0 main PWA CI 在 WebKit 的 worker script request 逾時，尚未建立 installing candidate。離線 fixture 改以 HTTP 503 結束背景 register/update，避免 TCP drop 後的重試阻塞 scope job queue。
- 每次恢復在線前驗證 offline registration.update 在 10 秒內失敗，再驗證後續候選更新；保留完整離線 shell、API exclusion、failed upgrades 與 recovery 測試，沒有放寬 deadline 或定向重跑取代修正。
- Asset revision 3.7.1／shell v31；schema 3、44 個 release assets。原 v3.7.0 tag 不改寫。
- verify-all 全數通過：464 Python、105 Node、95.29% backend branch coverage、40 組版面、雙引擎 E2E／PWA 無跳過。

## [3.7.0] - 2026-10-23

### Fixed

- 編輯已刪鞋款日誌跨日刷新仍要求重新選鞋，避免隱性轉移里程。
- Strava 舊匯入成功／失敗不修改替換視窗或新預覽，歷史舊 GET 不覆蓋新匯入結果；同視窗新預覽也不會重複提交。
- 鞋款現役／退役保留操作前與等待期間的未儲存暱稱等欄位，再儲存使用新版本且不撤銷狀態。
- PWA installer 拒絕長度不符的未壓縮 body，防止 WebKit 將截斷資產當作成功並啟用不完整 shell。

### Changed

- 原生 Strava controller 管理視窗、預覽／匯入 operation 與注入 transport/session，歷史納入 resource store。
- 各來源完成即套用並呈現，慢來源不再阻擋可用資料；獨立錯誤、session／request ownership 與精準失效保留。
- 單鞋／批次分析改 SQL 聚合與每鞋 recent12，固定三次 detail queries；AI 摘要只讀 aggregate，不載入完整 Run history。
- PWA observer 涵蓋已在 installing 的 candidate，update／終態共用 deadline，失敗附 worker timeline、fixture 階段與最近 HTTP 請求。
- 同步 README、SPEC-024／025、SDD 主圖、ADR-0008 與測試策略；asset revision 3.7.0／shell v30，schema 仍為 3。
- 本機 verify-all、最新 frontend-test 及 Agent eval 通過：464 Python、105 Node、95.29% backend branch coverage；40 組版面、雙引擎 E2E／PWA 無跳過，10 個 Agent evals 通過。

## [3.6.1] - 2026-10-23

### Fixed

- 鞋款移至退役／現役成功且保留新草稿時，同步模式、月跑量與版本；再次儲存只提交 dirty fields，避免撤銷狀態轉移。
- 目標以草稿 baseline 保護失焦、主題重繪及儲存期間的新修改，換帳號重設。

### Changed

- 原生 resource store 管理 session／request ownership、同資源讀取合併、獨立錯誤與快取失效；core 僅組合 readers、套用結果及呈現。
- WebKit PWA 離線 API probe 在 headers 後截斷 HTTP body，完整讀取 JSON 並檢查 server 計數；probe／worker update 各有期限，避免 fixture TCP 中斷後裸 fetch 長期 pending。
- Layout／CRUD／PWA 拆成獨立 CI jobs，加入階段 deadline、先落檔的原始錯誤、限時 trace／screenshot／close 與外層程序 watchdog。
- 新增 SPEC-024／ADR-0007、雙引擎草稿操作與卡住的 diagnostics／子程序回歸；同步 README module map、SPEC-023 狀態轉移追蹤與測試策略。
- 發布資產 revision 3.6.1／shell v29；schema 維持 3，沒有資料 migration。
- 本機 verify-all：462 Python、95 Node、95.26% backend branch coverage；40 組版面、雙引擎 E2E／PWA 無跳過，10 個 Agent evals 與合成 diagnostics 驗證通過。

## [3.6.0] - 2026-10-23

### Fixed

- 月跑量新增比對完整年月／里程草稿與操作身分；舊回應不清除新草稿或解鎖替換操作。
- 跑步／月跑量／鞋款編輯保留等待期間的新草稿，成功後更新可重用的 CAS 版本。
- 同款鞋選單改用暱稱、購買日期及 ID 辨識；暱稱持久化、輸出 escaping，CSV／XLSX 及帳號備份保留。

### Changed

- 原生 form operations 共用 session、epoch、ownership 與快照；依 mutation 精準重讀資源、清除相關快取並拒絕過期結果。
- 認證與目標寫入移入 services，純 credentials primitives 不依賴 HTTP；architecture gate 納入 auth／goals routers。
- 新增 schema 3 nickname additive migration；使用 asset revision 3.6.0／shell v28。
- 新增 SPEC-023／ADR-0006、具名測試追蹤、CI 合成 diagnostics 產生→上傳→下載驗證，README／SDD／測試策略同步。
- 本機 verify-all：458 Python、88 Node、95.26% backend branch coverage；40 組版面及雙引擎 E2E／PWA 無跳過，Agent evals 10 個通過。

### CI

- Browser job 使用與 lockfile 相符的 Playwright noble container，避免 Ubuntu mirror 下載拖過 job timeout；完整 layout／CRUD／PWA gates 保留。
- 失敗診斷明確包含 hidden files，上傳範圍限制在 .artifacts/browser/。
- 新增 SPEC-022、CI runtime／診斷契約回歸；保留既有 v3.5.1 image 與 tag 不變。

## [3.5.1] - 2026-10-22

### Fixed

- 改密碼以原 hash／登入版本作條件原子更新，過期並行請求回 409，避免覆寫新密碼與漏撤銷憑證。
- 註冊改以 SQLite writer reservation 保護同名／容量檢查與新增，空資料庫及跨程序均適用。
- README 的 shell／worker 資產數量更新為 40；docs-check 以 manifest 推導數量，阻擋後續漂移。

### Documentation and testing

- 新增 SPEC-021 並更新 SDD／ADR／TDD；新增重疊改密碼、spawn process 註冊容量／同名及文件數量負例。
- 核心修正 verify-all 通過：449 Python、81 Node、95.21% backend coverage；40 組版面及雙引擎 E2E／PWA 無跳過。
- 修補版使用 asset revision 3.5.1／shell v27，schema 維持 2。

## [3.5.0] - 2026-10-22

### Fixed

- 延遲的新增跑步成功回應保留等待期間的新日期、里程、鞋款與查看月份；同內容失敗重試沿用 key。
- 鞋款／日誌配額在 SQLite writer reservation 後驗證，跨 thread／process 並行不再突破上限。
- App factory 的 CRUD／註冊／Strava 配額與 upload guard 使用注入設定，不再由 router import-time 常數決定。

### Changed

- 跑步、鞋款、月跑量的 transaction／quota／version／mileage 移入 application services；HTTP adapter 統一轉換 domain errors。
- 原生 run controller 收斂明細、分頁、年度 cache、editor 與新增操作 state，明確注入 transport／session／key factory，boot 與 PWA manifest 整合。
- 日期區間統計共用 read model；月報月份、上月同期、YTD 一次 SQL conditional aggregate，重用於目標進度。
- Schema 維持 2；PWA shell v26／asset revision 3.5.0，與 v3.4.0 資料相容。

### Security

- Docker context 排除 SQLite WAL／SHM、DB 備份與 backups 目錄，防止遠端建置帶入工作區資料。

### Documentation and testing

- README 更正年度彙總說明，新增 SPEC-020／ADR-0005，更新 SDD／TDD／harness map。
- docs-check 驗證本地連結／anchor、spec sections／Owner／狀態、Implemented AC completion 與 traceability 測試檔；補齊早期規格章節並修正不存在的測試引用。
- 新增 thread／spawn process quota、app settings isolation、共享統計 query budget、native controller／DOM 草稿及雙引擎延遲 POST 回歸。
- 本機 verify-all／最終 verify：444 Python、81 Node、95.14% backend coverage；Agent eval 10 passed，40 組版面、雙引擎整合／PWA 均實際執行。

## [3.4.0] - 2026-10-22

### Fixed

- 跑步月份／分頁載入失敗後成功重試會清除自己的錯誤，不掩蓋全域資料載入失敗。
- 同源跨分頁登入／登出／換帳號立即清理舊資料與 pending JSON requests，不刪除其他分頁的新憑證。

### Added

- JSON CRUD／登入 deadline 與 GET 一次有限重試；新增日誌 Idempotency-Key 使用持久化、user-scoped transaction receipt，人工重試／並行重送只累計一次里程，內容衝突回 409。
- 年度每月／每鞋彙總 API，年度圖表不再分頁下載逐筆日誌。
- `release-check --base-url` 固定檢查完整 API、schema、39 個資產 hash／MIME、匿名雙引擎 boot/runtime/cache 與 Chromium 離線重開；E2E 先在真實 ASGI/CORS／暫存 SQLite 執行。

### Changed

- Schema 2 只新增 run_creation_requests，附備份與舊版 rollback marker 相容步驟；舊 API 無 key 仍相容。
- Playwright 1.63.0／npm lockfile 與 npm ci；失敗截圖、trace、錯誤輸出由 CI 保存；Docker context 排除本機 secrets／診斷／npm dependencies。
- PWA shell v25／asset revision 3.4.0；更新 SPEC-019、ADR-0004、SDD、TDD、README 及 harness。

### Testing

- 424 Python／78 Node／10 Agent eval、94.63% branch coverage；40 組排版、兩引擎 CRUD／session／跨分頁／PWA 與真實 ASGI/CORS release gate 通過，沒有跳過瀏覽器。
- 並行相同／衝突 key、quota replay、失敗 transaction、user isolation、schema 1→2，以及錯版本／hash／MIME／schema／API／匿名授權／browser failure 負面測試。

## [3.3.1] - 2026-10-21

### Fixed

- 修正正式站 CORS 的 `Vary: Origin` 造成原生模組離線載入失敗：僅公開同源 shell cache 查詢忽略 Vary，仍精確比對 URL／版本且排除 API。
- 發布 PWA shell v24／asset revision 3.3.1，保留已發布 v3.3.0 tag，不重用有問題的舊快取名稱。

### Testing

- 先以正式站同樣的 CORS response headers 重現離線啟動失敗，再由 Chromium／WebKit PWA regression 驗證修正；新增 SPEC-018，保留失敗升級、版本隔離及 API 不快取測試。

## [3.3.0] - 2026-10-21

### Security

- 發布稽核發現 CA bundle 漏洞，鎖定 certifi 2026.10.19 並重新生成正式／開發依賴雜湊，修補 [PYSEC-2026-4320／GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。

### Fixed

- 月跑量空白不再覆寫成零，目標頁與首頁／月報統一只計日誌；跨日更新日期限制且保留目前草稿。
- 刪鞋後年度堆疊圖保留歷史日誌；同名鞋款須消歧義並可用 user-scoped ID 選定。
- 平均月支出改由後端日曆年月計算，不受瀏覽器時區影響；新增跑步晚到回應不污染新帳號。
- 彈窗補齊焦點、Tab／Shift+Tab、Escape 與 aria 語義，修正背景 inert 導致無法返回焦點。

### Changed

- 共用 read models 與 shoe metrics 統一 API／工具／月報／匯出規則；批次鞋款分析消除 N+1。
- 新增日誌整月 summary、目標 progress、支出 summary API；明細每頁 200 筆，月曆／統計完整不截斷。
- 支出按需載入及局部重試；Strava 解析領域錯誤由 router 映射 HTTP，月報不再解析 AI 工具 JSON。
- 各功能註冊生命週期清理，原生 ES module runtime 由相容橋接載入；CSS、彈窗模板、模型、Markdown、工具 schema／parser 與 Node tests 依責任拆分。
- HTML／單一 CSS／PWA 清單由 assets manifest 生成並由 harness 驗證；shell v23 包含 native module MIME 檢查與非強制更新提示。

### Testing

- SPEC-017／ADR-0003 與架構／測試圖更新，新增統計不變量、身份歧義、query budget、跨日、完整分頁及兩引擎鍵盤流程。
- 架構檢查追蹤 transitive／relative imports，防止 service/read models 間接依賴 HTTP 或 AI adapters。

## [3.2.5] - 2026-10-20

### Fixed

- 全前端表單、日期／月份欄位、模型工具列與操作按鈕共用尺寸及行高；修正 WebKit 長選單溢出。
- 彈窗次要／主要操作明確分組，桌面等高對齊、手機換行不留下 spacer；保留新增、現役／退役編輯與停用行為。
- 表格數字與表頭統一右對齊及等寬數字，修正可編輯格的邊界；圖表標題與繪圖區起點、卡片文字節奏一致，跑鞋／支出六張摘要採平衡的三欄或兩欄排列。
- 補齊欄位 label 對應，修正跑鞋分析／Strava 彈窗被通用寬度覆蓋；PWA revision 3.2.5／shell v22。
- 月報狀態與產生按鈕保留間距，已儲存訊息不再顯示錯誤紅色，真正失敗仍有明確錯誤樣式。

### Testing

- 排版矩陣擴為 40 組（雙引擎、亮暗及 10 組尺寸），遍歷六個功能分頁、三個認證表單、全部彈窗及新增／編輯／錯誤／停用／行內輸入。
- 新增控制項、按鈕、工具列、圖表與數字欄位幾何斷言；啟動畫面測試改用明確 gate，避免固定延遲的競態。更新 SPEC-016、SDD、README 與測試矩陣。

## [3.2.4] - 2026-10-20

### Fixed

- 跑步日誌固定為首頁：重新整理、重新開啟與瀏覽器快取還原不再回到上次的 AI 助手或其他分頁。
- 移除分頁持久保存，保留本次使用的正常切換、登入狀態與主題偏好；一般前景／背景切換不強制切頁。
- 更新 PWA asset revision 3.2.4／shell v21，新增啟動、手機標籤／ARIA、重開及 PWA 離線導航回歸測試與 SPEC-015。

## [3.2.3] - 2026-10-20

### Added

- Fly 外部備份 CLI：下載一致 SQLite 快照與 checksum，private staging 驗證及隔離還原通過後才發布完整備份與 manifest；拒絕 Git 目錄，不自動刪除本地備份。
- `database_backup.py drill`：隨機 OS 暫存目的地，比對完整 schema、ordered row digest、各表筆數與 schema version，不接受正式還原目的地。
- `frontend-pwa`：以真正 Chromium／WebKit Service Worker 測試舊版線上 migration、HTTP／MIME 失敗更新、已安裝 shell 離線啟動、恢復更新、API 排除與 scoped cleanup，納入 verify-all／CI。

### Fixed

- PWA navigation 不再將新 HTML 寫入舊版 cache；完整資產安裝成功才接管，失敗保留舊 shell，僅清理本 app cache。
- PWA 安裝逐一讀完資源 response body，避免有限連線池被未消耗的串流佔滿；驗證資源 MIME 與 HTML revision。
- PWA asset revision `3.2.3`、shell v20，確保新版 HTML 與資產一起更新。

## [3.2.2] - 2026-10-20

### Fixed

- 登入／註冊／更改密碼加入共用操作鎖、取消與過期回應隔離；舊請求不能覆蓋新帳號或 loading 狀態。
- 跑鞋新增、編輯、刪除與移動以視窗 context 保存版本及 session，防止重送和晚到回應關閉新草稿。
- 月報 GET／歷史／串流統一輸出帶時區 UTC，讀取與生成都使用同一本地時間格式。

### Changed

- Strava 上傳後的 CSV／filter／DB service 工作移入 worker thread，保留原交易與帳號隔離。
- 拆出匯出、目標設定、跑鞋圖表與月跑量圖表，保留 plain-script 契約與原版面。
- PWA shell v19、asset revision 3.2.2 納入四個新增 modules。
- 新增 SPEC-013，更新 SDD、harness module 清單與 Node／Python／雙引擎回歸測試。

## [3.2.1] - 2026-10-20

### Fixed

- 跑步／月跑量編輯保存原始 ID、版本及 session，避免資料重新載入後修改錯筆或覆蓋較新內容；提交鎖與回應更新以視窗為單位。
- AI 串流只有成功 done 才保存完整對話；錯誤、提前 EOF 或連線中斷保留可見內容並提供重試，不污染歷史。
- 清單、退役時間軸與單鞋分析共用後端預估及來源，批次查詢不產生逐鞋 N+1。

### Changed

- 抽出 `app-streams.js`，共用認證 SSE 檢查、解碼、取消及 terminal state。
- 圖表按 active panel 載入、快取及失效，資料／主題更新不重畫隱藏分頁；年度跑步資料按需載入。
- PWA cache v18、asset revision `3.2.1` 納入新 module，避免混用舊版 shell。
- 新增 SPEC-012、模組圖、回歸追蹤矩陣與 deterministic Node／SQLite／雙引擎 browser 測試。

## [3.2.0] - 2026-10-19

### Changed

- 現役與退役跑鞋清單移除尺寸、買價、原價、折數四欄，保留使用指標與分析／編輯操作。
- 支出明細新增尺寸，集中呈現購鞋資訊；既有資料、編輯表單、匯出及成本計算保持不變。
- 無尺寸或無原價時以「—」呈現，不再顯示無意義的「—%」。
- 靜態資產版本更新為 3.2.0，PWA app shell cache 更新為 v17。

### Documentation

- 新增 SPEC-011，更新呈現責任說明、README、測試矩陣及欄位／資料持續性回歸測試。

## [3.1.0] - 2026-10-19

### Fixed

- SQLite 還原改用獨占鎖與 backup API，避免殘留 WAL 重播舊資料；拒絕忙碌目標、保留安全快照並驗證還原結果。
- 洞察快取綁定登入 session，登出清空快取與畫面，拒絕上一帳號的延遲分析回應。
- 登出中止 AI 串流、清除對話與重試內容並解鎖輸入，防止舊串流污染下一帳號。
- 統一認證回應與 body 的 session 檢查，舊請求 401 不再清除新登入；目前 session 過期仍正常登出。

### Changed

- 靜態資產版本更新為 3.1.0，Service Worker app shell 更新為 v16。
- 新增 WAL crash／busy restore、HTTP 競態與 Chromium/WebKit 帳號切換回歸測試。

### Documentation

- 新增 SPEC-010、session 隔離時序圖，更新備份操作、測試追蹤矩陣與驗證基線。

## [2.14.0] - 2026-10-19

### Changed

- 將前端啟動、state、API、認證、跑步洞察與 Strava UI 拆成獨立 module，保持 plain-script 載入與既有互動相容。
- 將 Strava upload router、匯入 transaction 與 run CRUD 分離。
- 將 analytics、exports、spending HTTP routes 分離，CSV／XLSX／帳號備份生成移入 framework-independent service。
- 將 Agent query planner、tool dispatcher、SSE protocol 與 runner 分離。
- Service Worker app shell 升級為 v11，納入所有新增前端 module。

### Documentation

- 新增 SPEC-006、前端 module 圖、PWA／Fly runtime 圖與集中式 changelog。
- 補齊 v2.13.0 的 app factory／typed settings release history。

## [2.13.1] - 2026-10-19

### Fixed

- 讓 PWA 啟動畫面在舊快取與冷啟動時更早出現。
- 登出與重新登入時清除帳密欄位，避免不同帳號共用裝置時殘留表單內容。

## [2.13.0] - 2026-10-19

### Added

- 新增 PWA 冷啟動 loading、逾時與重試狀態。

### Changed

- 導入可注入的 FastAPI app factory、typed settings 與最小 ASGI entry point。
- 將所有 HTTP endpoints 收斂至 feature routers，`backend/main.py` route budget 降為零。

## [2.12.0] - 2026-10-18

### Changed

- 強化資料載入、API 邊界、工程 harness 與架構驗證。


