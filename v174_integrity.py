"""Conservative V17.4 data-integrity diagnostics. Never silently promote partial data."""
from __future__ import annotations
from datetime import date


def _nonnegative(value):
    try:
        x = int(value)
        return max(0, x)
    except (TypeError, ValueError, OverflowError):
        return 0


def _day(value):
    if value is None:
        return ""
    s = str(value).strip()[:10].replace("/", "-")
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return ""


def assess_snapshot(snapshot: dict | None) -> dict:
    if not isinstance(snapshot, dict) or not snapshot:
        return {"status": "NO_DATA", "label": "尚無模型資料", "issues": ["請先執行完整市場更新。"], "metrics": {}, "dates": {}, "safe_to_claim_synced": False}
    c = snapshot.get("coverage") or {}
    o = c.get("official_eod") or {}
    s = snapshot.get("session") or {}
    tw = _day(o.get("raw_twse_date") or o.get("twse_date"))
    ot = _day(o.get("raw_tpex_date") or o.get("tpex_date"))
    common = _day(s.get("common_complete_date") or o.get("model_sync_date") or snapshot.get("price_date"))
    price = _day(snapshot.get("price_date"))
    mother, valid = _nonnegative(c.get("requested")), _nonnegative(c.get("feature_valid"))
    model = _nonnegative(snapshot.get("full_universe_model_n") or snapshot.get("candidate_n"))
    tw_count, ot_count = _nonnegative(c.get("twse_universe")), _nonnegative(c.get("tpex_universe"))
    issues, blockers = [], []
    def problem(message, blocking=False):
        issues.append(message)
        if blocking:
            blockers.append(message)
    if not common:
        problem("缺少或無效的共同完整交易日；不可宣稱資料已同步。", True)
    if not tw or not ot:
        problem("上市或上櫃原始來源日期缺漏或格式錯誤，無法驗證來源時效。", True)
    if tw and ot and tw != ot:
        if common and common <= min(tw, ot):
            problem(f"上市來源 {tw}、上櫃來源 {ot} 不同日；模型基準 {common} 需確認完整回退及覆蓋。")
        else:
            problem(f"上市來源 {tw}、上櫃來源 {ot} 不同日，且模型基準未安全回退。", True)
    if common and ((tw and common > tw) or (ot and common > ot)):
        problem("模型日比部分官方來源更新；可能混用未確認資料。", True)
    if price and common and price != common:
        problem(f"快照價格日 {price} 不等於共同模型日 {common}。", True)
    if not mother:
        problem("普通股母體家數缺漏。", True)
    if not tw_count or not ot_count:
        problem("上市／上櫃家數缺漏，無法確認兩市場皆有涵蓋。", True)
    if mother and tw_count and ot_count and mother != tw_count + ot_count:
        problem("普通股總母體與上市／上櫃分項家數不同；需核對去重及統計口徑。")
    if not model:
        problem("可投資模型家數為零或缺漏。", True)
    if valid and model > valid:
        problem("可投資家數超過有效歷史家數。", True)
    if mother and model > mother:
        problem("可投資家數超過普通股母體家數。", True)
    if mother and valid > mother:
        problem("有效歷史家數超過普通股母體家數。", True)
    errors = c.get("errors") or []
    if errors:
        problem(f"行情資料來源回報 {len(errors)} 項錯誤或警示，請展開來源紀錄。")
    if s.get("postclose_pending"):
        problem("當日完整官方收盤檔尚未齊備，仍採前一完整交易日。")
    status = "BLOCK" if blockers else ("CHECK" if issues else "OK")
    return {
        "status": status,
        "label": {"BLOCK": "資料可信度不足，禁止標示同步完成", "CHECK": "資料存在需核對事項", "OK": "快照內部一致性檢查通過"}[status],
        "issues": issues, "blockers": blockers,
        "safe_to_claim_synced": status == "OK" and tw == ot == common,
        "metrics": {"上市母體": tw_count, "上櫃母體": ot_count, "普通股母體": mother,
                    "歷史有效": valid, "可投資模型": model,
                    "公司／法人可比資料": _nonnegative(snapshot.get("research_breadth_n")),
                    "排除過期資料": _nonnegative(c.get("stale_excluded"))},
        "dates": {"上市來源": tw or "待確認", "上櫃來源": ot or "待確認", "統一模型日": common or "待確認"},
    }
