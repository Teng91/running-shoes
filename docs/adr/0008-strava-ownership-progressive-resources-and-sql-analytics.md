# ADR-0008：匯入所有權、逐資源交付與有界 SQL 分析

- 狀態：Accepted
- 日期：2026-10-23
- 規格：[SPEC-025](../specs/025-strava-ownership-progressive-resources-and-bounded-analytics.md)
- 延伸：[ADR-0007](0007-draft-rebase-resource-store-and-browser-deadlines.md)

## Context

同帳號中的視窗替換、輸入變更與匯入後歷史讀取也需要操作所有權；僅驗證 auth session 不足以拒絕舊回應。整批 render 的 barrier 延誤已完成來源。批次 ORM 歷史雖無 N+1，仍使記憶體隨完整 run history 成長。WebKit 更新觀測可能漏接已在 installing 的 candidate，截斷 HTTP body 也可能被引擎當作成功內容。

## Decision

- `runtime/strava-controller.mjs` 注入 session／upload transport，擁有視窗 generation、預覽 revision、AbortController 及 import operation。Adapter 管理 DOM 與成功通知。關閉視窗只撤銷 UI 所有權，不宣稱取消 server commit；同 session 的已完成匯入仍刷新資料。
- `strava-history` 交給 resource store；成功匯入先 invalidate 舊 ticket，新讀取不與先前 pending GET 合併。歷史只保存目前 session 的有效結果。
- Resource refresh 提供同步 onResult callback，每個來源完成即 accept 一次、套用及 render；原本整批 Promise 保留作為全部完成的界線。第一個可用來源呈現後解除 boot，個別失敗仍保留獨立錯誤。
- 鞋款狀態指令僅 acknowledge lifecycle／月跑量；其他表單欄位與 categories 以原始 draft baseline rebase，保留指令之前及等待期間的修改。
- `read_models/shoe_statistics.py` 以 user_id／shoe_ids 限制所有查詢，SQL 分組計算完整統計，12 個月份聚合與 row_number partition 每鞋 recent 12。詳細分析固定三次查詢；AI 摘要略過不使用的月份／recent 查詢，只需一次 aggregate。Formatter 與預估政策仍在 analytics／forecasting。
- Worker observer 先掛 updatefound，再觀測已存在 installing／waiting，只接受 candidate 終態，不以目前 active worker 當更新成功。update 呼叫與終態共用 deadline；失敗保存註冊時間線、fixture 階段及最近請求。合成中斷回應有 headers 和不完整 Content-Length，worker 比對未壓縮回應長度，拒絕引擎未拒絕的截斷資料；壓縮回應不能以解壓後大小比對 wire length。

## Consequences

- 不增加框架、bundler、schema 或 HTTP contract；classic adapters 仍負責呈現。
- 分析回傳完整統計、排序、同日 id tie-break、12 月資料與 first／last 日期政策保持相容；不再 materialize 全歷史 Run entities。SQL 掃描統計仍隨資料量成長，但交付／記憶體有界。
- 逐來源 render 會增加輕量重繪次數，既有 panel revision／request guards 保持過期統計拒收；同資源 coalescing 仍只套用一次。
- 逾時不證明瀏覽器所有內部競態已消失；失敗會阻擋發布，不能把定向重跑當成根因修正。外層 watchdog／限時 trace 與 close 保持有效。
- v3.7.0／shell v30、schema 3。部署前驗證備份，回滾用相容 v3.6.1 image。

## CI follow-up

Main 39934466655 的 trace 證明 worker script request 可在 installing candidate 建立前卡住；僅補 statechange observer 不足。v3.7.1 fixture 對離線 worker script 回 HTTP 503，並在每次在線轉換前要求離線 update 有限失敗。這避免 TCP drop 的背景更新重試阻塞下一個 scope job；不擴大 deadline、不跳過 WebKit。正式發布使用 v3.7.1／v31，v3.7.0 tag 保留原始證據。
