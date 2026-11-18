# 版本說明

各版本上線時的行為變更、資料相容性與回滾說明，依版本由新到舊排列。
每版的摘要見 [CHANGELOG.md](../CHANGELOG.md)；目前的功能與操作方式以 [README](../README.md) 為準。
這裡保留當時的文字，後續版本可能已調整其中的行為。

### 自訂邀請碼（SPEC-076，v4.20.1）

- 註冊表單的提示「例如 K7QM-3XPA」看起來像真的邀請碼，改為「向管理員索取」。
- `InviteCreate.code` 選填：`invites.create_invite` 去掉空白與符號、轉大寫，接受 4～20 個 ASCII 英數字，重複回 409；`redeem_invite` 接受同樣的長度範圍。自訂碼仍只存 SHA-256，面板提醒自訂碼比較好猜。

Asset 4.20.1／shell v82、schema 11 不變，可直接回滾至 v4.20.0 image；舊版只接受 8 碼，自訂碼在回滾期間無法使用。

### 邀請制註冊與帳號管理（SPEC-075，v4.20.0）

- 註冊先前對所有人開放（上限 100 個帳號）。`REGISTRATION_MODE` 預設為 `invite`，無法辨識的值一律視為 `closed`；`GET /api/auth/registration` 讓註冊表單決定是否顯示邀請碼欄位。邀請碼 8 碼（排除 0／O、1／I／L），只存 SHA-256；註冊在同一個交易扣用，失敗的註冊不會用掉邀請碼。
- 管理員由 `ADMIN_USERNAMES`（Fly secret）決定，`routers/admin.py` 對其他帳號回 403。管理員可產生、查看、停用邀請碼，並以 `accounts.admin_reset_password` 產生臨時密碼（同時讓對方的 token 失效），在 email 找回密碼完成前先用這個方式協助。
- `accounts.delete_account` 重新檢查密碼（打錯回 400，不會被當成登入過期而登出），在單一交易內依 metadata 由子表到父表刪除所有含 `user_id` 的資料表，最後清掉刪除時產生的稽核紀錄與使用者本身。邀請碼不屬於任何帳號，刪除管理員帳號不受影響。
- 帳號名稱不分大小寫：`accounts.find_user` 以 `lower(username)` 查詢，schema 11 在沒有大小寫重複時加上唯一索引；登入失敗鎖定以 case-fold 後的名稱計算。
- AI 每個帳號每天的預設上限 50 → 20 次。登入與註冊頁新增隱私說明。

Schema 11。回滾：停止寫入並備份後執行 `scripts/rollback_schema_eleven.sql`（保留 `invites`、移除名稱索引），再部署 v4.19.4 image；舊版會恢復開放註冊。

### 登入耗用的 CPU 與 Strava 上傳記憶體（SPEC-074，v4.19.4）

- bcrypt cost 12 在本機每次約 0.2 秒，Fly 共用 CPU 更慢。原本登入、註冊、改密碼的全站上限每分鐘 300 次，等於每分鐘 60 秒以上的 CPU；預設改為每個 IP 20 次、全站 60 次。被攻擊時正常使用者可能要等一分鐘才能登入。
- `routers/strava.strava_upload_slot()` 比照備份還原的 `restore_slot`，每個程序同時只解析一個 Strava CSV，忙碌立即回 429（`Retry-After: 5`）；取得之後才消耗 `enforce_strava_upload_limits()` 的帳號視窗（預設每分鐘 10 次）。

Asset 4.19.4／shell v80、schema 10 不變，可直接回滾至 v4.19.3 image。

### 被大量請求灌爆時的防護（SPEC-073，v4.19.3）

- 先前只有登入、註冊、AI 與備份預覽有頻率限制。`middleware.ApiRateLimitMiddleware` 現在對每個 `/api/` 請求檢查來源位址每分鐘的上限（預設 600），在驗證、session 與路由之前回 429；計數放在記憶體（`ApiRequestLimiter`，最多 10,000 個位址），不寫 SQLite，避免灌爆時每個請求都要搶唯一的 writer。靜態檔、首頁與健康檢查不受限。
- `fly.toml` 新增 `[http_service.concurrency]`（requests，soft 25／hard 50），超過時由 Fly 代理排隊或拒絕，不讓唯一一台 256 MB 機器被湧入的請求用光記憶體。
- `client_address` 從 `rate_limits` 移到 `middleware`，兩種限流用同一個位址判斷。

Asset 4.19.3／shell v79、schema 10 不變，可直接回滾至 v4.19.2 image。

### 過去年份的圖表看得到全年（SPEC-072，v4.19.2）

- 年度月跑量對比先前把沒有月跑量資料的月份當成空白（`spanGaps: false`），2024 年從 9 月才有資料時，線只從 9 月畫起。`yearOverYearSeries` 依 `localDateISO()` 判斷已開始的月份：過去的年份 12 個月都補 0，今年補到本月，之後的月份與未來年份仍為空白。
- 每週跑量與每週最長一次先前固定是年份最後 16 週。`GET /api/analytics/trends` 新增選填的 `weeks_end`，`trends.weekly_window` 把視窗限制在這一年內並回傳 `weekly_window: {end, has_earlier, has_later}`；前端兩張圖共用「‹ 較早／較晚 ›」，換年份時回到最近 16 週。AI 工具仍取最近 16 週。
- 只有今天所在的週叫「本週」；過去年份被 12/31 截斷的最後一週在提示框標示「只算到 12/31」，說明文字不再出現「本週 0.0 km」。

Asset 4.19.2／shell v78、schema 10 不變，可直接回滾至 v4.19.1 image。

### 公開站台的 AI 每日額度與防護補強（SPEC-071，v4.19.1）

- 註冊開放（上限 100 個帳號），AI 先前只有每分鐘限額，任何帳號都能整天呼叫並消耗 OpenRouter 額度。現在 `rate_limits.enforce_agent_request_limits` 在同一交易再消耗每帳號（預設 50）與全站（預設 200）兩個 24 小時視窗，滿了回 429 並附 `Retry-After`。限流桶的保留時間從 1 小時改為 24 小時，模型刷新冷卻上限維持 3600 秒。
- 正式環境的 `create_app` 不再掛載 `/docs`、`/redoc`（回 JSON 404）；`/openapi.json` 保留，因為 `release-check` 用它比對部署後的路由契約。
- `SECURITY_HEADERS` 新增 `Strict-Transport-Security: max-age=31536000; includeSubDomains`。
- 密碼至少 8 碼與登入失敗鎖定（同一 IP 對同一帳號 15 分鐘 10 次）原本就有，這版不變。

Asset 4.19.1／shell v77、schema 10 不變，可直接回滾至 v4.19.0 image。

### 跑步里程與跑鞋里程分開顯示（SPEC-070，v4.19.0）

- 跑鞋分頁的「總里程」是所有跑鞋里程的合計，包含記在鞋上的步行與健行（例如 2,827.4 km），和 Strava 個人頁的跑步總計（2,280.6 km）不是同一個數字，容易誤會。
- 新增 `GET /api/runs/totals`（`run_count`、`total_km`），只讀使用者自己的跑步，包含已刪除鞋款上的跑步（刪鞋不刪跑步）。跑鞋分頁的「跑步里程」卡顯示這個合計與筆數；原「總里程」改名「跑鞋里程（含步行、健行）」，平均每 km 成本仍以跑鞋里程計算。
- 移除「需補鞋類別」卡（類別覆蓋仍在下方的類別摘要），摘要維持六張、兩欄三列的手機版面。跑步新增、編輯、刪除與 Strava 匯入後會重新讀取跑步里程。

Asset 4.19.0／shell v76、schema 10 不變，可直接回滾至 v4.18.4 image。

### 近 90 天沒穿的鞋不預估退役日（SPEC-069，v4.18.4）

- 退役預估先前在近 90 天沒有紀錄時一律改用計畫月跑量。對偶爾穿的鞋（例如一年只健行幾次的 Hierro v8，近 90 天 0 km），預設的 60 km／月會推算出明年就退役的日期，完全不合理。
- 現在 `forecasting.retirement_forecast` 區分兩種情況：有逐筆紀錄但近 90 天沒有 → `forecast_source: "idle_90_days"`，不給日期；從沒有紀錄的新鞋 → 仍用計畫月跑量。批次預估仍是一次查詢（同時算近 90 天里程與紀錄筆數）。單鞋分析、跑鞋清單、AI 工具共用同一結果。
- 只用 90 天判斷，不用 30 天：一個月沒穿的比賽鞋仍有近 90 天的實際月均可以參考。

Asset 4.18.4／shell v75、schema 10 不變，可直接回滾至 v4.18.3 image；`idle_90_days` 對舊前端會顯示成「依計畫月跑量」與「無法預估」。

### 跑鞋里程與 Strava 相同的捨去規則（SPEC-068，v4.18.3）

- 以實際 `activities.csv` 對照 Strava「我的鞋履」：鞋子里程是公尺欄位的合計，畫面無條件捨去到小數點第一位（Wave Sky 7 合計 673.352 km，Strava 顯示 673.3）。App 先前四捨五入，小數點第二位為 5～9 時會多 0.1。
- `floorShoeKm`／`formatShoeMileage` 以 `Math.floor(km × 10 + 1e-6) / 10` 捨去（微小的 epsilon 避免 4.35 這類二進位浮點數被多捨一位），套用到跑鞋清單、首頁總里程卡、單鞋分析的總里程、壽命圖提示與輪替時間軸。只改顯示，資料與 API 不變。
- 匯入早已讀公尺欄位（公里欄位被 Strava 捨去到 0.01），README 補上對帳規則與步行里程的處理方式。

Asset 4.18.3／shell v74、schema 10 不變，可直接回滾至 v4.18.2 image。

### 輪替時間軸顯示鞋子里程（SPEC-067，v4.18.2）

- 時間軸先前只顯示跑步紀錄的合計，和跑鞋清單的鞋子里程不同；差距是記在鞋上、但不在跑步日誌的里程，主要是 Strava 的「步行」活動（暖身、緩和），匯入只收跑步類型。`GET /api/analytics/shoe-timeline` 每雙鞋新增 `shoe_km`（鞋子里程）與 `other_km`（鞋子里程減跑步合計），提示框顯示「鞋子里程」與「跑步 … 次｜步行與暖身 …」；差距為零或負數時只顯示跑步。
- 跑鞋清單（現役與退役）的里程顯示到小數點第一位，和 Strava 的裝備清單一致；行內編輯仍使用完整的儲存值。

Asset 4.18.2／shell v73、schema 10 不變，可直接回滾至 v4.18.1 image。

### 手機數字鍵盤輸入時間（SPEC-066，v4.18.1）

- 時間欄位用數字鍵盤（`inputmode="numeric"`），但 iOS 的數字鍵盤沒有冒號，只能打出整數分鐘。現在輸入時會從右邊每兩位自動補冒號：`5421` → `54:21`、`15959` → `1:59:59`；刪除數字也會重新分組，貼上的 `1:05:30` 不變，一、兩位數仍視為整數分鐘。跑步新增、編輯與比賽目標的三個時間欄位都適用。

Asset 4.18.1／shell v72、schema 10 不變，可直接回滾至 v4.18.0 image。

### 比賽準備（SPEC-065，v4.18.0）

- 「訓練分析」的「配速分析」改為「比賽準備」。設定目標賽事（日期、距離、目標時間）與選填的參考成績（距離、時間、氣溫）後，顯示倒數、目標配速、預估完賽與差距、長距離準備與近 8 週強度分布。
- 預估完賽以 Riegel 公式 `T2 = T1 × (D2/D1)^1.06` 計算；參考成績在 25°C 以上時標示「涼爽時通常更快」。
- 強度以目標配速為基準：輕鬆慢 45 秒以上、穩定慢 15–45 秒、比賽配速快 10 秒到慢 15 秒、更快。以整次跑步的平均配速分類，有熱身或間歇的課表會落在較慢的區間。
- 長距離門檻是比賽距離的 75%，近 8 週建議至少 2 次；最後一次長距離建議在賽前 14 天前完成，之後的建議改為減量。
- 移除月跑量與配速、累積跑量與配速、距離與配速、配速分布四張圖；`GET /api/analytics/pace` 只回傳配速趨勢（有目標時每筆帶強度）。
- 比賽目標不在 JSON 帳號備份內，也不寫入異動歷史。

Asset 4.18.0／shell v71、schema 10（新增 `race_goals`）。回滾到 v4.17.1：停止寫入並確認 schema 10 備份可讀後，以 Python
`sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_ten.sql`](../scripts/rollback_schema_ten.sql)（守衛確認目前是 10，只把 marker 改回 9），
再部署 v4.17.1 image。`race_goals` 保留，schema 9 程式不讀寫它；再次升級後沿用。

### 分頁改名與作品集 README（v4.17.1）

- 「月跑量」分頁改名為「訓練分析」，「AI」分頁改名為「AI 教練」；內容、網址與資料都不變。
- README 前半改寫為作品集介紹，原有的操作、部署與 API 說明移到「使用與維運手冊」。

Asset 4.17.1／shell v70、schema 9 不變，可直接回滾至 v4.17.0 image。

### 配速分析（SPEC-064，v4.17.0）

- 月跑量分頁新增「配速分析」，涵蓋全部紀錄、不隨年份切換：配速趨勢、月跑量與配速、累積跑量與配速、距離與配速、配速分布 5 張圖，配速軸越上面越快。
- 平均配速以時間加權計算；跑量包含沒有時間的跑步。相關係數至少 8 個點才顯示，並說明「前 3 個月平均跑量」與當月配速的關係。
- 訓練趨勢的「星期幾跑量與配速」加上每個星期幾的平均配速折線（`/api/analytics/trends` 的 `weekday[].pace`），說明列出最快與最慢的星期幾。
- 新增唯讀 API `GET /api/analytics/pace`。

Asset 4.17.0／shell v69、schema 9 不變，可直接回滾至 v4.16.1 image。

### Strava 繁中匯出的時段用語（SPEC-063，v4.16.1）

- 解析器先前只認得「上午／下午」，「晚上 11:30」等時段讀不到時間而直接使用 UTC 日期，台灣清晨的跑步被記到前一天，SPEC-062 也因日期不同而無法和手動紀錄配對。現在認得午夜、半夜、凌晨、清晨、早上、上午、中午、下午、傍晚、晚上與 24 小時制時間。
- 已因此記錯日期的紀錄，重新匯入時由 SPEC-047 的日期修正移到台灣日期；若它和手動紀錄重複，請在網頁上刪除，刪除後不會再被匯入。

Asset 4.16.1／shell v68、schema 9 不變，可直接回滾至 v4.16.0 image。

### Strava 匯入辨識手動輸入的跑步（SPEC-062，v4.16.0）

- 先前 Strava 匯入只用活動 ID 判斷重複，手動輸入的跑步會被再新增一筆，跑鞋與月跑量變成雙倍。現在同一天只有一筆距離接近（0.3 km 或 5% 以內）的手動紀錄時，活動會連結到那筆紀錄（存入 Strava 活動 ID），並在沒有時間時補上移動時間；距離、日期、鞋款與既有時間都不改，里程不變。
- 同一天有手動紀錄但距離差太多，或同天多筆無法一對一時，活動不匯入也不連結，預覽顯示筆數與例子。只有連結、沒有新活動時也可以按匯入。
- 匯入歷史的「重複」筆數包含連結與略過的活動。

Asset 4.16.0／shell v67、schema 9 不變，可直接回滾至 v4.15.0 image；已連結的紀錄在舊版被視為已匯入的 Strava 紀錄，不會重複。

### 跑步時間與配速（SPEC-060，v4.15.0）

- 新增與編輯跑步時可以選填跑步時間（`32:15`、`1:05:30` 或整數分鐘），後端依時間與距離算出配速；配速每公里須在 1:00～60:00 之間。編輯時清空欄位會刪除時間。
- 跑步列表新增「時間」「配速」欄；月份總里程卡片與單雙鞋分析顯示平均配速，以總時間 ÷ 有時間紀錄的距離計算，沒有時間的跑步不列入。
- Strava 匯入讀取 `移動時間`（沒有時用 `經過時間`）。重新匯入同一份 CSV 時，預覽顯示「另有 N 筆既有紀錄會補上跑步時間」，匯入只補還沒有時間的紀錄，不覆寫已有的時間；距離被手動改到配速不合理的紀錄會略過。
- 帳號備份升為 v4，包含跑步時間；v4 無法由 v4.14.x 以前的版本匯入。合併匯入時，備份裡沒有時間的跑步不會清除既有時間。

CI 同時改為每次 push、每個 PR 與每週排程都跑完整測試（包括只改文件），`main` 只能透過 CI 全綠的 PR 合併（SPEC-061）。

Asset 4.15.0／shell v66、schema 9（`runs.duration_seconds`，既有資料為 NULL）。回滾到 v4.14.1：停止寫入並確認 schema 9 備份可讀後，以 Python
`sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_nine.sql`](../scripts/rollback_schema_nine.sql)（守衛確認目前是 9，只把 marker 改回 8），
再部署 v4.14.1 image。`duration_seconds` 欄位保留，schema 8 程式不讀寫它；再次升級後沿用已存的時間。

### 訓練趨勢的進行中週次與說明修正（SPEC-056 修訂，v4.14.1）

- 「每週最長一次」的近期平均只算已結束的週；本週還沒跑步時不畫 0 km 的點。每週跑量圖的 4 週平均也不為進行中的週畫點。
- 週目標說明列出「年度目標 ÷ 52.1 週」；星期分布以跑步次數計算平均每次距離。

Asset 4.14.1／shell v65、schema 8 不變，可直接回滾至 v4.14.0 image。

### 在安全時自動套用新版（SPEC-059，v4.14.0）

- 新版裝好後，App 在背景、剛回到前景還沒操作，或閒置 5 分鐘時自動換成新版，不必在每台裝置按「立即更新」。
- AI 正在回答、月報產生中、有彈窗或行內編輯開著、有請求還沒完成、AI 輸入框或登入表單還有文字時先等待；使用中的畫面仍顯示提示，可以馬上更新。
- 完成的 AI 對話存在分頁的 sessionStorage，重新載入（包括自動更新）後還在；關閉分頁、登出或換帳號就清除。
- 這個行為本身是新版程式：各裝置第一次升到 v4.14.0 時仍要手動更新最後一次。

Asset 4.14.0／shell v64、schema 8 不變，可直接回滾至 v4.13.0 image（回滾後恢復只提示、按了才更新）。

### 資料正確性、訓練分析與 AI 統計工具（SPEC-055～058，v4.13.0）

- 刪除 Strava 匯入的跑步時記住活動 ID（schema 8 的 `run_tombstones.strava_id`），重新匯入同一份 CSV 不會再建立那筆跑步或增加里程；預覽顯示「另有 N 筆先前刪除過的活動不會重新匯入」，要找回請從異動歷史復原。升級時從仍保留的刪除稽核紀錄回填，已被保留上限清掉的無法回填。
- 年度回顧在年份進行中時與前一年同期（1/1 到同月同日）比較；已退役的鞋不再有預估退役日期；換鞋提醒全站統一為 80% 注意、90% 準備換鞋；跑步日誌卡片顯示所選月份。
- 登入相關欄位改用標準 `autocomplete`，密碼管理器可以填入；登出與換帳號仍清空欄位。
- 訓練趨勢新增週目標虛線、每週最長一次與星期幾跑量；AI 助手新增目標進度、訓練趨勢、年度回顧與支出 4 個工具（共 12 個）。
- README 新增完整 API 一覽並由 `docs-check` 檢查；版本說明移到本檔。

Asset 4.13.0／shell v63、schema 8。回滾到 v4.12.0：停止寫入並確認 schema 8 備份可讀後，以 Python
`sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_eight.sql`](../scripts/rollback_schema_eight.sql)（守衛確認目前是 8，只把 marker 改回 7），
再部署 v4.12.0 image。`strava_id` 欄位與索引保留，schema 7 程式不讀寫它們；再次升級時會回填回滾期間刪除的活動。

### 安全標頭與文件一致性（SPEC-053／SPEC-054，v4.12.0）

- 頁面加上嚴格的 Content-Security-Policy：只允許同源 script，以及建置時以 SHA-256 雜湊放行的三段啟動 script（主題、樣式載入、開機逾時）。原本樣式表上的 inline `onload` 改為可雜湊的 script，離線頁改用不需 script 的「重新連線」連結。
- 所有回應加上 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`／`frame-ancestors 'none'`、`Referrer-Policy: same-origin`、`Cross-Origin-Opener-Policy: same-origin` 與 `Permissions-Policy`；`.js`／`.mjs` 固定以 `text/javascript` 提供。
- 移除 `allow_origins=["*"]` 的 CORS 設定：前端與 API 同源，其他網站的頁面無法再讀取 API 回應。
- `docs-check` 會檢查 README 目錄結構列出每個後端／前端模組與 script，且 SDD 有安排每個應用模組；漏列或列了不存在的檔案都會失敗（SPEC-053）。
- 程式整理：測試專用的 token 簽章移到 `unit_tests/token_helpers.py`，正式的認證只用注入的密鑰；合併重複的 legacy tool-call 掃描、月跑量查詢與 schema 驗證器。

Asset 4.12.0／shell v62、schema 7 不變，可直接回滾至 v4.11.0 image（回滾後恢復舊的 CORS 與無安全標頭）。

### 主畫面與分頁圖示改版（SPEC-052，v4.11.0）

- PWA 與 iOS 主畫面圖示改為碳黑底、volt「速度線＋箭頭」標誌配磨耗進度環，和介面內的品牌標誌一致；Android 的圓形裁切也不會切到進度環。
- 瀏覽器分頁圖示改用同一個 volt 標誌的 SVG，並保留 PNG 備援。
- 已加入 iOS 主畫面的捷徑不會自動換圖示，請刪除後從 Safari 重新「加入主畫面」；Android 會在 Chrome 下次檢查時自動更新。

Asset 4.11.0／shell v61、schema 7 不變，可直接回滾至 v4.10.0 image。

### 運動科技風視覺改版（SPEC-051，v4.10.0）

- 整個介面改成運動科技風：碳黑底加細格線、螢光黃綠主色、DIN 風格數字、斜線「速度條」標記與英文區塊小標；登入頁、開機畫面與側欄使用新的「速度線＋箭頭」標誌，分頁圖示改為線條 SVG。
- 亮色主題重新配色：螢光黃綠只用在按鈕等底色，文字與線條改用深綠，跑鞋表格的生命進度、圖表與熱力圖在白底上都看得清楚。
- 圖表、跑鞋磨耗色階、熱力圖與跑步月曆都改讀 CSS 主題 token，月曆依當天距離顯示由下往上的亮度。版面尺寸、操作流程與資料都不變。

Asset 4.10.0／shell v60、schema 7 不變，可直接回滾至 v4.9.0 image。

### 近 90 天月均里程佔比與圖表空白修正（SPEC-050，v4.9.0）

- 跑鞋頁的圓餅圖改為「近 90 天月均里程佔比」：每雙現役鞋的數字就是單鞋分析裡的「實際月均」，中間顯示合計；近 90 天沒穿的鞋不佔扇形。
- 現役表格移除「月跑量」欄。計畫月跑量仍在編輯視窗，近 90 天沒有紀錄的鞋，退役預估以它回退。
- 「跑鞋輪替時間軸」與「每雙鞋的距離分布」用跑步紀錄繪製。讀取途中跑步紀錄或目標資料才到，或中途切到別的分頁，以前會留下空白的圖，要重新整理才恢復；現在會自動重畫。

Asset 4.9.0／shell v59、schema 7 不變，可直接回滾至 v4.8.0 image。

### 新版部署提示（SPEC-049，v4.8.0）

- App 開著時也會檢查有沒有新部署：回到前景、視窗取得焦點、網路恢復，以及每 30 分鐘一次（同時觸發的只算一次，隱藏或離線時不檢查）。
- 偵測到新版時右下角（手機在底部分頁列上方）跳出「有新版本 v<版號>」，按「立即更新」才重新載入；按「稍後」先隱藏，下次開啟 App 就是新版。重新載入時表單草稿會保留，AI 對話會清除。
- v4.0.0～v4.7.3 偵測到新版會直接重新載入；已開著 v4.7.3 的頁面升級到本版時仍會自動載入一次，之後改為提示。

Asset 4.8.0／shell v58、51 個 release assets、schema 7 不變，可直接回滾至 v4.7.3 image。

### 備份還原上限與頻率限制（SPEC-047 修訂，v4.7.3）

- 帳號備份 JSON 上限從 20 MB 降為 10 MB，跑步與異動歷史各從 50,000 筆降為 10,000 筆。帳號本身最多只能有 5,000 筆跑步（`MAX_RUNS_PER_USER` 預設）及 5,000＋5,000 筆保留歷史，配額內的完整帳號匯出約 7 MB，仍可下載與還原。`MAX_RUNS_PER_USER` 設超過 10,000 時，跑步數超過的帳號需改用管理員完整資料庫備份。
- 備份預覽每個帳號每分鐘最多 20 次、全站 60 次（選檔或切換匯入模式都會重新預覽；`RESTORE_PREVIEW_RATE_LIMIT_PER_MINUTE`／`RESTORE_PREVIEW_GLOBAL_RATE_LIMIT_PER_MINUTE`）；每個伺服器程序一次只處理一個預覽或還原，其他請求立即回 429「請稍後再試」，不排隊。
- 原因：解析一份上傳的備份會用到檔案大小數倍的記憶體，舊上限下一份刻意做大的檔案就可能讓 256 MB 的機器記憶體不足而重啟；預覽也不再同時保留兩份完整副本。

Asset 4.7.3／shell v57、51 個 release assets、schema 7 不變，可直接回滾至 v4.7.2 image（回滾後恢復舊上限與無頻率限制）。

### 備份檔名、AI 錯誤訊息與 router 解耦（SPEC-047 修訂，v4.7.2）

- 帳號備份 JSON 的檔名改用台灣時間，不再在凌晨標成前一天。
- AI 對話與月報出錯時顯示整理過的訊息（例如「這個免費模型目前請求過多或今日額度已滿」），不再顯示模型供應商的原始錯誤內容；詳細內容只寫進伺服器 log。
- 所有 router 都不再自行查詢資料庫，改由 read model 或 service 負責。

Asset 4.7.2／shell v56、51 個 release assets、schema 7 不變，可直接回滾至 v4.7.1 image。

### 保留上限與小修正（SPEC-047 修訂，v4.7.1）

- 匯入含異動歷史的備份不再擠掉本機可復原的紀錄：本機與備份帶入的歷史各保留最新 5,000 筆。
- 過期的還原預覽改在每次啟動時清除，避免占用磁碟。
- 年目標固定兩位小數；`MODEL_REFRESH_COOLDOWN_SECONDS` 上限 3600 秒。

Asset 4.7.1／shell v55、51 個 release assets、schema 7 不變，無資料 migration，可直接回滾至 v4.7.0 image。

### 程式審查修正、有界歷史與模組解耦（SPEC-047，v4.7.0）

[SPEC-047](../docs/specs/047-review-hardening-and-decoupling.md) 修正一次全面程式審查找到的問題：

- **Strava 日期**：改用台灣日期，重新匯入可修正舊紀錄。
- **小修正**：跑步更新送 `expected_version: null` 改回 422；匯出檔名改用台灣時間；同月份新增跑步不再浪費月跑量 ID。
- **登入鎖定**：同一網路對同一帳號輸錯 10 次只暫停該網路 15 分鐘，帳號擁有者換個網路仍可登入；跨網路累計 100 次才暫停整個帳號。
- **保留上限**：每帳號保留最新 5,000 筆異動紀錄、1,000 筆操作回執與 50,000 筆刪除身分。
- **SECRET_KEY**：正式環境要求至少 32 bytes。

內部改動：

- import 時不再做 I/O；限流只用 SQLite 一套計數，且不 commit 請求交易。
- 稽核 trigger 每次啟動依目前欄位重建。
- 前端改以 `data-*` 屬性委派事件。
- 測試不再留下未關閉的 SQLite 連線。

Asset 4.7.0／shell v54、51 個 release assets、schema 6 → 7。

上線步驟：

1. 部署前建立並驗證異地備份，在私有副本重複升級兩次，確認業務資料不變。
2. 確認 Fly 的 `SECRET_KEY` 至少 32 bytes。
3. 部署後執行匿名 `release-check`。
4. 用自己的 Strava 匯出檔預覽一次，確認清晨跑步的修正方向正確（例如 10/31 → 11/01）再匯入。

回滾步驟：

1. 停止寫入並另做 schema 7 備份。
2. 以 Python `sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_seven.sql`](../scripts/rollback_schema_seven.sql)，重建空的舊回執表並把 marker 改回 6。
3. 部署 v4.6.0 image。

### 冷啟動加速、購買日前跑步提醒與瀏覽器偵測（SPEC-046，v4.6.0）

[SPEC-046](../docs/specs/046-cold-start-purchase-date-warnings-and-browser-probe.md) 讓後端啟動不再載入 OpenAI SDK（第一次 AI 請求才載入），Docker image 預先編譯 `backend/`，縮短 Fly 閒置停機後第一次開啟的等待；
新增／編輯跑步與 Strava 配對時，日期早於鞋款購買日會提醒（不阻擋）；`verify-all` 與 Stop hook 改以實際啟動 Chromium／WebKit 判斷瀏覽器可用性，缺 Linux 系統函式庫時跳過並提示 `sudo npx playwright install-deps chromium webkit`。
schema 6 不變、Asset 4.6.0／shell v53，可回滾至 v4.5.1 image。

### 清除舊空表與已刪除鞋款標籤（SPEC-045，v4.5.1）

[SPEC-045](../docs/specs/045-legacy-tables-and-deleted-shoe-labels.md) 啟動時刪除不再使用的空表 `operation_history`、`app_settings`（仍有資料則保留），資料庫由 19 張表變為 17 張；
年度堆疊圖把已刪除鞋款合併為「已刪除的鞋款」，不再顯示 `#15` 這類內部編號。鞋款／跑步主鍵維持全域穩定編號，刪除不重排。
schema 維持 6、Asset 4.5.1／shell v52，可直接回滾至 v4.5.0 image。

### 月跑量年度目標總覽（SPEC-044，v4.5.0）

[SPEC-044](../docs/specs/044-annual-goal-overview.md) 移除「查看月份」選單，月跑量分頁改以一張年度目標卡同時顯示 12 個月的達標狀態、年度進度與本月進度；
目標設定收進「調整目標」，開始年份改為選單並說明用途。新增唯讀 `GET /api/running-goal/year`；Asset 4.5.0／shell v51、schema 6 不變，可回滾至 v4.4.0 image。

### 支出併入跑鞋分頁（SPEC-043，v4.4.0）

[SPEC-043](../docs/specs/043-spending-in-shoes-tab.md) 移除「支出」分頁，支出卡片、兩張支出圖與支出明細移到跑鞋分頁最下方，內容不變；導覽剩 4 個分頁。
Asset 4.4.0／shell v50、schema 6 不變，可回滾至 v4.3.0 image。

### 移除跑步摘要卡、距離分布配色與 AI 分頁合併（SPEC-042，v4.3.0）

[SPEC-042](../docs/specs/042-run-log-tiles-distance-colors-and-ai-tab.md) 移除跑步日誌頂端的四張摘要卡與個人紀錄（保留「今天穿哪雙」）；
每雙鞋的距離分布改為 5 km 一段並用紅、黃、綠、藍、紫區分；AI 助手與月報合併為一個「AI」分頁，在面板內切換。
Asset 4.3.0／shell v49、schema 6 不變，可回滾至 v4.2.0 image。

### 年度回顧、首頁摘要與手機底部分頁列（SPEC-040，v4.2.0）

[SPEC-040](../docs/specs/040-highlights-review-and-mobile-navigation.md) 新增年度回顧、跑步日誌頂端摘要（本週、連續天數、目標進度環、累計里程碑）、近 30 天里程碑與個人新紀錄、「今天穿哪雙」建議、每雙鞋距離分布與年度月跑量對比；
月跑量分頁統一為一個年份選單，同一雙鞋在所有圖表顏色一致，手機版改用固定底部分頁列。全部由後端計算，只使用既有跑步日誌與鞋款資料。
Asset 4.2.0／shell v48、schema 6 不變，無資料 migration，可回滾至 v4.1.3 image。

### 輪替時間軸只列現役鞋（SPEC-038 修訂，v4.1.3）

跑鞋分頁的輪替時間軸不再顯示已退役的鞋，只列出仍在輪替中的現役鞋與閒置提醒；`GET /api/analytics/shoe-timeline` 同步排除退役鞋。
Asset 4.1.3／shell v47、schema 6 不變，可回滾至 v4.1.2 image。

### 移除月跑量紀錄表（SPEC-039，v4.1.2）

[SPEC-039](../docs/specs/039-compact-monthly-records.md) 移除月跑量分頁底部的「月跑量紀錄」表格、新增表單與月份編輯對話框（v4.1.1 曾先改為收合）。
月跑量仍由跑步日誌自動累加，既有歷史／手動調整資料、圖表、目標、報告、備份與 `/api/monthly-mileage` 都保留。
Asset 4.1.2／shell v46、50 個 release assets、schema 6 不變，可回滾至 v4.1.1 image。

### 訓練趨勢與跑鞋輪替（SPEC-038，v4.1.0）

[SPEC-038](../docs/specs/038-training-trends-and-shoe-rotation.md) 在月跑量分頁新增年度跑步熱力圖（含有跑天數、最長／目前連續天數）、
近 16 週每週跑量與 4 週平均（比前 4 週平均多 30% 以上標示暴增），以及年度累計跑量對照目標線與全年推估；
跑鞋分頁新增輪替時間軸，標出超過 30 天沒穿的現役鞋。全部由後端計算，只使用既有跑步日誌。
Asset 4.1.0／shell v44、schema 6 不變，無資料 migration，可回滾至 v4.0.3 image。

### 本機資料庫自動重新連線（SPEC-037，v4.0.3）

[SPEC-037](../docs/specs/037-reconnecting-local-workspace-store.md) 修正瀏覽器（特別是 iPhone Safari）在背景或記憶體壓力下關閉本機資料庫後，
離線待送跑步與草稿無法讀寫直到重新整理的問題；下一次讀寫會自動重新連線。本版也更新依賴並穩定 WebKit 瀏覽器測試。
Asset 4.0.3／shell v43、schema 6 不變，無資料 migration，可回滾至 v4.0.2 image。

### 安全強化與跨平台安裝（SPEC-036，v4.0.1）

[SPEC-036](../docs/specs/036-security-hardening-and-portable-locks.md) 修正 AI／月報 Markdown 的 XSS，
被自身上限拒絕的請求不再消耗全站額度。新註冊與改密碼需至少 8 個字元；同一帳號 15 分鐘內密碼錯誤 10 次後，
該帳號的登入與改密碼會暫停 15 分鐘（其他帳號不受影響）。鎖定檔改為跨平台編譯，Windows 可直接執行 setup。
Asset 4.0.1／shell v42、schema 6 不變，可回滾至 v4.0.0 image。

### 穩定測試版（v4.0.0）

目前上線測試的穩定版，預期不再特別調整。PWA 在部署新版後會自動載入最新版；跑步紀錄和鞋款選單不再顯示內部數字編號。

### 資料與同步操作簡化（SPEC-035，v3.10.5）

目前前端使用 Asset 3.10.5／shell v40、schema 6。同步區依待送跑步及網路狀態顯示動作；草稿、備份／匯入、歷史和本機清理預設收合。

### 來源復原搬移與跨分頁同步（SPEC-034，v3.10.4）

v3.10.4 使用 Asset 3.10.4／shell v39、schema 6、51 個 release assets。
[SPEC-034](../docs/specs/034-portable-recovery-and-sync-refresh.md) 修正來源網站復原後再次搬移的重複跑步、浮點尾差造成的假更新，以及其他分頁送出後畫面未刷新的問題。

新下載使用 **備份 JSON v3**，每筆跑步的 `aliases` 保留同一來源復原前的 ID；省略異動歷史仍保留這項來源身分。
單檔最多 50,000 個別名，共用 20 MiB 限制，超限拒絕下載，不靜默裁切。別名須唯一且不能指向不同跑步；若既有對應已衝突，預覽會拒絕，不會自動刪除或合併資料。
新版仍接受 v1/v2；v1 指紋沿用舊算法，避免升版後重建舊檔。舊 App 不接受 v3，請先更新接收端再匯入，不能手動刪除別名或改版本以繞過檢查。

里程累積與比較統一兩位精度，既有儲存浮點尾差不會觸發無意義的版本更新。
「更新雲端資料」即使沒有待送出紀錄也會讀取雲端；回到前景或同帳號另一分頁成功送出時同樣刷新，保留未送出的輸入。
支援 BroadcastChannel 的瀏覽器會接收跨分頁提交通知；通知不可用時，回到前景或按「更新雲端資料」仍可刷新。通知期間又收到提交會補做一次讀取，舊帳號通知不影響目前帳號。

無 schema migration。部署前驗證正式異地備份及隔離還原；回滾可部署 v3.10.3 image
`registry.fly.io/running-shoes@sha256:5def65ac422062ac5a7e4c932d5d8dd4c76c5e1a184e46d11759d9781e4af690`。
回滾後 v3 檔案需保留至接收端重新升級才能匯入，DB 對應仍相容，不還原舊業務快照。

### 復原與同步身分（SPEC-033，v3.10.3）

v3.10.3 使用 Asset 3.10.3／shell v38、schema 6、51 個 release assets。
[SPEC-033](../docs/specs/033-recovery-and-sync-identity.md) 補足刪除、復原與再次匯入的組合操作：
同帳號舊備份不重建已刪跑步；明確復原後，原來源及舊 ID 的對應會跟隨復原紀錄，後續更新匯入仍可修改該筆資料。
每次離線送出使用獨立租約，重新登入接手後不受舊請求的延遲結果影響。
同步已送出而畫面讀取失敗時會明確提示重新整理；誤刪復原已成功而讀取失敗時，按「重新載入資料」只重試讀取。
核心刷新驗證由 resource bridge 共用；跑步來源復原別名由 `backend/services/run_identity.py` 管理，服務仍由呼叫端持有交易。

本版無 schema migration，回滾可使用 v3.10.2 immutable image
`registry.fly.io/running-shoes@sha256:bac44457f12adfde6473e9d9a973b330e1bf69eac7e44feb3fb6ed1f5a55429a`，
不還原業務資料快照。發布驗證涵蓋 verify、40 組版面、雙引擎 CRUD／PWA、main/tag CI 及正式站匿名 release-check。

### 可靠帳號資料搬移（SPEC-032，v3.10.2）

v3.10.2 使用 Asset 3.10.2／shell v37、schema 6、51 個 release assets。
[SPEC-032](../docs/specs/032-trustworthy-account-transfer.md) 將提交成功與畫面載入分開：若匯入已完成但讀取失敗，
按「重新載入資料」只重新讀取，不會再次匯入；提交回應不確定時仍沿用原操作重試。
預覽分別顯示新增、實際變更與內容相同，並保留已刪除跑步及額外本機資料。

`GET /api/export/account?include_history=true` 預設包含全部異動歷史；兩個下載入口均可明確取消「包含異動歷史」，
產生檔名以 `_without_history.json` 結尾的資料檔，業務資料不會省略。匯出與匯入共用集合、格式、秘密檢查及容量上限（v4.7.3 起為 10 MiB），
下載前驗證可重新匯入；超限會顯示原因，不產生檔案、不靜默截斷。每份最多 5,000 雙鞋、10,000 筆跑步、
2,412 個月份／月報、1,000 筆 Strava 摘要及 10,000 筆異動歷史（v4.7.3 起；原為 20 MiB、50,000 筆）。取消歷史後仍超限時，需使用下方管理員完整資料庫備份流程。

本版無 schema migration。部署前完成異地備份及隔離還原；若需回滾可直接使用 v3.10.1 immutable image
`registry.fly.io/running-shoes@sha256:ba35ff3051b2c627ebf3b59fdb091747e93db2c0fc3a91c14320ca8411bde804`，
schema 6 保持相容，不還原舊業務快照。

### 匯入操作隔離（SPEC-030，v3.10.1）

v3.10.1 使用 Asset 3.10.1／shell v36、schema 6、51 個 release assets。
[SPEC-030](../docs/specs/030-import-operation-isolation.md) 修正跨帳號清除、無變更匯入的假衝突及預覽完成順序問題。
每份預覽獨立有效 20 分鐘，同帳號最多 8 份、合計 64 MiB；關閉／換檔會以本人
`DELETE /api/account-restore/preview/{token}` 捨棄不用的 token，失敗由到期清理回收。其他分頁與晚到請求不會撤銷仍有效的預覽；業務資料變更仍需重新預覽。
相同內容的更新不增加版本或異動紀錄，額外資料的編輯仍可正常儲存。

Schema 5→6 只以交易重建 `restore_previews` 的 `(user_id, token)` 主鍵並保留現有預覽，不修改業務表。
部署前建立異地備份、校驗與隔離還原，並在私有副本重複升級驗證資料不變。
回滾優先 forward fix；確需回 v3.10.0，先進入維護環境停止所有 HTTP／背景寫入、另做 schema 6 備份，
以 Python `sqlite3.Connection.executescript` 在掛載的資料庫執行
[`scripts/rollback_preview_schema.sql`](../scripts/rollback_preview_schema.sql)，再部署先前 v3.10.0 immutable image
`registry.fly.io/running-shoes@sha256:a6281907140cc065db385eb68769ed86fc2cbbb4757678c48d04755d361bbb78`。
此程序只捨棄暫存預覽、恢復 schema 5 預覽主鍵及 marker，不以舊快照覆蓋跑步資料；不得混跑兩版。
重新上線後需重新預覽並執行匿名 release-check。

### 雲端下載與本機匯入更新（SPEC-028／029，v3.10.0）

v3.10.0 使用 Asset 3.10.0／shell v35、schema 5、50 個資產。詳見 [使用指南](../docs/user-guide.md) 與 [資料搬移規格](../docs/specs/029-account-data-transfer.md)。

- `POST /api/account-restore/preview?mode=merge|update` 預設只新增；update 僅接受 v2，明確更新同來源鞋款與跑步、檔案內月份調整、目標及月報。模式與資料一起綁定本人預覽 hash／revision，apply 不接受切換模式。
- 更新保留接收端額外資料、已刪除跑步及不存在於檔案的內容；不是整個帳號的鏡像取代。鞋款刪除狀態依檔案更新，不按同品牌型號合併。所有總里程於後端重算，月報匯入會撤銷同月份舊生成的保存資格。
- 同步按鈕與下載在目前視窗顯示明確結果；接收網站／帳號、來源與更新筆數在確認前可見。使用者確認匯入才修改目前網站的資料，部署驗證不執行正式帳號匯入。
- 無 schema migration；回滾可直接部署 v3.9.0 image，維持 schema 5。新版已成功匯入的資料仍為既有格式；未完成的新預覽需重新預覽。部署前照常建立、校驗正式備份並完成隔離還原演練。

### Schema 2 上線與回滾

v3.4.0 只新增 `run_creation_requests` 表與 user/key 唯一約束，沒有改寫既有鞋款、日誌或里程。
部署前必須用下方異地備份工具下載快照並完成 checksum 與隔離還原演練；舊 v3.3.1 不接受 schema 2 marker，不能直接切回舊 image。
優先 forward fix。若確實回滾，停止所有 app writes、另做 schema 2 備份，確認 schema 2 只有新增 receipt 表後，
在停止的資料庫上執行 `UPDATE schema_metadata SET value='1' WHERE key='schema_version' AND value='2';`，保留 receipt 表與業務資料，再部署已驗證的 v3.3.1 image。
重新發布舊程式仍須新的 shell revision。不要以舊快照覆蓋已新增的正式資料；完整還原只用於確認可接受資料回溯的災難復原。

### 可恢復的帳號工作區（SPEC-027，v3.9.0）

側欄「資料與同步」提供草稿、同步佇列、備份合併還原及異動歷史。Asset 3.9.0／shell v34，共 50 個資產；發布流程包含正式備份、隔離還原驗證、CI 與部署後匿名 release-check。

- 跑步、月跑量與目標表單自動存入 IndexedDB；鞋款、跑步、月份的彈窗／行內編輯保留原 ID、version 與輸入，可在工作區選擇恢復或捨棄。重開仍使用原版本，伺服器有新異動會回報衝突。資料按 origin／帳號分區，登出保留本機資料，另一帳號不可顯示或同步；共用裝置可按「清除此帳號的本機資料」。
- 僅新增跑步支援離線寫入。先以同一 IndexedDB 交易持久化 payload／operation ID 並消耗對應草稿，成功才清除仍相同的表單；等待時的新輸入保留。尚未同步不計入統計。連線且開啟 App、回到前景或按同步按鈕時重試；不承諾關閉 App 後背景同步。
- 多分頁以 120 秒原子 lease 避免同時發送，失聯重播同 operation ID，由伺服器交易回執防止重複。401 暫停等待重新登入；刪鞋、版本／配額或格式錯誤會列為「需要處理」，必須明確重新配對或移除，絕不默默換鞋。移除／清除會失去尚未同步紀錄，介面會先確認。瀏覽器儲存不可用時保留輸入並提示，連線可使用一般新增。
- 最近鞋款、月跑量、目標及目前月份跑步另存本機快照；它們可能過期，不作為伺服器權威。Service worker 只快取公開 shell，IndexedDB 不存 token／密碼。瀏覽器回收空間或使用者清除網站資料會移除本機草稿／佇列，請定期同步、下載備份；本機資料不是加密保險箱。
- 完整備份以同一資料庫讀取快照匯出，並行新增不會產生跨集合不一致。備份 JSON v2 包含穩定來源身分、鞋款基礎里程、月份歷史調整與異動歷史。選檔後先驗證／預覽，確認才在一個交易合併，保留既有暱稱、月份調整、目標與月報；不按同品牌型號合併鞋款。相同來源 ID／Strava ID 不重建，mapping 保留已刪紀錄的身分，重複匯入不撤銷後續刪除。新跑步正常累加里程。Strava 匯入摘要保留既有項目，剩餘容量內按新到舊合併，超額略過並在預覽列出，不清除既有摘要。舊 v1 格式仍接受，只保證完全相同檔案重複匯入不重建。
- 預覽僅限本人、有效 20 分鐘；預覽後資料異動須重新預覽。上限 10 MB、5,000 雙鞋、10,000 筆跑步／歷史、2,412 個月份／月報及 1,000 筆匯入歷史（v4.7.3 起），並受目標帳號配額限制；預覽有每帳號與全站頻率限制，每個伺服器程序一次只處理一個預覽或還原；拒絕非有限數值、無效參照、未知欄位與認證內容，失敗整筆回滾。超過還原限制的大型完整匯出不會截斷，需另行規劃資料搬移；不會靜默部分還原。
- Schema 5 起，鞋款、跑步、月跑量、目標每次寫入都在同一交易記錄前後值、原因及操作身分；升級前的歷史無法回溯產生。v4.7.0 起每個帳號保留最新 5,000 筆異動紀錄，更早的無法再顯示或復原；v4.7.1 起從備份帶入的唯讀歷史另計 5,000 筆，不會擠掉本機紀錄。刪除過的跑步身分另存，不受影響。歷史分頁僅限本人；可復原刪除的跑步／鞋款及清除的月份，仍檢查原鞋款、目前版本、配額與 Strava 重複。復原會重新計算里程，原事件只可復原一次；備份帶入的歷史明確標為唯讀。
- `/api/operations` 統一 operation ID、更新／刪除 expected_version、成功回執與錯誤 `{detail, error: {code, message}}`。既有 CRUD 保留相容性，新增／帶版本的異動可附 `Idempotency-Key`；未提供版本的舊式刪除不取得新契約的重播保護。年度、目標與洞察已移除相容鏡像 Map，統一由 resource store 擁有請求與快取。

Schema 5 增加 user metadata、回執、預覽、mapping、異動、context 與主鍵配置表；既有業務資料／里程不改寫。Run／month ID 不因刪除而重用，避免恢復草稿寫到新紀錄；allocator 僅讀全域最大主鍵與 sequence 這類配置 metadata，不讀取其他帳號的業務值。上線前必須建立、校驗正式備份並完成隔離還原演練。若回滾至 v3.8.0，先停止所有寫入、另備份 schema 5，保留新增表／欄位／triggers，將 `schema_metadata` marker 降至 4，再切回舊映像及通過 readiness／匿名 release-check；舊版不再保證離線操作回執與主鍵不重用，不能混跑新舊寫入。重新升級需保留本機 queue 並使用新 shell revision。

### 行內草稿、衍生資源與月報生成（SPEC-026，v3.8.0）

- 新增跑步草稿所選鞋款被刪除後，保留「請重新選擇」，直到明確選擇替代鞋款；重繪或跨日不默默換鞋。
- 資源完成只失效依賴它的分頁。鞋款／月跑量行內編輯保留輸入 DOM 與表格列快照；背景刷新、主題或跨日重繪不觸發部分數字儲存。Enter／使用者離開欄位才提交原始 id／version，Escape 取消，換帳號清理。
- 年度彙總、目標進度與首頁洞察透過 resource store 合併同 key 的 pending 與成功結果；失效後拒絕舊回應，失敗可重試。完整刷新導致的有效日誌失效可以啟動新讀取，單純重繪不增加請求。
- Strava 匯入期間停用配對選單；失敗可在同一視窗重新調整。舊操作不解鎖替換視窗。
- 月報採「最新開始的生成」：同帳號同月份的新請求開始後，舊請求即使較晚完成也不保存，串流回傳錯誤而非成功。新請求失敗／取消時保留先前成功報告，不讓舊請求重新取得資格。不同帳號／月份互不撤銷；LLM 等待不持有資料庫交易。
- Schema 4 僅新增 `report_generations`，每帳號／月份一筆最新身分，不產生可見的空月報；既有報告、里程與版本不改寫。Asset 3.8.0／shell v33，共 45 個資產。

Schema 4 上線前，執行異地備份、checksum 與隔離還原驗證。回滾優先 forward fix；若需回 v3.7.2，先停止所有實例與寫入、另備份 schema 4，確認新增表是唯一 schema 差異，
再對停止寫入的資料庫執行 `UPDATE schema_metadata SET value='3' WHERE key='schema_version' AND value='4';`，保留新增表與業務資料，部署已驗證的 v3.7.2 image。禁止混跑兩版月報生成服務；回滾後失去生成順序保護。還原部署前快照會遺失後續寫入，僅作災難復原選項。

### 首次顯示目標表單的草稿保護（v3.7.2）

- 切換月跑量時，在欄位可操作前同步初始化目標草稿 baseline；圖表仍於下一個 animation frame 繪製。即使在第一個 frame 前輸入並失焦，後續重繪及晚到的目標回應也不覆蓋草稿。
- 雙引擎 E2E 明確暫停首次 panel frame，先輸入再釋放，以固定重現原先的時序缺口。正式版本為 asset revision 3.7.2／shell v32，44 個資產、schema 3。

### 離線 worker 更新與佇列驗證（v3.7.1）

- v3.7.0 main CI 的 trace 顯示 worker update 卡在尚無 installing candidate 的 script request；相同 tag 的 PWA 已通過，不能以此略過 main 失敗。
- WebKit 離線 fixture 對 worker script 回 503，避免背景 register/update 在 TCP drop 後持續重試。每次恢復連線前，明確驗證離線 `registration.update()` 在 10 秒內失敗，然後驗證下一個在線候選正常處理；離線 shell／API exclusion 與 failed-upgrade gates 保留。
- v3.7.1 使用 asset revision 3.7.1／shell v31，仍是 44 個資產、schema 3。v3.7.0 tag 保留原始內容；正式發布及部署使用後續通過檢查的修正版。

### 匯入所有權與逐資源呈現（SPEC-025，v3.7.0）

- 編輯原鞋款已刪除的日誌，跨日／背景刷新仍保留「請重新選擇」；明確選取替代鞋款後才能儲存，避免自動轉移里程。
- Strava 預覽、匯入與視窗操作由 `runtime/strava-controller.mjs` 管理。取消／重開後，舊成功或失敗不關閉新視窗、不清除新預覽，也不解鎖其他提交；已完成的匯入仍刷新資料。
- Strava 歷史納入 resource store；匯入成功使舊讀取失效，新歷史及下次預設日期不會被晚到的舊回應覆蓋。
- 鞋款移至現役／退役保留點擊前和等待期間的其他未儲存欄位；再次儲存只更新這些欄位並使用新版本。狀態操作本身仍更新月跑量。
- 各資源完成即套用及呈現，慢來源不再阻擋已完成資料或持續蓋住啟動畫面；整批 Promise 仍可等待全部完成，失敗按來源保留。
- 單鞋及批次分析共用 SQL read model：三次查詢取得全歷史統計、12 個月聚合及每雙鞋最多 12 筆最近紀錄，不載入全部 Run entities；統計欄位及日期政策維持相容。
- PWA worker observer 同時觀測既有與新 installing candidate，deadline 涵蓋 update 呼叫與終態；失敗文字附註冊狀態時間線、目前階段及最近合成 HTTP 請求。中斷資產 fixture 在 headers 後截斷宣告的 body，避免 WebKit TCP 重試使錯誤掛起；worker 拒絕長度不符的未壓縮回應，避免截斷內容仍被當成成功。
- Asset revision 3.7.0／shell v30；schema 維持 3。部署前做異地備份及隔離還原演練，回滾可直接部署相容 schema 3 的 v3.6.1 image；不以舊資料覆寫正式站。

### 草稿狀態轉移與資源模組（SPEC-024，v3.6.1）

- 鞋款移至退役／現役成功後，保留的新草稿會同步最新模式、月跑量與版本；再次儲存只提交實際修改的欄位，避免撤銷剛完成的狀態轉移。
- 目標以 server baseline 比較草稿，失焦、主題切換與背景重繪皆保留未儲存內容；儲存期間的新修改也會保留，帳號切換會清理。
- `runtime/resource-store.mjs` 不依賴 DOM 或 HTTP，注入 session 與快取 hooks；同資源／key 的並行讀取共用 pending request，成功與錯誤各自管理，失效或換帳號後拒絕舊結果。
- `app-resources.js` 註冊既有快取 adapters；`app-core.js` 負責 reader 組合、套用結果與 render。某個來源失敗仍能更新其他成功來源，完整／部分刷新沿用 SPEC-023 的異動範圍。
- v3.6.1 使用 asset revision 3.6.1／shell v29；schema 仍為 3，沒有資料 migration，API method/path 不變。

### 表單保護、暱稱與部分刷新（SPEC-023，v3.6.0）

- 月跑量新增成功只清除與送出時相同的年月及里程草稿；舊回應不會解鎖新操作、覆蓋新帳號錯誤或關閉重開的視窗。
- 跑步、月跑量與鞋款共用原生表單操作模組。等待期間改過的編輯草稿會保留，成功回應的版本用於下一次儲存。
- 新增／編輯鞋款可設定最多 80 字的暱稱（留空表示沒有暱稱）。跑步與 Strava 選單顯示暱稱、品牌型號、購買日期和 #ID，區分同款鞋；鞋款表、CSV／XLSX 與帳號備份保留暱稱。
- 月跑量異動只重讀月跑量；鞋款異動重讀現役與退役清單；跑步異動重讀鞋款、月跑量、明細與摘要。首次登入及手動重試仍完整讀取，匯入另更新 Strava 歷史。
- 購鞋支出快取只因鞋款異動失效；逐筆目標與年度統計因日誌異動失效。不同資源分別檢查請求身分及登入 session，舊完整讀取不會蓋掉新的部分刷新，其他來源成功也不會掩蓋尚未恢復的載入錯誤。
- 認證與目標寫入位於 `backend/services/accounts.py`／`goals.py`，密碼與 token primitives 位於 `backend/credentials.py`；router 保留輸入、rate limits 及 HTTP 轉換。
- v3.6.0 使用 asset revision 3.6.0／shell v28。Schema 3 新增 `shoes.nickname`，舊鞋預設空字串，保留原始里程與版本；新舊資料庫均提供 server default。

Schema 3 正式上線前，必須執行異地備份、checksum 與隔離還原演練。優先 forward fix；若要回滾 v3.5.1，先停止所有 writes、另做 schema 3 備份並確認只有新增 nickname 欄位，
再於停止的資料庫執行 `UPDATE schema_metadata SET value='2' WHERE key='schema_version' AND value='3';`，保留 nickname 欄位和新業務資料，部署已驗證的 schema 2 image。
不要以舊快照覆蓋新資料。重新發布舊來源仍須新 shell revision。

### 交易與草稿安全（SPEC-020，v3.5.0）

- 新增日誌等待回應期間，可繼續修改下一筆草稿；成功只清除仍符合送出快照的輸入，不覆蓋新日期、里程、鞋款或查看月份。
- 跑步、鞋款與月跑量的寫入由 application services 統一管理；取得 SQLite writer reservation 後才讀取配額與業務版本。並行新增不會突破鞋款／日誌上限，里程與重送回執維持同一交易。
- `create_app(config=...)` 的鞋款、日誌、註冊、Strava 配額及上傳限制由該 app instance 注入；測試不必改 router 全域常數。
- `runtime/run-controller.mjs` 擁有跑步明細／分頁／年度 cache、編輯快照與新增操作，明確注入 transport、session 與 key factory。DOM bridge 保留既有 handler，帳號切換統一清理 controller。
- 首頁、目標與月報共用日期區間邊界；月報的月份／上月同期／年度累積以一次 SQL 聚合取得，不再每月各查一次，仍不把手動歷史調整算成逐筆日誌目標。
- v3.5.0 維持 schema 2，不需資料 migration。回滾至 v3.4.0 image 可讀寫相同資料；重新發布舊來源仍需新 shell revision，不以舊備份覆蓋正式資料。
