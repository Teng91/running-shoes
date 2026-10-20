"""Provider-neutral public function schemas; no queries or dispatch."""

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "shoe_usage_analytics",
            "description": "以 JSON 取得跑鞋的穿著次數、近期實際里程與實際退役預測。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shoe_name": {"type": "string", "description": "選填，指定品牌或鞋款名稱。"},
                    "shoe_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "同名候選請先詢問使用者，再以 ID 選定。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_shoes",
            "description": "以 JSON 列出所有跑鞋；後端已分別計算累積里程、剩餘里程、已使用百分比與分配月跑量。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoe_summary",
            "description": "以 JSON 取得跑鞋總覽；所有數量、金額、里程與壽命皆由後端計算。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monthly_mileage_stats",
            "description": "以 JSON 取得後端計算的跑量統計及最近六個有跑量月份；必須逐字採用 mileage_km，不可自行重算或杜撰。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nearing_end_of_life",
            "description": "以 JSON 找出接近壽命的現役鞋；剩餘里程、使用率與是否需要補鞋均由後端判定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "提醒門檻，0.8 代表達預期壽命 80%。",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_shoes",
            "description": "以 JSON 比較兩雙鞋；壽命、剩餘里程與每公里成本均由後端計算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shoe_a": {"type": "string", "description": "第一雙鞋的品牌或鞋款名稱。"},
                    "shoe_b": {"type": "string", "description": "第二雙鞋的品牌或鞋款名稱。"},
                    "shoe_a_id": {"type": "integer", "minimum": 1},
                    "shoe_b_id": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoe_category_status",
            "description": "以 JSON 分析用途覆蓋與補鞋需求；也可指定鞋款取得退役後的後端判定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shoe_name": {"type": "string", "description": "選填，指定品牌或鞋款名稱。"},
                    "shoe_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "同名候選請先詢問使用者，再以 ID 選定。",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "以 JSON 搜尋市售跑鞋、規格、評價或價格，結果欄位為 title、snippet、url；只在需要外部資訊時使用。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "具體搜尋關鍵字。"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]
