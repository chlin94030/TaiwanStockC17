"""Fast reading panel shown while the V17.2 full model is updating.

The briefing is intentionally *not* an alpha factor. It gives the user useful
context during a multi-minute full-market refresh: overnight global stress,
plain-language factor names, a cached previous-model snapshot, and a small set
of relevant public news headlines. News never changes short/mid/long scores.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import email.utils
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import requests

TZ = dt.timezone(dt.timedelta(hours=8))

NEWS_QUERIES = (
    ("台股與半導體", "台股 台積電 半導體 AI 晶片"),
    ("美國利率與總經", "聯準會 利率 通膨 美債 殖利率 美股"),
    ("AI／晶片供應鏈", "輝達 AMD 博通 AI 晶片 出口管制 供應鏈"),
)

PREFERRED_CHINESE_SOURCES = {
    "中央社", "自由時報", "經濟日報", "工商時報", "鉅亨網", "Yahoo奇摩股市",
    "MoneyDJ", "財訊快報", "時報資訊", "聯合新聞網", "中時新聞網", "財經新報",
    "商業周刊", "今周刊", "CTWANT", "非凡新聞", "風傳媒", "鏡週刊",
}

HUMAN_FACTORS = {
    "sox": "美國半導體",
    "ndx": "那斯達克100",
    "tsm_adr": "台積電ADR",
    "spx": "標普500",
    "vix": "市場恐慌指數",
    "nq_fut": "那斯達克100期貨",
    "es_fut": "標普500期貨",
    "tnx": "美國10年債殖利率",
    "dxy": "美元指數",
}

NEGATIVE_WORDS = (
    "plunge", "plunges", "selloff", "sell-off", "slump", "falls", "drop", "drops",
    "tariff", "tariffs", "export curb", "export control", "ban", "sanction", "war",
    "hot inflation", "inflation accelerates", "hawkish", "yield surge", "yields jump",
    "下跌", "重挫", "暴跌", "關稅", "禁令", "出口管制", "升息", "通膨升溫", "殖利率攀升",
)
POSITIVE_WORDS = (
    "rally", "rallies", "surge", "rises", "gain", "gains", "record high", "beats",
    "rate cut", "cuts rates", "easing", "stimulus", "strong demand", "upgrade",
    "上漲", "大漲", "反彈", "降息", "寬鬆", "刺激", "需求強勁", "上修", "創新高",
)


def _now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    title = re.sub(r"\s+-\s+[^-]{1,50}$", lambda m: m.group(0) if _contains_cjk(title) else "", title)
    return title[:240]


def _topic(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("nvidia", "amd", "broadcom", "semiconductor", "chip", "tsmc", "台積", "半導體", "晶片", "ai")):
        return "半導體／AI"
    if any(k in t for k in ("fed", "inflation", "yield", "bond", "rate", "聯準會", "通膨", "殖利率", "利率")):
        return "利率／總經"
    if any(k in t for k in ("tariff", "export", "china", "war", "sanction", "關稅", "出口", "中國", "戰爭", "制裁")):
        return "政策／地緣"
    if any(k in t for k in ("taiwan", "taiex", "台股", "台灣", "加權")):
        return "台股／權值"
    return "市場"


def _headline_bias(title: str) -> str:
    t = title.lower()
    neg = sum(1 for k in NEGATIVE_WORDS if k in t)
    pos = sum(1 for k in POSITIVE_WORDS if k in t)
    if neg >= 1 and neg > pos:
        return "可能偏空"
    if pos >= 1 and pos > neg:
        return "可能偏多"
    return "待判讀"


def _parse_pubdate_dt(text: str) -> dt.datetime | None:
    try:
        d = email.utils.parsedate_to_datetime(text)
        if d is None:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(TZ)
    except Exception:
        return None


def _parse_pubdate(text: str) -> str:
    d = _parse_pubdate_dt(text)
    return d.strftime("%m/%d %H:%M") if d else ""


def _fetch_google_news(query: str, category: str, timeout: int = 6) -> list[dict]:
    params = {
        "q": query,
        "hl": "zh-TW",
        "gl": "TW",
        "ceid": "TW:zh-Hant",
    }
    url = "https://news.google.com/rss/search?" + urlencode(params)
    r = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 AlphaRadar/17.2", "Accept": "application/rss+xml,application/xml,text/xml,*/*"},
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out: list[dict] = []
    for item in root.findall(".//item")[:10]:
        title = _clean_title(item.findtext("title") or "")
        link = str(item.findtext("link") or "").strip()
        source_node = item.find("source")
        source = str(source_node.text or "").strip() if source_node is not None else ""
        if not title:
            continue
        published_dt = _parse_pubdate_dt(item.findtext("pubDate") or "")
        out.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published_dt.strftime("%m/%d %H:%M") if published_dt else "",
            "published_iso": published_dt.isoformat() if published_dt else "",
            "published_ts": published_dt.timestamp() if published_dt else 0.0,
            "category": category,
            "topic": _topic(title),
            "bias": _headline_bias(title),
            "is_chinese_title": _contains_cjk(title),
            "is_preferred_source": source in PREFERRED_CHINESE_SOURCES or _contains_cjk(source),
        })
    return out


def _news_score(row: dict, now: dt.datetime) -> tuple:
    published_ts = float(row.get("published_ts") or 0.0)
    age_hours = 9999.0
    if published_ts > 0:
        age_hours = max(0.0, (now.timestamp() - published_ts) / 3600.0)
    chinese = 1 if row.get("is_chinese_title") else 0
    preferred_source = 1 if row.get("is_preferred_source") else 0
    topic_bonus = {
        "台股／權值": 3,
        "半導體／AI": 3,
        "利率／總經": 2,
        "政策／地緣": 2,
        "市場": 1,
    }.get(str(row.get("topic") or ""), 0)
    recency = -age_hours
    return (preferred_source, chinese, topic_bonus, recency)


def fetch_news_digest(
    data_dir: Path,
    *,
    max_items: int = 7,
    cache_minutes: int = 30,
    max_age_hours: int = 120,
    force: bool = False,
) -> dict:
    data_dir = Path(data_dir)
    if os.getenv("ALPHA_RADAR_DISABLE_NEWS_NETWORK", "0") == "1":
        return {"available": False, "items": [], "fetched_at": _now().isoformat(timespec="seconds"), "source": "", "errors": ["NEWS_NETWORK_DISABLED"]}
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = data_dir / "market_news_digest.json"
    now = _now()
    if not force and cache.exists():
        try:
            obj = json.loads(cache.read_text(encoding="utf-8"))
            fetched = dt.datetime.fromisoformat(str(obj.get("fetched_at") or ""))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=TZ)
            if (now - fetched).total_seconds() <= cache_minutes * 60:
                return obj
        except Exception:
            pass

    rows: list[dict] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(NEWS_QUERIES)) as ex:
        futs = {ex.submit(_fetch_google_news, q, cat): cat for cat, q in NEWS_QUERIES}
        for fut in as_completed(futs):
            try:
                rows.extend(fut.result())
            except Exception as exc:
                errors.append(f"{futs[fut]}:{type(exc).__name__}")

    # Recency filter first; avoid month-old and year-old stale headlines.
    fresh_rows = []
    for row in rows:
        published_iso = str(row.get("published_iso") or "")
        published_dt = dt.datetime.fromisoformat(published_iso) if published_iso else None
        if published_dt is None:
            continue
        age_hours = (now - published_dt).total_seconds() / 3600.0
        if age_hours <= max_age_hours:
            fresh_rows.append(row)

    # If sources are too sparse, allow a slightly wider fallback, but still recent.
    if len(fresh_rows) < max(3, max_items // 2):
        for row in rows:
            if row in fresh_rows:
                continue
            published_iso = str(row.get("published_iso") or "")
            published_dt = dt.datetime.fromisoformat(published_iso) if published_iso else None
            if published_dt is None:
                continue
            age_hours = (now - published_dt).total_seconds() / 3600.0
            if age_hours <= max_age_hours * 2:
                fresh_rows.append(row)

    # De-duplicate near-identical syndications while preserving topical diversity.
    dedup: list[dict] = []
    seen: set[str] = set()
    for row in sorted(fresh_rows, key=lambda x: _news_score(x, now), reverse=True):
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", row["title"].lower())[:110]
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(row)

    chosen: list[dict] = []
    by_topic: dict[str, list[dict]] = {}
    for row in dedup:
        by_topic.setdefault(str(row.get("topic") or "市場"), []).append(row)

    # Round-robin by important topics, Chinese and recent first.
    for topic in ("台股／權值", "半導體／AI", "利率／總經", "政策／地緣", "市場"):
        candidates = sorted(by_topic.get(topic, []), key=lambda x: _news_score(x, now), reverse=True)
        hit = next((x for x in candidates if x not in chosen), None)
        if hit is not None:
            chosen.append(hit)
        if len(chosen) >= max_items:
            break

    for row in sorted(dedup, key=lambda x: _news_score(x, now), reverse=True):
        if len(chosen) >= max_items:
            break
        if row not in chosen:
            chosen.append(row)

    # Strip helper keys before persisting.
    cleaned_items = []
    for row in chosen:
        cleaned_items.append({
            "title": row.get("title") or "",
            "link": row.get("link") or "",
            "source": row.get("source") or "",
            "published": row.get("published") or "",
            "category": row.get("category") or "",
            "topic": row.get("topic") or "市場",
            "bias": row.get("bias") or "待判讀",
            "is_chinese_title": bool(row.get("is_chinese_title")),
        })

    obj = {
        "available": bool(cleaned_items),
        "items": cleaned_items,
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "Google News RSS（中文優先標題彙整）",
        "errors": errors,
        "max_age_hours": max_age_hours,
    }
    if cleaned_items:
        try:
            cache.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return obj

    if cache.exists():
        try:
            old = json.loads(cache.read_text(encoding="utf-8"))
            old["stale"] = True
            old["errors"] = list(old.get("errors") or []) + errors
            return old
        except Exception:
            pass
    return obj


def human_global_summary(global_ctx: dict | None) -> dict:
    g = global_ctx or {}
    if not g.get("available"):
        return {"headline": "全球市場即時摘要暫不可用；台股核心模型仍可獨立更新。", "factors": [], "details": []}
    shock = g.get("shock_score")
    try:
        shock_f = float(shock)
    except Exception:
        shock_f = None
    mode = str(g.get("mode") or "UNKNOWN")
    if mode == "PANIC":
        headline = "隔夜外部壓力高：開盤先縮小首筆部位；若優質股相對抗跌且從低點回升，再評估錯殺反轉。"
    elif mode == "STRESS":
        headline = "隔夜外部壓力偏高：避免開盤追價，優先觀察相對大盤有韌性的標的。"
    else:
        headline = "隔夜外部壓力一般：以台股自身趨勢、相對強弱與買點條件為主。"
    if shock_f is not None:
        headline = f"隔夜市場壓力 {shock_f:.0f}/100。" + headline

    returns = g.get("returns_pct") or {}
    comps = g.get("components") or {}
    ordered = sorted(comps.items(), key=lambda kv: float((kv[1] or {}).get("risk") or 0), reverse=True)
    keys = [k for k, _ in ordered[:5]]
    for k in ("sox", "ndx", "tsm_adr", "vix", "nq_fut"):
        if k not in keys and returns.get(k) is not None:
            keys.append(k)
        if len(keys) >= 5:
            break
    factors = []
    details = []
    for key in keys[:5]:
        try:
            val = float(returns.get(key))
        except Exception:
            continue
        name = HUMAN_FACTORS.get(key, key)
        factors.append({"name": name, "value_pct": val, "key": key})
        tone = "偏空" if val < -1.0 else "偏多" if val > 1.0 else "中性"
        details.append(f"{name} {val:+.1f}%（{tone}）")
    return {"headline": headline, "factors": factors, "details": details}


def previous_model_digest(snapshot: dict | None) -> dict:
    snap = snapshot or {}
    stocks = [x for x in (snap.get("stocks") or []) if isinstance(x, dict)]
    out = {"date": str(snap.get("price_date") or ""), "short": [], "mid": [], "long": []}
    for h in ("short", "mid", "long"):
        ranked = sorted(stocks, key=lambda x: ((x.get("horizons") or {}).get(h) or {}).get("ranking_score", -1), reverse=True)
        out[h] = [str(x.get("name") or x.get("ticker") or "") for x in ranked[:3]]
    return out


def build_waiting_brief(data_dir: Path, global_fetcher, previous_snapshot: dict | None = None) -> dict:
    """Fetch global context + news in parallel so the reading panel appears fast."""
    data_dir = Path(data_dir)
    gctx: dict = {}
    news: dict = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_g = ex.submit(global_fetcher)
        f_n = ex.submit(fetch_news_digest, data_dir)
        try:
            gctx = f_g.result()
        except Exception:
            gctx = {"available": False}
        try:
            news = f_n.result()
        except Exception:
            news = {"available": False, "items": []}
    return {
        "global": gctx,
        "global_summary": human_global_summary(gctx),
        "news": news,
        "previous": previous_model_digest(previous_snapshot),
        "built_at": _now().isoformat(timespec="seconds"),
    }
