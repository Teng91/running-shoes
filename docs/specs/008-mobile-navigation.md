# SPEC-008：手機精簡導覽

- 狀態：Implemented
- Owner：Running Shoes
- 關聯 issue／ADR：SPEC-007

## Problem

手機把六個入口與帳號操作全部攤開，佔用約三分之一首屏；iPhone PWA 也需要將頂部內容與狀態列隔開。使用者必須先捲過導覽才能操作跑步內容。

## Goals

- 800px 以下預設只顯示品牌、目前頁面與選單按鈕。
- 點選選單才能展開六個功能及帳號操作，選取功能後自動收起。
- 保留手機內容左右留白與 iOS safe-area，並縮短首頁介紹區。
- 保留桌面側欄與所有功能。

## Non-goals

- 不修改後端、資料模型或跑步計算。
- 不建立另一組手機分頁，避免兩套導覽狀態不同步。

## Proposed design

使用帶 `aria-expanded/aria-controls` 的按鈕作為手機選單，與桌面共用同一組導覽。CSS 在桌面永遠顯示導覽，在手機依 `menu-open` 決定顯示。`switchTab` 同步目前功能標籤並關閉選單、將焦點交還選單按鈕，返回頁面頂端；登入重設也收起選單。手機 header sticky 並以 `calc(12px + env(safe-area-inset-top))` 留出狀態列空間。

## Security and data isolation

只調整前端呈現。帳號名稱及目前頁面標籤使用 textContent。資料與認證請求維持原有隔離。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：手機展開、切換、收起選單；桌面側欄；亮暗色與方向切換。
- PWA CSS/JS 使用一致的資產版本，更新 cache namespace。
- 回滾：回滾前端變更即可，資料格式不變。

## Acceptance criteria

- [x] Given 手機登入後，Then 選單預設收起，header 本身不超過 88px（不含系統 safe-area）。
- [x] Given 手機點開選單，Then 六個入口及主題／登出可操作；切換後自動收起且顯示正確目前頁面。
- [x] Given 桌面，Then 選單按鈕隱藏、側欄始終可見；旋轉或縮放不會讓功能消失。
- [x] Given 各尺寸及主題，Then 內容有左右留白，表單、圖表與對話框不溢出。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-4 | `python3 scripts/task.py frontend-layout` |
| 資產版本、前端行為 | `python3 scripts/task.py frontend-test` |
