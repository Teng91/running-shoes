# Feature specifications

每個會改變使用者行為、API、資料模型、部署流程或架構邊界的工作，都先從
[`template.md`](template.md) 複製一份規格。檔名使用 `NNN-short-name.md`，狀態依序為
Draft、Accepted、Implemented、Superseded。

小型 typo 或純依賴更新不需要 feature spec；重大且長期的技術取捨另外建立 ADR。


`docs-check` 檢查每份規格的必要章節、Owner、狀態、AC checkbox 與 traceability 路徑。
Implemented 不得保留未勾選 AC；SPEC-020 起每個 AC 都需有明確測試檔或 task command。
Markdown 本地連結與標題 anchor 一併檢查；靜態通過不代表已證明驗收條件的語義正確。
