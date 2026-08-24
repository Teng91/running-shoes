"""讀取使用者跑鞋資料的 agent 工具。

設計重點：
- 每個查詢都帶 `user_id`，永遠只看「目前登入使用者」的資料，與現有
  Dashboard 的 user 隔離一致。工具本身不接收 user_id 參數（由 agent
  在呼叫時自動注入），避免 LLM 去讀別人的資料。
- 回傳值統一為「人類可讀的文字 + 結構化資料」，方便直接餵回 LLM。
- 這裡只定義 tool 的 schema 與執行器；真正的派發在 agent.py。

所有函式都接受 `(db, user_id)`，回傳 `str`（給 LLM 看的摘要）。
"""

from sqlalchemy.orm import Session

from backend import models


# ── 工具實作 ────────────────────────────────────────────────────
def list_my_shoes(db: Session, user_id: int) -> str:
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id)
        .order_by(models.Shoe.is_retired, models.Shoe.date.desc())
        .all()
    )
    if not shoes:
        return "（你目前沒有任何跑鞋紀錄）"

    lines = []
    for s in shoes:
        status = "已退役" if s.is_retired else "使用中"
        cats = s.categories or []
        cat_str = ", ".join(cats) if cats else "（無）"
        life = ""
        if s.expected_mileage:
            pct = min(100, round(s.mileage / s.expected_mileage * 100))
            life = f" 壽命 {pct}%（{s.mileage}/{s.expected_mileage} km）"
        line = (
            f"- {s.brand} {s.model} [{cat_str}] [{status}] 購於 {s.date} 尺寸 {s.size} "
            f"價格 {int(s.price)} 元(原價 {int(s.orig_price)}) 月跑量 {s.monthly_km}{life}"
        )
        lines.append(line)
    return "你的跑鞋清單：\n" + "\n".join(lines)


def shoe_summary(db: Session, user_id: int) -> str:
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user_id).all()
    if not shoes:
        return "（你目前沒有任何跑鞋紀錄）"

    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]
    total_mileage = sum(s.mileage or 0 for s in shoes)
    total_spent = sum(s.price or 0 for s in active)
    total_orig = sum(s.orig_price or 0 for s in active)

    # 各鞋剩餘壽命
    life_lines = []
    for s in sorted(active, key=lambda x: (x.mileage / x.expected_mileage if x.expected_mileage else 0), reverse=True):
        if s.expected_mileage:
            remain = max(0, s.expected_mileage - s.mileage)
            pct = round(s.mileage / s.expected_mileage * 100)
            life_lines.append(f"  - {s.brand} {s.model}：已用 {pct}%，剩約 {int(remain)} km")
        else:
            life_lines.append(f"  - {s.brand} {s.model}：未設定預期壽命")

    return (
        f"跑鞋總覽：共 {len(shoes)} 雙（使用中 {len(active)} / 已退役 {len(retired)}）\n"
        f"總累積里程：{int(total_mileage)} km\n"
        f"使用中鞋款花費：{int(total_spent)} 元（原價 {int(total_orig)} 元）\n"
        "剩餘壽命：\n" + ("\n".join(life_lines) if life_lines else "  （無）")
    )


def monthly_mileage_stats(db: Session, user_id: int) -> str:
    rows = (
        db.query(models.MonthlyMileage)
        .filter(models.MonthlyMileage.user_id == user_id)
        .order_by(models.MonthlyMileage.year, models.MonthlyMileage.month)
        .all()
    )
    if not rows:
        return "（你目前沒有每月跑量紀錄）"

    rows = [r for r in rows if r.km > 0]
    if not rows:
        return "（所有月份的跑量都為 0）"

    total = sum(r.km for r in rows)
    avg = total / len(rows)
    recent = rows[-6:]
    recent_total = sum(r.km for r in recent)
    recent_avg = recent_total / len(recent)
    trend = "上升" if (recent_avg > avg) else ("下降" if recent_avg < avg else "持平")

    last = rows[-1]
    detail = "\n".join(
        f"  - {r.year}-{r.month:02d}: {r.km:.1f} km" for r in recent
    )
    return (
        f"跑量統計：有紀錄月份 {len(rows)} 個，總跑量 {total:.1f} km，月均 {avg:.1f} km\n"
        f"近 6 個月有跑量月份月均 {recent_avg:.1f} km（近 6 月合計 {recent_total:.1f} km）\n"
        f"趨勢：相較整體月均為「{trend}」\n"
        f"最近一筆：{last.year}-{last.month:02d} {last.km:.1f} km\n"
        "近 6 個月明細：\n" + detail
    )


def nearing_end_of_life(db: Session, user_id: int, threshold: float = 0.8) -> str:
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_retired.is_(False))
        .all()
    )
    candidates = []
    for s in shoes:
        # Guard against expected_mileage = 0 (user-editable) to avoid division by zero
        if s.expected_mileage and s.expected_mileage > 0:
            pct = s.mileage / s.expected_mileage
            if pct >= threshold:
                remain = max(0, s.expected_mileage - s.mileage)
                candidates.append((pct, s, remain))

    if not candidates:
        return f"目前沒有鞋的累積里程達到預期壽命的 {int(threshold*100)}%，暫時都不需要急著換。"

    candidates.sort(reverse=True)
    lines = []
    for pct, s, remain in candidates:
        other_active_same_category = sum(
            other.id != s.id and any(
                cat in (other.categories or []) for cat in (s.categories or [])
            ) for other in shoes
        )
        lifecycle_message = (
            "可以準備換鞋" if pct >= 0.9 else "先注意這雙鞋的使用狀況"
        )
        coverage_message = (
            f"同類別還有 {other_active_same_category} 雙現役鞋，暫時不用補鞋；目前單純注意這雙鞋即可"
            if other_active_same_category
            else "同類別沒有其他現役鞋，建議準備補鞋"
        )
        lines.append(
            f"- {s.brand} {s.model}：已用 {round(pct*100)}%（{int(s.mileage)}/{int(s.expected_mileage)} km），"
            f"剩約 {int(remain)} km，{lifecycle_message}。{coverage_message}。"
        )
    return "以下跑鞋已達預期壽命的提醒門檻：\n" + "\n".join(lines)


def compare_shoes(db: Session, user_id: int, shoe_a: str = "", shoe_b: str = "") -> str:
    """比較目前使用者的兩雙鞋，名稱可用「品牌 鞋款」或其中一段文字。"""
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user_id).all()

    def find_shoe(query: str):
        query = (query or "").strip().lower()
        if not query:
            return None
        exact = next(
            (s for s in shoes if f"{s.brand} {s.model}".lower() == query),
            None,
        )
        if exact:
            return exact
        return next(
            (s for s in shoes if query in f"{s.brand} {s.model}".lower()),
            None,
        )

    first = find_shoe(shoe_a)
    second = find_shoe(shoe_b)
    if not first or not second:
        available = ", ".join(f"{s.brand} {s.model}" for s in shoes)
        missing = []
        if not first:
            missing.append(f"shoe_a={shoe_a or '未提供'}")
        if not second:
            missing.append(f"shoe_b={shoe_b or '未提供'}")
        return f"找不到比較對象（{', '.join(missing)}）。目前可用鞋款：{available or '無'}"
    if first.id == second.id:
        return "比較需要兩雙不同的跑鞋，請提供不同鞋款。"

    def details(shoe: models.Shoe) -> list[str]:
        life = shoe.mileage / shoe.expected_mileage if shoe.expected_mileage else 0
        remain = max(0, shoe.expected_mileage - shoe.mileage) if shoe.expected_mileage else None
        actual_cost = shoe.price / shoe.mileage if shoe.mileage > 0 else None
        expected_cost = shoe.price / shoe.expected_mileage if shoe.expected_mileage > 0 else None
        result = [
            f"{shoe.brand} {shoe.model}（{'已退役' if shoe.is_retired else '使用中'}）",
            f"- 類別：{', '.join(cats) if (cats := shoe.categories or []) else '（無）'}",
            f"- 里程：{shoe.mileage:.1f}/{shoe.expected_mileage:.1f} km，已用 {life:.1%}，剩餘約 {remain:.1f} km" if remain is not None else f"- 里程：{shoe.mileage:.1f} km，未設定預期壽命",
            f"- 每 km 成本：{actual_cost:.2f} 元；預期每 km 成本：{expected_cost:.2f} 元" if actual_cost is not None and expected_cost is not None else "- 每 km 成本：目前尚無足夠里程資料",
            f"- 設定月跑量：{shoe.monthly_km:.1f} km",
        ]
        return result

    return "鞋款比較：\n" + "\n".join(details(first) + ["", "VS", ""] + details(second))


def shoe_category_status(db: Session, user_id: int, shoe_name: str = "") -> str:
    """分析鞋款用途的現役覆蓋，以及指定鞋款退役後是否要補鞋。

    一雙鞋可對應多個用途（例如 Daily + Tempo）。退役分析會檢查該鞋
    涵蓋的每個類別是否還有其他現役鞋作為替代。
    """
    categories = ("Daily", "Speed", "Tempo", "Race", "Trail", "Walk")
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user_id).all()
    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]

    if shoe_name:
        query = shoe_name.strip().lower()
        # Search in ALL shoes (active + retired) so user can query retired shoes too
        target = next(
            (s for s in shoes if query in f"{s.brand} {s.model}".lower()),
            None,
        )
        if not target:
            return f"找不到鞋款「{shoe_name}」，請使用品牌或鞋款名稱查詢。"
        target_cats = target.categories or []
        if not target_cats:
            return f"{target.brand} {target.model} 尚未設定用途類別。"

        # If the queried shoe is already retired, note that in the response
        is_retired_note = "（此鞋已退役）" if target.is_retired else ""

        cat_str = ", ".join(target_cats)
        # For each category the target serves, check if any other active shoe covers it
        parts = []
        for cat in target_cats:
            backup = [s for s in active if s.id != target.id and cat in (s.categories or [])]
            if backup:
                parts.append(f"{cat} 類別還有 {len(backup)} 雙現役鞋")
            else:
                parts.append(f"{cat} 類別沒有其他現役鞋")
        all_covered = all(
            any(s.id != target.id and cat in (s.categories or []) for s in active)
            for cat in target_cats
        )
        action = "暫時不需要補鞋" if all_covered else "建議準備補鞋"
        return (
            f"{target.brand} {target.model} {is_retired_note}屬於 {cat_str} 類別。"
            f"若它退役後：" + "、".join(parts) + f"，因此{action}。"
        )

    lines = ["跑鞋用途分類狀態（只把現役鞋算作目前可用）："]
    for category in categories:
        active_count = sum(category in (s.categories or []) for s in active)
        retired_count = sum(category in (s.categories or []) for s in retired)
        action = "需要補鞋" if active_count == 0 else "目前不需要補鞋"
        lines.append(
            f"- {category}：現役 {active_count} 雙、退役 {retired_count} 雙，{action}"
        )
    return "\n".join(lines)


# ── 派發表：讓 agent 用 tool name 找到對應函式 ────────────────
REGISTRY: dict[str, callable] = {
    "list_my_shoes": list_my_shoes,
    "shoe_summary": shoe_summary,
    "monthly_mileage_stats": monthly_mileage_stats,
    "nearing_end_of_life": nearing_end_of_life,
    "compare_shoes": compare_shoes,
    "shoe_category_status": shoe_category_status,
}


# ── 給 LLM 看的工具說明（文字格式，不用各家原生 tool-calling）──
TOOL_SPEC_TEXT = """當你需要讀取使用者的資料時，請在回覆中插入一個工具標記，
格式為：<tool>工具名稱 {JSON 參數}</tool>
可用工具：
- list_my_shoes：列出使用者所有跑鞋。參數：{}
- shoe_summary：跑鞋總覽（鞋數/里程/花費/剩餘壽命）。參數：{}
- monthly_mileage_stats：每月跑量統計與趨勢。參數：{}
- nearing_end_of_life：找快到壽命的鞋，參數：{"threshold": 0.8}（0~1，可選）
- compare_shoes：比較兩雙跑鞋，參數：{"shoe_a": "品牌 鞋款", "shoe_b": "品牌 鞋款"}
- shoe_category_status：分析 Daily/Speed/Tempo/Race/Trail 類別覆蓋與補鞋需求，參數：{"shoe_name": "可選，指定鞋款"}
- web_search：上網搜尋市售鞋款/評價/價格，參數：{"query": "搜尋關鍵字"}

規則：
1. 先根據問題決定要呼叫哪些工具，插入對應標記（可多個）。
2. 工具標記**單獨成行**，放在你需要的分析位置，但最終給使用者的建議文字裡不要包含標記本身。
3. **在呼叫工具之前，先用一段文字說明你的推理**：你為什麼要查這個、你預期找到什麼。這段文字會顯示給使用者看，讓他們知道你的思考過程。
4. 拿到工具結果後，若還需要更多資訊可再呼叫；資訊足夠時，給一段不含標記的最終建議。
5. 不要呼叫不存在的工具。
6. **重點：當使用者說「查給我看」、「顯示資料」、「結果呢」時，你必須實際呼叫對應的 `<tool>`，而不是只說「我來查一下」然後沒有給出任何數據。如果不呼叫工具，你無法看到資料庫中的實際內容。**"""


def parse_tool_calls(text: str) -> list[dict]:
    """從 LLM 回傳文字中解析 <tool>name {json}</tool> 標記。

    回傳 [{"name": str, "arguments": dict}, ...]。解析失敗的參數會用 {} 代替。
    """
    import re, json as _json
    out = []
    for m in re.finditer(r"<tool>\s*([A-Za-z_]+)\s*(\{.*?\})\s*</tool>", text, re.DOTALL):
        name = m.group(1)
        raw = m.group(2) or "{}"
        try:
            args = _json.loads(raw)
        except Exception:
            args = {}
        out.append({"name": name, "arguments": args})
    return out


def strip_tool_markers(text: str) -> str:
    """移除最終回覆中的 <tool> 標記，只留給使用者看的文字。"""
    import re
    return re.sub(r"<tool>.*?</tool>", "", text, flags=re.DOTALL).strip()
