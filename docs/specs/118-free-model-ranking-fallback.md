# SPEC-118：AI 模型清單的排行榜備援

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-103](103-split-agent-migrations-llm.md)

## Problem

- AI 模型清單只取 OpenRouter 本日總使用量前 50 名中，免費且支援工具呼叫的模型。前 50 名若剛好全是付費模型，清單變空，一小時後 AI 對話與月報就完全停用，即使排行榜後段仍有可用的免費模型。

## Goals

- 前 50 名沒有免費工具模型時，改從整份當日排行榜依用量取前 5 個免費工具模型。
- 前 50 名有時行為完全不變。

## Non-goals

- 不列入當日排行榜以外的免費模型（只在目錄、沒有用量的模型），也不使用固定名單。
- 不改快取時間、舊清單沿用規則與前端顯示。

## Proposed design

- `backend/llm.py` 的 `_fetch_free_models` 把排行榜依 token 用量排序後，先與免費工具目錄取前 50 名的交集；交集為空時，改與整份排行榜取交集，保留前 `_FALLBACK_MODEL_LIMIT`（5）個。
- 價格與工具支援仍來自即時目錄，所以備援不可能選到付費模型。

## Security and data isolation

- 不碰使用者資料。後端仍驗證請求的模型必須在目前清單中，伺服器的 API key 只用於免費模型。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：AI 分頁的模型清單照常顯示（目前前 50 名有免費模型，不會啟用備援）。
- 回滾方式與資料相容性：直接回滾前一版 image。

## Acceptance criteria

- [x] AC-1：Given 前 50 名沒有免費工具模型、排行榜後段有，When 抓取模型清單，Then 依用量取前 5 個，不列入排行榜外的模型。
- [x] AC-2：Given 前 50 名有免費工具模型，When 抓取模型清單，Then 只列前 50 名中的模型，不啟用備援。
- [x] AC-3：Given 整份排行榜都沒有免費工具模型，When 抓取模型清單，Then 回傳空清單，沿用既有的停用規則。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_llm.py::test_spec118_falls_back_to_most_used_free_models_outside_the_top_50` |
| AC-2 | `unit_tests/test_llm.py::test_spec118_fallback_is_unused_when_the_top_50_has_a_free_model` |
| AC-3 | `unit_tests/test_llm.py::test_spec118_no_free_model_in_the_whole_ranking_still_returns_nothing` |
