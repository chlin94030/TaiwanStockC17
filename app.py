"""Alpha Radar V17.0 Goal-Complete — canonical full-market multi-horizon decision system."""
from __future__ import annotations

from pathlib import Path
from v174_integrity import assess_snapshot
import gc
import html
import os
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import radar_service as service
from industry_profile import fine_industry
from intraday_engine import FinMindRealtimeClient, candidate_tickers, full_market_tickers, dynamic_candidate_pool, filter_realtime_df, market_is_open, rerank_snapshot
from market_data import DailyPriceStore, _taipei_timestamp, provider_runtime_status
from policy_engine import HORIZONS
from presentation import investment_view
from trading_calendar import session_reference_policy, INTRADAY, POSTCLOSE
from operational_tools import ScanBusyError, safe_error_text, scan_lock
from recommendation_engine import rank_intraday_buys, summarize_buy_gate_failures, rank_next_session, rank_next_session_live
from strategy_config import LIVE_SCAN, DOCTOR_VERSION, CANONICAL_MODEL_POLICY
from doctor_engine import buy_decision, holding_decision
from global_context import fetch_global_context
from market_briefing import build_waiting_brief, human_global_summary

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ALPHA_RADAR_DATA_DIR", str(ROOT / "data")))

VIEWS = ["總覽", "盤中買點", "明日關注", "推薦總表", "短線", "中線", "長線", "個股", "資料健檢"]
H_LABEL = {"short": "短線 · 約2週", "mid": "中線 · 約2個月", "long": "長線 · 約6個月"}
REGIME = {"BULL": "大盤偏多", "NEUTRAL": "大盤整理", "BEAR": "大盤偏弱", "UNKNOWN": "大盤待確認"}
FAMILY_LABELS = {
    "完整資料": "full",
    "價格＋公司資料": "business_confirmed",
    "價格＋法人": "flow_confirmed",
    "只看價格": "price_only",
}
HOLD_LABELS = {
    "DATA_UNVERIFIED": "價格尚未核對。",
    "ORIGINAL_STRUCTURE_INVALIDATED": "已跌破原防守價，需優先重新評估。",
    "ORIGINAL_THESIS_INVALIDATED": "原買進理由已不成立，需重新評估。",
    "PROTECTION_TRIGGER_REVIEW_EXECUTION": "已碰到獲利保護價，請依原紀律處理。",
    "ORIGINAL_THESIS_UNKNOWN_MANUAL_REVIEW": "缺少原始防守條件，無法自動判斷。",
    "ORIGINAL_RULES_NOT_BREACHED_NOT_A_RETURN_GUARANTEE": "原防守條件尚未被破壞。",
}

def _bootstrap_secrets():
    """Expose Streamlit secrets to the data layer without hard-coding tokens."""
    for key in ("FINMIND_TOKEN",):
        if os.getenv(key):
            continue
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value not in (None, ""):
            os.environ[key] = str(value)


@st.cache_data(ttl=int(LIVE_SCAN.get("cache_ttl_seconds", 52)), show_spinner=False)
def _cached_realtime_snapshot(snapshot_id: str, tickers: tuple[str, ...]):
    """Reuse the same complete quote batch while users switch views.

    The one-minute full-market quote batch is reused while the user switches
    views, preventing duplicate provider calls inside the same refresh window.
    """
    client = FinMindRealtimeClient()
    return client.snapshots(list(tickers))


@st.cache_data(ttl=int(LIVE_SCAN.get("cache_ttl_seconds", 52)), show_spinner=False)
def _cached_verified_execution_snapshot(snapshot_id: str, tickers: tuple[str, ...]):
    """Official-verified quote batch for prices that can trigger a trade decision."""
    client = FinMindRealtimeClient()
    return client.verified_snapshots(list(tickers))


@st.cache_data(ttl=600, show_spinner=False)
def _cached_global_context():
    """Best-effort US/global overnight context; never blocks Taiwan core model."""
    return fetch_global_context(DATA_DIR, max_age_minutes=10)


CSS = r"""
<style>
:root{
  --paper:#f3f0e7; --surface:#fffdfa; --ink:#0e1116; --muted:#656a74;
  --line:#d1cec4; --blue:#1248c7; --red:#d93025; --green:#0b7d5c;
  --amber:#9a4d00; --soft:#ece8de;
}
.stApp{background:var(--paper);color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
header[data-testid="stHeader"]{background:rgba(245,244,239,.96);backdrop-filter:blur(8px);}
.block-container{max-width:1120px;padding-top:4.75rem;padding-bottom:4rem;}
@supports (padding-top:env(safe-area-inset-top)){
 .block-container{padding-top:calc(4.75rem + env(safe-area-inset-top));}
}
#MainMenu,footer{visibility:hidden;}
.mast{display:grid;grid-template-columns:1fr auto;align-items:end;border-top:5px solid var(--ink);border-bottom:1px solid var(--ink);padding:13px 1px 11px;margin-bottom:10px;}
.brand{font-size:1.62rem;font-weight:950;letter-spacing:-.055em;line-height:1}.brand span{color:var(--blue)}
.version{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.76rem;color:var(--muted);letter-spacing:.06em;}
.marketbar{display:flex;gap:13px;flex-wrap:wrap;align-items:center;padding:7px 0 10px;border-bottom:1px solid var(--line);font-size:.88rem;color:var(--muted);}
.marketbar b{color:var(--ink)}
.section-kicker{font-size:.72rem;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:18px 0 5px;}
.section-title{font-size:1.32rem;font-weight:950;letter-spacing:-.025em;margin:0 0 9px;}
.rankrow{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:10px;align-items:center;background:var(--surface);border-top:1px solid var(--ink);border-bottom:1px solid var(--line);padding:13px 10px 12px;margin-top:9px;}
.rankno{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1.28rem;font-weight:900;color:#a3a39d;align-self:start;padding-top:2px;}
.stockname{font-size:1.28rem;font-weight:950;line-height:1.05;letter-spacing:-.025em}.stockcode{font-size:.79rem;font-weight:750;color:var(--muted);margin-left:5px;}
.industry{font-size:.82rem;color:#4d5159;margin-top:4px;line-height:1.15;}.tagrow{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}.tag{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;border:1px solid var(--line);background:#f7f6f1;font-size:.73rem;font-weight:850;color:#434851}.tag.blue{color:#0b57d0;border-color:#c9daf8;background:#f2f7ff}.tag.red{color:#8a3b11;border-color:#ead2c6;background:#fff6f1}
.quote{text-align:right;min-width:92px}.price{font-size:1.30rem;font-weight:950;line-height:1}.change{font-size:.87rem;font-weight:900;margin-top:5px}.up{color:var(--red)}.down{color:var(--green)}.flat{color:var(--muted)}
.signal{display:grid;grid-template-columns:minmax(130px,.34fr) 1fr;gap:12px;background:var(--surface);padding:9px 10px 11px;border-bottom:1px solid var(--line);}
.signal-title{font-size:1.02rem;font-weight:950;color:var(--blue);line-height:1.3}.signal-copy{font-size:.91rem;line-height:1.45;color:#3f434a}.risk{color:#8a3b11}
.entryline{display:flex;flex-wrap:wrap;gap:7px;align-items:center;background:#fffefb;padding:8px 10px 5px;font-size:.80rem}.entrychip{display:inline-flex;align-items:center;padding:3px 8px;border:1px solid var(--line);border-radius:999px;background:#f7f6f1;font-weight:850;color:#3f434a}.entrychip b{color:var(--ink);margin-left:4px}.entryaction{font-weight:950;color:#8a3b11}.entryok{color:var(--green)}.overnight{color:#8a3b11;font-weight:850}.entrywhy{background:#fffefb;border-bottom:1px solid var(--line);padding:0 10px 8px;font-size:.76rem;line-height:1.35;color:var(--muted)}.scoreline{display:flex;flex-wrap:wrap;gap:6px;background:#fffefb;padding:6px 10px 8px;border-bottom:1px solid var(--line)}.scorechip{font-size:.72rem;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 7px}.scorechip b{color:var(--ink)}
.quick{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-top:0;background:var(--surface);}
.q{padding:9px 10px;border-right:1px solid var(--line);min-width:0}.q:last-child{border-right:0}.qk{font-size:.72rem;color:var(--muted);font-weight:800}.qv{font-size:.94rem;font-weight:900;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.liveflag{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;font-weight:900;color:var(--green);letter-spacing:.04em}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px rgba(7,135,93,.12)}
.offflag{font-size:.78rem;font-weight:850;color:var(--muted)}
.datagrid{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);background:var(--surface);margin:8px 0 12px}.datum{padding:10px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.datum:nth-child(4n){border-right:0}.dk{font-size:.74rem;color:var(--muted);font-weight:800}.dv{font-size:1rem;font-weight:950;margin-top:3px}.ds{font-size:.73rem;color:var(--muted);margin-top:2px;line-height:1.3}.flowbar{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:6px 0 10px}.flowbar>div{background:var(--surface);padding:8px 9px}.flowbar small{display:block;color:var(--muted);font-weight:800}.flowbar b{display:block;margin-top:2px;font-size:.95rem}.overview{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:6px 0 14px}.ovcol{border:1px solid var(--line);background:var(--surface)}.ovhead{padding:10px;border-bottom:1px solid var(--line);font-weight:950}.ovitem{display:grid;grid-template-columns:32px 1fr;gap:8px;padding:10px;border-bottom:1px solid var(--line)}.ovitem:last-child{border-bottom:0}.ovrank{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#9a9b95;font-weight:900}.ovname{font-weight:900}.ovmeta{font-size:.8rem;color:var(--muted);margin-top:2px}.consensus{border:1px solid var(--line);background:var(--surface);padding:10px 11px;margin:10px 0 6px}.consensus b{font-size:1rem}.sectorbar{display:flex;gap:7px;overflow-x:auto;padding:4px 0 10px;margin-bottom:4px;scrollbar-width:none}.sectorbar::-webkit-scrollbar{display:none}.sectorpill{flex:0 0 auto;border:1px solid var(--line);background:var(--surface);padding:7px 10px;border-radius:999px;font-size:.78rem;font-weight:850;color:#3f434a}.sectorpill b{color:var(--ink);margin-left:4px}.sectorpill.hot{border-color:#bfd3f7;background:#f1f6ff;color:#0b57d0}.sectorpill.weak{background:#faf4f0;color:#8a3b11}.consensus-note{font-size:.79rem;color:var(--muted);margin-top:4px}
.plan{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:8px}.plan>div{background:var(--surface);padding:9px}.plan small{display:block;color:var(--muted);font-weight:800}.plan b{display:block;margin-top:3px;font-size:.98rem}
.chartchips{display:flex;gap:12px;align-items:center;font-size:.76rem;color:var(--muted);margin:4px 0 1px;flex-wrap:wrap}.chipline{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:5px}.ma5{background:#111318}.ma20{background:#0b57d0}.ma60{background:#f08c00}.ma120{background:#7b61ff}.ma240{background:#2f9e44}.bb{background:#d9480f}.ind-caption{font-size:.78rem;color:var(--muted);margin:2px 0 6px}
.mini-note{font-size:.78rem;color:var(--muted);line-height:1.4}
[data-testid="stExpander"]{border:0!important;border-bottom:1px solid var(--line)!important;border-radius:0!important;background:transparent!important;}[data-testid="stExpander"] summary{padding-left:0!important;padding-right:0!important;font-weight:850!important;}
div[data-baseweb="tab-list"]{gap:4px}button[data-baseweb="tab"]{font-weight:850}.stRadio [role="radiogroup"]{gap:.35rem!important;align-items:center}.stRadio label{background:var(--surface);border:1px solid var(--line);padding:.16rem .58rem;border-radius:999px}.stRadio label p{color:var(--ink)!important;font-weight:850!important}button[data-baseweb="tab"]{color:var(--ink)!important}
.stButton>button{border-radius:5px!important;font-weight:850!important;min-height:42px}.stButton>button[kind="primary"]{background:var(--ink)!important;border-color:var(--ink)!important;}
hr{border-color:var(--line)!important}
@media(max-width:720px){
 .stApp{font-size:17.5px}.block-container{padding:4.35rem .72rem 3rem}.mast{padding:13px 0 10px;margin-top:.15rem}.brand{font-size:1.52rem}.version{font-size:.68rem}
 .marketbar{font-size:.84rem;gap:8px 11px}.rankrow{grid-template-columns:36px minmax(0,1fr) auto;padding:12px 7px 11px;gap:7px}.rankno{font-size:1.08rem}.stockname{font-size:1.30rem}.stockcode{font-size:.78rem}.industry{font-size:.84rem}.quote{min-width:78px}.price{font-size:1.25rem}.change{font-size:.88rem}
 .signal{grid-template-columns:1fr;gap:3px;padding:9px 7px 10px}.signal-title{font-size:1.05rem}.signal-copy{font-size:.96rem;line-height:1.42}
 .quick{grid-template-columns:repeat(2,1fr)}.q:nth-child(2){border-right:0}.q:nth-child(-n+2){border-bottom:1px solid var(--line)}.qk{font-size:.78rem}.qv{font-size:1rem}
 .datagrid{grid-template-columns:repeat(2,1fr)}.datum:nth-child(odd){border-right:1px solid var(--line)}.datum:nth-child(even){border-right:0}.dk{font-size:.80rem}.dv{font-size:1.05rem}.ds{font-size:.77rem}
 .plan{grid-template-columns:repeat(2,1fr)}.overview{grid-template-columns:1fr}.flowbar{grid-template-columns:repeat(2,1fr)}.section-title{font-size:1.25rem}
 .stRadio [role="radiogroup"]{gap:.22rem!important}.stRadio label{font-size:.92rem!important;padding:.14rem .45rem!important}
 @supports (padding-top:env(safe-area-inset-top)){.block-container{padding-top:calc(4.35rem + env(safe-area-inset-top));}}
}

.decision{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-top:0;margin-bottom:0}.decision>div{background:#fffefb;padding:8px 9px}.decision small{display:block;color:var(--muted);font-size:.69rem;font-weight:800}.decision b{display:block;margin-top:2px;font-size:.91rem}.decision-action{grid-column:1/-1;background:#f7f6f1!important;font-weight:900;color:#3f434a}.decision-reasons{grid-column:1/-1;background:#fbfaf6!important;color:var(--muted);font-size:.78rem}.gatebar{display:flex;gap:7px;flex-wrap:wrap;margin:7px 0 9px}.gatechip{border:1px solid var(--line);background:#fffefb;padding:5px 7px;font-size:.76rem;color:var(--muted)}.decision-action.buy{color:var(--green)}.decision-action.wait{color:#8a3b11}@media(max-width:720px){.decision{grid-template-columns:repeat(2,1fr)}.decision small{font-size:.72rem}.decision b{font-size:.94rem}}.phasebar{border:1px solid var(--line);background:var(--surface);padding:10px 11px;margin:8px 0 12px}.phasebar b{font-weight:950}.phasebar .mini-note{margin-top:3px}.buyempty{border:1px solid var(--line);background:#fffefb;padding:12px;margin:8px 0;color:#4d5159;font-size:.9rem}.buyempty b{color:var(--ink)}

/* V16.7 doctor readability: custom light paper must override browser/Streamlit dark label text. */
[data-testid="stWidgetLabel"] p,
.stTextInput label p,.stSelectbox label p,.stNumberInput label p,.stCheckbox label p,
.stRadio>label p,.stTextInput label,.stSelectbox label,.stNumberInput label,.stCheckbox label{color:var(--ink)!important;font-weight:800!important}
.doctor-hero{border:1px solid var(--line);border-top:4px solid var(--ink);background:var(--surface);padding:14px 15px;margin:10px 0 8px}
.doctor-hero.buy{border-top-color:var(--green)}.doctor-hero.wait{border-top-color:var(--amber)}.doctor-hero.sell{border-top-color:var(--red)}.doctor-hero.hold{border-top-color:var(--blue)}
.doctor-kicker{font-size:.72rem;font-weight:900;letter-spacing:.10em;color:var(--muted);text-transform:uppercase}.doctor-title{font-size:1.35rem;font-weight:950;letter-spacing:-.02em;margin-top:3px}.doctor-sub{font-size:.84rem;color:var(--muted);margin-top:5px;line-height:1.4}
.doctor-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:8px 0 10px}.doctor-grid>div{background:var(--surface);padding:10px}.doctor-grid small{display:block;color:var(--muted);font-size:.72rem;font-weight:800}.doctor-grid b{display:block;margin-top:3px;font-size:1rem}.doctor-reasons{border-left:3px solid var(--line);padding:6px 10px;margin:8px 0 12px;color:#3f434a;font-size:.88rem;line-height:1.55}
.doctor-plan{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:8px 0 12px}.doctor-plan>div{background:var(--surface);padding:9px}.doctor-plan small{display:block;color:var(--muted);font-size:.72rem;font-weight:800}.doctor-plan b{display:block;margin-top:3px}
@media(max-width:720px){.doctor-grid{grid-template-columns:repeat(2,1fr)}.doctor-plan{grid-template-columns:repeat(2,1fr)}.doctor-title{font-size:1.25rem}}

.briefbox{border:1px solid var(--line);border-top:4px solid var(--ink);background:var(--surface);padding:12px 13px;margin:10px 0 12px;box-shadow:0 2px 10px rgba(17,19,24,.04)}.briefbox h4{margin:0 0 6px;font-size:1rem}.briefline{font-size:.86rem;line-height:1.5;color:#3f434a}.briefchips{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}.briefchip{border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:.76rem;font-weight:850;background:#f7f6f1}.briefchip.pos{border-color:#f0c2bc;background:#fff5f3;color:#9a241b}.briefchip.neg{border-color:#bee0d3;background:#f1fbf7;color:#0b7d5c}.briefdetail{font-size:.8rem;line-height:1.5;color:#4d5159;margin-top:8px}.newsitem{padding:8px 0;border-top:1px solid var(--line);font-size:.84rem;line-height:1.45}.newsmeta{font-size:.72rem;color:var(--muted);margin-top:2px}.syncwarn{border-left:4px solid var(--amber);padding:8px 10px;background:#fff8ef;margin:7px 0 10px;font-size:.83rem;line-height:1.45}.boardnote{font-size:.8rem;color:var(--muted);margin:4px 0 8px}.tabletitle{font-weight:900;margin:8px 0 4px}
</style>
"""


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def finite(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except Exception:
        return None


def nfmt(v, d=2):
    x = finite(v)
    if x is None:
        return "—"
    return f"{x:,.{d}f}".rstrip("0").rstrip(".")


def pp(v, d=1):
    x = finite(v)
    return "—" if x is None else f"{x:+.{d}f}%"


def decpct(v, d=1):
    x = finite(v)
    return "—" if x is None else f"{x*100:+.{d}f}%"


def lots(v):
    x = finite(v)
    return "—" if x is None else f"{x:+,.0f}張"


def _optional_float(v):
    text = str(v or "").strip().replace(",", "")
    if not text:
        return None
    try:
        x = float(text)
        return x if np.isfinite(x) and x > 0 else None
    except Exception:
        return None


def _research(stock: dict):
    r = stock.get("research") or {}
    return (
        r.get("monthly_revenue") or {},
        r.get("financials") or {},
        r.get("valuation") or {},
        r.get("institutional_flow") or {},
        r.get("main_force_proxy") or {},
    )


def _quick_values(stock: dict):
    rev, fin, val, inst, _ = _research(stock)
    latest = rev.get("latest") or {}
    eps4 = fin.get("eps_4q_sum")
    if eps4 is not None:
        eps_label, eps_value, eps_note = "近4季EPS", nfmt(eps4, 2), "單季加總"
    elif fin.get("latest_ytd_eps") is not None:
        eps_label, eps_value, eps_note = "最新累計EPS", nfmt(fin.get("latest_ytd_eps"), 2), fin.get("latest_period") or "官方季報"
    else:
        eps_label, eps_value, eps_note = "EPS", "—", "資料未取得"
    sector = stock.get("sector_strength") or {}
    theme = stock.get("theme_strength") or {}
    mainline = finite(((stock.get("horizons") or {}).get("mid",{}).get("score_components") or {}).get("mainline"))
    if mainline is None:
        mainline = 0.56*(finite(sector.get("score")) or 50.0)+0.44*(finite(theme.get("score")) or 50.0)
    theme_name = str(theme.get("name") or stock.get("theme") or sector.get("status") or "主線")
    return [
        ("月營收", f"{nfmt(latest.get('revenue_billion'),1)}億", f"YoY {pp(latest.get('yoy_pct'))}"),
        (eps_label, eps_value, eps_note),
        ("產業鏈主線", nfmt(mainline, 0), theme_name),
        ("法人淨超", lots(inst.get("total_net_lots")) if inst.get("available") else "—", str(inst.get("scope_label") or "合計")),
    ]


def _quick_html(stock: dict) -> str:
    cells = []
    for k, v, s in _quick_values(stock):
        cells.append(f"<div class='q'><div class='qk'>{esc(k)}</div><div class='qv'>{esc(v)}</div><div class='ds'>{esc(s)}</div></div>")
    return "<div class='quick'>" + "".join(cells) + "</div>"


def _merge_research(base: dict | None, fresh: dict | None) -> dict:
    """Prefer usable on-demand sections without discarding an existing good snapshot."""
    base = dict(base or {})
    fresh = dict(fresh or {})
    merged = dict(base)
    for section in ["monthly_revenue", "financials", "valuation", "institutional_flow", "main_force_proxy"]:
        old = base.get(section) or {}
        cur = fresh.get(section) or {}
        usable = bool(
            cur.get("available")
            or cur.get("rows")
            or cur.get("quarters")
            or cur.get("history_quarters")
            or cur.get("daily_rows")
            or cur.get("latest")
            or cur.get("latest_ytd_eps") is not None
        )
        if usable or not old:
            merged[section] = cur
    sources = []
    for src in [base.get("source"), fresh.get("source")]:
        if src and str(src) not in sources:
            sources.append(str(src))
    if sources:
        merged["source"] = " + ".join(sources)
    if fresh.get("fetched_at"):
        merged["fetched_at"] = fresh.get("fetched_at")
    if fresh.get("error"):
        merged["detail_error"] = fresh.get("error")
    return merged


def _research_detail_for_ticker(stock: dict, force: bool = False) -> tuple[dict, str | None]:
    """Load detail lazily and keep it in Streamlit session state for 15 minutes."""
    ticker = str(stock.get("ticker") or "").strip()
    embedded = stock.get("research") or {}
    if not ticker:
        return embedded, "股票代碼缺失"
    cache = st.session_state.setdefault("alpha_research_detail_cache", {})
    now_ts = time.time()
    item = cache.get(ticker) if isinstance(cache, dict) else None
    item_ttl = 60 if isinstance(item, dict) and item.get("error") else 900
    if (
        not force
        and isinstance(item, dict)
        and isinstance(item.get("data"), dict)
        and now_ts - float(item.get("ts") or 0.0) < item_ttl
    ):
        return _merge_research(embedded, item.get("data")), item.get("error")
    try:
        fresh = service.research_on_demand(ticker, DATA_DIR, include_branch=False)
        err = str(fresh.get("error")) if isinstance(fresh, dict) and fresh.get("error") else None
        cache[ticker] = {"ts": now_ts, "data": fresh if isinstance(fresh, dict) else {}, "error": err}
        return _merge_research(embedded, fresh), err
    except Exception as exc:
        err = safe_error_text(exc, mask_tokens=(os.getenv("FINMIND_TOKEN", ""),))
        cache[ticker] = {"ts": now_ts, "data": {}, "error": err}
        return embedded, err


def _render_fundamental_details(stock: dict, key: str):
    """Render research detail with explicit coverage and categorical period axes."""
    rev, fin, _, inst, _ = _research(stock)
    rendered = 0

    st.markdown("#### 月營收")
    rows = [dict(r) for r in (rev.get("rows") or []) if isinstance(r, dict)]
    rows = sorted(rows, key=lambda x: str(x.get("month") or ""))[-24:]
    if rows:
        rdf = pd.DataFrame(rows).copy()
        keep = [c for c in ["month", "revenue_billion", "mom_pct", "yoy_pct"] if c in rdf.columns]
        if keep:
            rdf = rdf[keep].rename(columns={
                "month": "月份", "revenue_billion": "營收(億元)", "mom_pct": "MoM(%)", "yoy_pct": "YoY(%)"
            })
            st.dataframe(rdf.tail(12), hide_index=True, use_container_width=True)
            rendered += 1
        chart_df = pd.DataFrame(rows)
        if {"month", "revenue_billion"}.issubset(chart_df.columns):
            chart_df["revenue_billion"] = pd.to_numeric(chart_df["revenue_billion"], errors="coerce")
            chart_df = chart_df.dropna(subset=["revenue_billion"]).drop_duplicates("month", keep="last")
            # Plotly interprets YYYY-MM as dates unless explicitly categorical.  With
            # a single point this used to create microsecond ticks around Aug 1.
            if len(chart_df) >= 2:
                try:
                    fig = go.Figure()
                    fig.add_bar(x=chart_df["month"].astype(str), y=chart_df["revenue_billion"], name="月營收")
                    fig.update_layout(
                        height=250, margin=dict(l=5, r=5, t=8, b=5), showlegend=False,
                        paper_bgcolor="#fffefb", plot_bgcolor="#fffefb", xaxis_title="", yaxis_title="億元",
                    )
                    fig.update_xaxes(type="category", tickmode="auto", nticks=min(6, len(chart_df)), fixedrange=True)
                    fig.update_yaxes(gridcolor="#ecebe5", fixedrange=True)
                    st.plotly_chart(fig, use_container_width=True, key=f"{key}_rev", config={"displayModeBar": False})
                except Exception:
                    st.caption("營收趨勢圖暫時無法繪製，但上方數值表仍可使用。")
            else:
                st.caption("目前只有最新 1 個月資料，因此不繪製容易誤判的單點趨勢圖。")
    else:
        latest = rev.get("latest") or {}
        if latest:
            st.dataframe(pd.DataFrame([{
                "月份": latest.get("month"), "營收(億元)": latest.get("revenue_billion"),
                "MoM(%)": latest.get("mom_pct"), "YoY(%)": latest.get("yoy_pct"),
            }]), hide_index=True, use_container_width=True)
            rendered += 1
            st.caption("目前資料源僅提供最新月份；取得歷史資料後會自動補上趨勢。")
        else:
            st.caption("未取得月營收明細。")
    if rev.get("coverage_label"):
        st.caption(f"營收涵蓋：{rev.get('coverage_label')}")
    if rev.get("source"):
        st.caption("營收來源：" + str(rev.get("source")))

    st.markdown("#### EPS / 毛利率")
    qhist = [dict(q) for q in (fin.get("history_quarters") or fin.get("quarters") or []) if isinstance(q, dict)]
    qhist = sorted(qhist, key=lambda x: str(x.get("quarter") or ""))[-8:]
    if qhist:
        qdf = pd.DataFrame(qhist).copy()
        official_ytd = fin.get("eps_ytd_basis") == "official_cumulative"
        ytd_title = "官方累積EPS" if official_ytd else "同年度累積EPS*"
        wanted = ["quarter", "eps_ytd_sum_unadjusted", "gross_margin_pct"] if official_ytd else ["quarter", "eps", "eps_ytd_sum_unadjusted", "gross_margin_pct"]
        cols = [c for c in wanted if c in qdf.columns]
        if cols:
            show = qdf[cols].rename(columns={
                "quarter": "季別", "eps": "單季EPS", "eps_ytd_sum_unadjusted": ytd_title, "gross_margin_pct": "單季毛利率(%)"
            })
            st.dataframe(show, hide_index=True, use_container_width=True)
            rendered += 1
        chart_col = "eps_ytd_sum_unadjusted" if official_ytd else "eps"
        if {"quarter", chart_col}.issubset(qdf.columns):
            chart_df = qdf[["quarter", chart_col]].copy()
            chart_df[chart_col] = pd.to_numeric(chart_df[chart_col], errors="coerce")
            chart_df = chart_df.dropna(subset=[chart_col]).drop_duplicates("quarter", keep="last")
            if len(chart_df) >= 2:
                try:
                    chart_name = "官方累積 EPS" if official_ytd else "單季 EPS"
                    fig = go.Figure()
                    fig.add_bar(x=chart_df["quarter"].astype(str), y=chart_df[chart_col], name=chart_name)
                    fig.update_layout(
                        height=240, margin=dict(l=5, r=5, t=8, b=5), showlegend=False,
                        paper_bgcolor="#fffefb", plot_bgcolor="#fffefb", xaxis_title="", yaxis_title=chart_name,
                    )
                    fig.update_xaxes(type="category", fixedrange=True)
                    fig.update_yaxes(gridcolor="#ecebe5", fixedrange=True)
                    st.plotly_chart(fig, use_container_width=True, key=f"{key}_eps", config={"displayModeBar": False})
                except Exception:
                    st.caption("EPS 趨勢圖暫時無法繪製，但上方數值表仍可使用。")
            else:
                st.caption("目前只有 1 個可比較 EPS 期間，因此不繪製單點趨勢圖。")
        if official_ytd:
            st.caption("官方 Q2/Q3/Q4 EPS 是年初至當季的累計 EPS。因加權平均股數可能改變，本系統不以相減方式冒充單季 EPS；單季毛利率則可由營收／毛利累計額差分還原。")
        else:
            st.caption("* FinMind EPS 為單季值；跨季直接加總遇配股／分割時可能與公司財報累計 EPS 不一致。")
    elif fin.get("latest_ytd_eps") is not None:
        st.dataframe(pd.DataFrame([{
            "期間": fin.get("latest_period") or "最新季報",
            "官方累積EPS": fin.get("latest_ytd_eps"),
            "累計毛利率(%)": fin.get("gross_margin_latest_pct"),
        }]), hide_index=True, use_container_width=True)
        rendered += 1
        st.caption("目前只有最新累計季報；沒有足夠相鄰季度時，不把累計 EPS 誤畫成單季趨勢。")
    else:
        st.caption("未取得 EPS / 季財報明細。")
    if fin.get("coverage_label"):
        st.caption(f"財報涵蓋：{fin.get('coverage_label')}")
    if fin.get("source"):
        st.caption("財報來源：" + str(fin.get("source")))

    st.markdown("#### 三大法人")
    daily = [dict(r) for r in (inst.get("daily_rows") or []) if isinstance(r, dict)]
    daily = sorted(daily, key=lambda x: str(x.get("date") or ""))[-22:]
    if daily:
        ddf = pd.DataFrame(daily).copy()
        cols = [c for c in ["date", "foreign_net_lots", "trust_net_lots", "dealer_net_lots", "total_net_lots"] if c in ddf.columns]
        if cols:
            ddf = ddf[cols].rename(columns={
                "date": "日期", "foreign_net_lots": "外資(張)", "trust_net_lots": "投信(張)",
                "dealer_net_lots": "自營商(張)", "total_net_lots": "合計(張)",
            })
            st.dataframe(ddf, hide_index=True, use_container_width=True)
            rendered += 1
    elif inst.get("available"):
        scope = str(inst.get("scope_label") or "目前可取得期間")
        st.dataframe(pd.DataFrame([
            ["外資", inst.get("foreign_net_lots")],
            ["投信", inst.get("trust_net_lots")],
            ["自營商", inst.get("dealer_net_lots")],
            ["合計", inst.get("total_net_lots")],
        ], columns=["類別", f"{scope}淨買賣超(張)"]), hide_index=True, use_container_width=True)
        rendered += 1
    else:
        reason = str(inst.get("reason") or "")
        st.caption("未取得三大法人明細。" + (f"（{reason}）" if reason else ""))
    if inst.get("scope_label"):
        st.caption("法人涵蓋：" + str(inst.get("scope_label")))
    if inst.get("source"):
        st.caption("法人來源：" + str(inst.get("source")))
    if inst.get("summary"):
        st.caption(str(inst.get("summary")))

    if rendered == 0:
        st.warning("本次沒有取得可顯示的營收、EPS 或法人明細。請稍後再展開；這不影響短／中／長線既有排名。")

def _render_research(stock: dict, widget_scope: str):
    ticker_for_cache = str(stock.get("ticker") or "").strip()
    safe_scope = "".join(ch if ch.isalnum() else "_" for ch in f"{widget_scope}_{ticker_for_cache or 'x'}")[-140:]
    toggle_key = f"fund_toggle_{safe_scope}"
    detail_err = None
    detail_research = None

    # Streamlit updates widget state before rerunning the script.  If the detail
    # toggle is already ON, load/merge the detail *before* drawing the summary
    # cards.  V16.6.1 fetched only at the bottom of the card, so the top法人 tiles
    # could remain as dashes on the very same run that showed detailed tables.
    if bool(st.session_state.get(toggle_key, False)):
        detail_research, detail_err = _research_detail_for_ticker(stock)
        stock = dict(stock)
        stock["research"] = detail_research
    else:
        detail_cache = st.session_state.get("alpha_research_detail_cache", {})
        cached = detail_cache.get(ticker_for_cache) if isinstance(detail_cache, dict) else None
        if isinstance(cached, dict) and isinstance(cached.get("data"), dict):
            stock = dict(stock)
            stock["research"] = _merge_research(stock.get("research") or {}, cached.get("data"))
    rev, fin, val, inst, main = _research(stock)
    latest = rev.get("latest") or {}
    qs = fin.get("quarters") or []
    gm = fin.get("gross_margin_latest_pct")
    eps_name = "近4季EPS" if fin.get("eps_4q_sum") is not None else "最新累計EPS" if fin.get("latest_ytd_eps") is not None else "EPS"
    eps_value = fin.get("eps_4q_sum") if fin.get("eps_4q_sum") is not None else fin.get("latest_ytd_eps")
    eps_note = "單季加總" if fin.get("eps_4q_sum") is not None else (fin.get("latest_period") or "官方季報") if fin.get("latest_ytd_eps") is not None else "資料未取得"
    gm_name = "最新累計毛利率" if fin.get("latest_ytd_eps") is not None and fin.get("eps_4q_sum") is None else "最新毛利率"
    items = [
        ("最新月營收", f"{nfmt(latest.get('revenue_billion'))} 億", latest.get("month") or "—"),
        ("月增", pp(latest.get("mom_pct")), "MoM"), ("年增", pp(latest.get("yoy_pct")), "YoY"),
        (eps_name, nfmt(eps_value), eps_note), (gm_name, pp(gm, 1) if gm is not None else "—", ""),
        ("本益比", f"{nfmt(val.get('pe'),1)} 倍" if val.get("pe") is not None else "—", val.get("date") or ""),
        ("股價淨值比", nfmt(val.get("pbr"),1), "PBR"), ("殖利率", pp(val.get("dividend_yield_pct"),1), "近值"),
        ("近4季平均毛利", pp(fin.get("gross_margin_4q_avg_pct"),1) if fin.get("gross_margin_4q_avg_pct") is not None else "—", ""),
        ("資料時間", stock.get("price_date") or "—", "股價基準"),
    ]
    html_cells="".join(f"<div class='datum'><div class='dk'>{esc(k)}</div><div class='dv'>{esc(v)}</div><div class='ds'>{esc(note)}</div></div>" for k,v,note in items)
    st.markdown(f"<div class='datagrid'>{html_cells}</div>", unsafe_allow_html=True)
    st.markdown(f"""<div class='flowbar'>
      <div><small>外資</small><b>{esc(lots(inst.get('foreign_net_lots')) if inst.get('available') else '—')}</b></div>
      <div><small>投信</small><b>{esc(lots(inst.get('trust_net_lots')) if inst.get('available') else '—')}</b></div>
      <div><small>自營商</small><b>{esc(lots(inst.get('dealer_net_lots')) if inst.get('available') else '—')}</b></div>
      <div><small>三大法人合計</small><b>{esc(lots(inst.get('total_net_lots')) if inst.get('available') else '—')}</b></div>
    </div>""", unsafe_allow_html=True)
    if inst.get("available") and inst.get("scope_label"):
        st.caption("法人數字範圍：" + str(inst.get("scope_label")))
    if qs:
        try:
            if fin.get("eps_ytd_basis") == "official_cumulative":
                st.dataframe(pd.DataFrame([{
                    "季度": q.get("quarter"), "官方累積EPS": q.get("eps_ytd_sum_unadjusted"),
                    "單季毛利率(%)": q.get("gross_margin_pct")
                } for q in qs[-4:]]), hide_index=True, use_container_width=True)
                st.caption("官方 Q2/Q3/Q4 EPS 為累計值；不以相減方式推估單季 EPS。")
            else:
                st.dataframe(pd.DataFrame([{
                    "季度": q.get("quarter"), "單季EPS": q.get("eps"),
                    "同年度累積EPS*": q.get("eps_ytd_sum_unadjusted"), "毛利率(%)": q.get("gross_margin_pct")
                } for q in qs[-4:]]), hide_index=True, use_container_width=True)
                st.caption("* FinMind EPS 為單季值；遇配股/分割時跨季加總可能與公司重編累計值不同。")
        except Exception:
            st.caption("季財報摘要暫時無法表格化；可展開明細重新取得。")
    source=str((stock.get("research") or {}).get("source") or "")
    if source: st.caption("公司資料來源："+source)
    if rev.get("history_limited") or fin.get("history_limited"):
        st.caption("部分公司資料目前為官方最新期備援；展開明細會再嘗試回補官方歷史資料。")
    if inst.get("summary"): st.caption(str(inst.get("summary")))

    if st.toggle("顯示營收 / EPS / 法人明細", value=False, key=toggle_key):
        if detail_research is None:
            detail_research, detail_err = _research_detail_for_ticker(stock)
        detail_stock = dict(stock)
        detail_stock["research"] = detail_research
        if detail_err:
            st.warning("公司／法人明細重新取得時有部分資料源未回應；已顯示可取得的資料。")
        _render_fundamental_details(detail_stock, f"fund_{safe_scope}")


def _chart_dataframe(chart: dict) -> pd.DataFrame:
    if not chart or "ohlcv" not in chart:
        return pd.DataFrame()
    df = pd.DataFrame(chart["ohlcv"], columns=["Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(chart.get("dates", []), errors="coerce")
    df = df.dropna(subset=["Date"]).reset_index(drop=True)
    if df.empty:
        return df
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    c = df["Close"]
    for n in [5, 20, 60, 120, 240]:
        df[f"MA{n}"] = c.rolling(n).mean()
    m20 = c.rolling(20).mean()
    s20 = c.rolling(20).std()
    df["BBU"] = m20 + 2 * s20
    df["BBL"] = m20 - 2 * s20

    low9 = df["Low"].rolling(9).min()
    high9 = df["High"].rolling(9).max()
    k = (c - low9) / (high9 - low9).replace(0, np.nan) * 100
    df["KD_K"] = k.ewm(alpha=1/3, adjust=False).mean()
    df["KD_D"] = df["KD_K"].ewm(alpha=1/3, adjust=False).mean()

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]
    return df


def render_chart(chart: dict, plan: dict | None, key: str):
    raw = _chart_dataframe(chart)
    if raw.empty:
        st.caption("K線資料未取得。")
        return
    window = st.radio("區間", ["1個月", "3個月", "6個月", "1年"], index=2, horizontal=True, label_visibility="collapsed", key=f"{key}_range")
    n = {"1個月": 24, "3個月": 66, "6個月": 132, "1年": 252}[window]
    base = raw.tail(n).copy()
    opts = list(base["Date"])
    if len(opts) >= 2:
        left, right = st.select_slider(
            "放大區間", options=opts, value=(opts[0], opts[-1]),
            format_func=lambda d: pd.Timestamp(d).strftime("%m/%d"),
            key=f"{key}_zoom_{window}", help="拖曳左右端點可鎖定想看的交易日期；不使用手勢平移，避免手機上整張圖跑掉。"
        )
        df = base[(base["Date"] >= pd.Timestamp(left)) & (base["Date"] <= pd.Timestamp(right))].copy()
    else:
        df = base.copy()
    x = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    if df.empty:
        st.caption("所選區間沒有交易資料。")
        return

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, row_heights=[0.54,0.16,0.15,0.15], vertical_spacing=0.025)
    fig.add_trace(go.Candlestick(
        x=x, open=df.Open, high=df.High, low=df.Low, close=df.Close,
        increasing_line_color="#d92d20", increasing_fillcolor="#d92d20",
        decreasing_line_color="#07875d", decreasing_fillcolor="#07875d",
        name="價格", showlegend=False, whiskerwidth=.72,
    ), row=1,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.BBU,mode="lines",line=dict(color="rgba(217,72,15,.55)",width=1.1,dash="dot"),hovertemplate="布林上緣 %{y:.2f}<extra></extra>"),row=1,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.BBL,mode="lines",line=dict(color="rgba(217,72,15,.55)",width=1.1,dash="dot"),fill='tonexty',fillcolor='rgba(217,72,15,.045)',hovertemplate="布林下緣 %{y:.2f}<extra></extra>"),row=1,col=1)
    ma_specs=[("MA5","#111318",1.35),("MA20","#0b57d0",1.8),("MA60","#f08c00",1.65),("MA120","#7b61ff",1.35),("MA240","#2f9e44",1.35)]
    for col,color,width in ma_specs:
        fig.add_trace(go.Scatter(x=x,y=df[col],mode="lines",line=dict(color=color,width=width),hovertemplate=f"{col.replace('MA','')}日 %{{y:.2f}}<extra></extra>"),row=1,col=1)
    colors=np.where(df.Close>=df.Open,"rgba(217,45,32,.62)","rgba(7,135,93,.62)")
    fig.add_trace(go.Bar(x=x,y=df.Volume,marker_color=colors,showlegend=False,hovertemplate="量 %{y:,.0f}<extra></extra>"),row=2,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.KD_K,mode='lines',line=dict(color='#0b57d0',width=1.6),hovertemplate='K %{y:.1f}<extra></extra>'),row=3,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.KD_D,mode='lines',line=dict(color='#f08c00',width=1.6),hovertemplate='D %{y:.1f}<extra></extra>'),row=3,col=1)
    fig.add_hline(y=80,line_color='rgba(120,120,120,.40)',line_width=1,line_dash='dot',row=3,col=1); fig.add_hline(y=20,line_color='rgba(120,120,120,.40)',line_width=1,line_dash='dot',row=3,col=1)
    macd_colors=np.where(df.MACD_HIST>=0,'rgba(217,45,32,.55)','rgba(7,135,93,.55)')
    fig.add_trace(go.Bar(x=x,y=df.MACD_HIST,marker_color=macd_colors,showlegend=False,hovertemplate='MACD柱 %{y:.3f}<extra></extra>'),row=4,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.MACD,mode='lines',line=dict(color='#111318',width=1.4),hovertemplate='MACD %{y:.3f}<extra></extra>'),row=4,col=1)
    fig.add_trace(go.Scatter(x=x,y=df.MACD_SIGNAL,mode='lines',line=dict(color='#7b61ff',width=1.4),hovertemplate='訊號 %{y:.3f}<extra></extra>'),row=4,col=1)
    if plan:
        stop=finite(plan.get("invalidation")); trigger=finite(plan.get("trigger"))
        if trigger is not None: fig.add_hline(y=trigger,line_color="#8a5a00",line_width=1.1,line_dash="dot",row=1,col=1)
        if stop is not None: fig.add_hline(y=stop,line_color="#9b1c1c",line_width=1.1,line_dash="dash",row=1,col=1)
    vals=pd.concat([df["High"],df["Low"],df["MA20"],df["MA60"],df["MA120"],df["MA240"],df["BBU"],df["BBL"]]).dropna()
    if not vals.empty:
        lo,hi=float(vals.min()),float(vals.max()); pad=max((hi-lo)*.14,max(hi,1)*.010)
        fig.update_yaxes(range=[max(0,lo-pad),hi+pad],row=1,col=1)
    # Category x-axis removes weekend/holiday gaps, keeping candles almost touching.
    if x:
        ids=sorted(set(np.linspace(0,len(x)-1,min(4,len(x)),dtype=int).tolist()))
        tickvals=[x[i] for i in ids]; ticktext=[pd.to_datetime(x[i]).strftime("%m/%d") for i in ids]
        for r in [1,2,3,4]:
            fig.update_xaxes(type="category",tickmode="array",tickvals=tickvals,ticktext=ticktext,fixedrange=True,row=r,col=1)
    fig.update_layout(height=575,margin=dict(l=3,r=5,t=6,b=2),paper_bgcolor="#fffefb",plot_bgcolor="#fffefb",xaxis_rangeslider_visible=False,dragmode=False,hovermode="x unified",showlegend=False,font=dict(size=11,color="#4d5159"),bargap=.04)
    fig.update_yaxes(gridcolor="#ecebe5",zeroline=False,fixedrange=True,tickfont=dict(size=10))
    st.markdown("<div class='chartchips'><span>K線（日）</span><span><i class='chipline ma5'></i>週線5</span><span><i class='chipline ma20'></i>月線20</span><span><i class='chipline ma60'></i>季線60</span><span><i class='chipline ma120'></i>半年120</span><span><i class='chipline ma240'></i>年線240</span><span><i class='chipline bb'></i>布林</span></div><div class='ind-caption'>下方依序：量能、KD、MACD；交易日採等距顯示，週末不留大空隙。</div>",unsafe_allow_html=True)
    st.plotly_chart(fig,use_container_width=True,key=key,config={"displayModeBar":False,"scrollZoom":False,"displaylogo":False,"staticPlot":False})


def _history_line(stock: dict, h: str) -> str:
    f = stock.get("horizons", {}).get(h, {}).get("forecast", {}) or {}
    s = f.get("strategy") or {}
    if not f.get("estimate_available"):
        return "歷史案例不足"
    med = decpct(s.get("median"), 1)
    rate = finite(s.get("smoothed_positive_rate"))
    n = int(finite(f.get("local_effective_n")) or 0)
    return f"相似案例 {n} 次 · 中位數 {med} · 偏正向 {rate*100:.0f}%" if rate is not None else f"相似案例 {n} 次 · 中位數 {med}"


def _row(stock: dict, h: str, snap: dict, rank: int, live: bool = False):
    name = stock.get("name") or stock.get("ticker")
    ticker = stock.get("ticker") or ""
    fine = stock.get("fine_industry") or fine_industry(ticker, name, stock.get("industry", ""))
    role_label = ((stock.get("role") or {}).get("label") or "").strip()
    stage_label = ((stock.get("stage") or {}).get("label") or "").strip()
    tags = [f"<span class='tag'>{esc(fine)}</span>"] if fine else []
    if role_label:
        tags.append(f"<span class='tag blue'>{esc(role_label)}</span>")
    if stage_label:
        tags.append(f"<span class='tag red'>{esc(stage_label)}</span>")
    tag_html = "<div class='tagrow'>" + "".join(tags) + "</div>" if tags else ""

    block = stock.get("horizons", {}).get(h, {}) or {}
    if live:
        live_info = stock.get("intraday") or {}
        price = finite(live_info.get("price"))
        change = finite(live_info.get("change_rate_pct"))
        reasons = live_info.get("reasons") or []
        title = live_info.get("state") or "即時資料不足"
        risk = ""
        timing = live_info.get("entry_timing") or {}
        position = live_info.get("position_guidance") or block.get("position_guidance") or {}
        selection_score = finite(stock.get("live_ranking_score"))
        history = _history_line(stock, h)
    else:
        view = investment_view(stock, h, snap.get("market") or {})
        price = stock.get("price")
        change = None
        reasons = view.get("reasons") or []
        title = view.get("title") or "觀察"
        risk = view.get("risk") or ""
        timing = block.get("entry_timing") or {}
        position = block.get("position_guidance") or {}
        selection_score = finite(block.get("ranking_score"))
        history = _history_line(stock, h)

    cls = "flat"
    if change is not None:
        cls = "up" if change > 0 else "down" if change < 0 else "flat"
    change_text = pp(change, 2) if change is not None else esc(H_LABEL[h])
    reason_text = " · ".join(str(x) for x in reasons[:2])
    risk_text = f" · <span class='risk'>{esc(risk)}</span>" if risk else ""

    timing_html = ""
    entry_score = finite(timing.get("score"))
    if entry_score is not None:
        chase = str(timing.get("chase_risk") or "待確認")
        action = str(timing.get("action") or "等確認")
        action_cls = "entryok" if entry_score >= 70 and "不追" not in action and "暫不" not in action else "entryaction"
        idea_text = nfmt(selection_score, 1) if selection_score is not None else "—"
        overnight = "<span class='overnight'>隔夜風險↑</span>" if timing.get("overnight_risk") else ""
        timing_reasons = [str(x) for x in (timing.get("reasons") or [])[:2]]
        why_html = f"<div class='entrywhy'>{esc(' · '.join(timing_reasons))}</div>" if timing_reasons else ""
        pos_pct = position.get("percent")
        pos_chip = f"<span class='entrychip'>部位上限 <b>{int(pos_pct)}%</b></span>" if pos_pct is not None else ""
        timing_html = (
            "<div class='entryline'>"
            f"<span class='entrychip'>標的分數 <b>{esc(idea_text)}</b></span>"
            f"<span class='entrychip'>進場分數 <b>{entry_score:.0f}</b></span>"
            f"<span class='entrychip'>追價風險 <b>{esc(chase)}</b></span>"
            f"{pos_chip}<span class='{action_cls}'>{esc(action)}</span>{overnight}</div>{why_html}"
        )

    comp = block.get("score_components") or {}
    score_parts = []
    for label, key in (("技術", "technical"), ("歷史", "empirical"), ("基本", "fundamental"), ("法人", "flow")):
        v = finite(comp.get(key))
        score_parts.append(f"<span class='scorechip'>{label} <b>{'—' if v is None else f'{v:.0f}'}</b></span>")
    cov = finite(comp.get("evidence_coverage"))
    if cov is not None:
        score_parts.append(f"<span class='scorechip'>證據完整度 <b>{cov*100:.0f}%</b></span>")
    component_html = "<div class='scoreline'>" + "".join(score_parts) + "</div>" if score_parts else ""

    # Dedicated decision layer: buy-now ranking during the session, or next-session
    # planning outside the session.  This is intentionally separate from the
    # underlying stock-selection score.
    decision = (stock.get("buy_opportunity") or stock.get("next_session") or {}) if live else (stock.get("next_session") or {})
    decision_html = ""
    if decision:
        zone = decision.get("buy_zone") or {}
        low = finite(zone.get("low")); high = finite(zone.get("high"))
        target = finite(decision.get("target_price"))
        exp_ret = finite(decision.get("expected_return"))
        rr = finite(decision.get("reward_risk"))
        confidence = finite(decision.get("forecast_confidence"))
        sample_n = int(finite(decision.get("sample_n")) or 0)
        dscore = finite(decision.get("score"))
        zone_text = f"{nfmt(low)}–{nfmt(high)}" if low is not None and high is not None else "—"
        target_text = nfmt(target) if target is not None else "—"
        exp_text = f"{exp_ret*100:+.1f}%" if exp_ret is not None else "—"
        rr_text = f"{rr:.2f}" if rr is not None else "—"
        conf_text = f"{confidence:.0f}/100 · n={sample_n}" if confidence is not None else f"n={sample_n}" if sample_n else "—"
        score_text = f"{dscore:.0f}" if dscore is not None else "—"
        action_text = str(decision.get("action") or decision.get("stance") or "")
        cls_dec = "buy" if bool(decision.get("eligible_now")) else "wait"
        decision_is_buy = bool(stock.get("buy_opportunity"))
        decision_label = "買入優先" if decision_is_buy else "明日關注"
        path = str(decision.get("entry_path") or "")
        path_label = {"PULLBACK":"拉回承接", "CONTINUATION":"強勢續攻", "PANIC_REVERSAL":"恐慌錯殺反轉", "WAIT_PULLBACK":"等拉回", "WAIT_BREAKOUT":"等突破"}.get(path, "")
        blockers = [str(x.get("label") or "") for x in (decision.get("failed_gates") or []) if isinstance(x, dict) and x.get("label")]
        blocker_html = f"<div class='decision-reasons'>未通過：{esc(' · '.join(blockers[:3]))}</div>" if blockers and not decision.get("eligible_now") else ""
        decision_html = (
            "<div class='decision'>"
            f"<div><small>{decision_label}分數</small><b>{esc(score_text)}</b></div>"
            f"<div><small>進場路徑</small><b>{esc(path_label or '—')}</b></div>"
            f"<div><small>建議買入區</small><b>{esc(zone_text)}</b></div>"
            f"<div><small>模型中位目標</small><b>{esc(target_text)}</b></div>"
            f"<div><small>保守剩餘報酬</small><b>{esc(exp_text)}</b></div>"
            f"<div><small>報酬/風險</small><b>{esc(rr_text)}</b></div>"
            f"<div><small>案例信心</small><b>{esc(conf_text)}</b></div>"
            f"<div class='decision-action {cls_dec}'>{esc(action_text)} · 目標與報酬為歷史模型估計，非保證值</div>"
            f"{blocker_html}"
            "</div>"
        )

    st.markdown(f"""
    <div class="rankrow">
      <div class="rankno">{rank:02d}</div>
      <div><div><span class="stockname">{esc(name)}</span><span class="stockcode">{esc(ticker)}</span></div>{tag_html}</div>
      <div class="quote"><div class="price">{nfmt(price)}</div><div class="change {cls}">{esc(change_text)}</div></div>
    </div>
    <div class="signal"><div class="signal-title">{esc(title)}</div><div class="signal-copy">{esc(reason_text)}{risk_text}<div class="mini-note">{esc(history)}</div></div></div>
    {timing_html}
    {component_html}
    {decision_html}
    {_quick_html(stock)}
    """, unsafe_allow_html=True)

    label = f"{name}｜數據與走勢"
    with st.expander(label, expanded=False):
        _render_research(stock, f"{'live' if live else h}_{rank}_{snap.get('snapshot_id','x')}")
        block = stock.get("horizons", {}).get(h, {}) or {}
        plan = block.get("plan") or {}
        if plan:
            pos = position or block.get("position_guidance") or {}
            pos_label = pos.get("label") or "依風險調整"
            st.markdown(f"""<div class='plan'>
              <div><small>較理想區間</small><b>{nfmt(plan.get('zone_low'))}–{nfmt(plan.get('zone_high'))}</b></div>
              <div><small>轉強確認</small><b>{nfmt(plan.get('trigger'))}</b></div>
              <div><small>不追高超過</small><b>{nfmt(plan.get('chase_limit'))}</b></div>
              <div><small>跌破重看</small><b>{nfmt(plan.get('invalidation'))}</b></div>
              <div><small>目前部位節奏</small><b>{esc(pos_label)}</b></div>
            </div>""", unsafe_allow_html=True)
        if st.toggle("顯示 K 線與技術指標", value=False, key=f"chart_toggle_{'live' if live else h}_{ticker}_{snap.get('snapshot_id','x')}"):
            chart = None
            try:
                chart = service.chart_on_demand(snap, ticker, DATA_DIR, allow_fetch=False)
            except Exception:
                pass
            render_chart(chart, plan, f"chart_{'live' if live else h}_{ticker}_{snap.get('snapshot_id','x')}")


def _render_daily_list(snap: dict | None, h: str, n: int = 5):
    if not snap:
        st.info("請先更新市場資料。")
        return
    picks = service.select_market_best(snap, h, n=n)
    if not picks:
        st.info("目前沒有可排序標的。")
        return
    for i, stock in enumerate(picks, 1):
        _row(stock, h, snap, i, live=False)



def _render_plain_global_context(gctx: dict | None):
    summary = human_global_summary(gctx or {})
    factors = summary.get("factors") or []
    details = summary.get("details") or []
    chip_html = []
    for x in factors:
        if x.get("value_pct") is None:
            continue
        val = float(x.get("value_pct"))
        cls = "pos" if val >= 0 else "neg"
        chip_html.append(f"<span class='briefchip {cls}'>{esc(x.get('name'))} <b>{val:+.1f}%</b></span>")
    chips = "".join(chip_html)
    st.markdown(
        "<div class='briefbox'><h4>國際市場快讀｜摘要</h4>"
        f"<div class='briefline'>{esc(summary.get('headline') or '')}</div>"
        f"<div class='briefchips'>{chips}</div>"
        "<div class='newsmeta'>這一層只調整盤中風險與錯殺反轉條件，不直接改短／中／長線股票品質排名。</div></div>",
        unsafe_allow_html=True,
    )
    with st.expander("展開國際市場快讀（更多數據與判讀）", expanded=False):
        if details:
            bullets = "".join(f"<div class='briefdetail'>• {esc(line)}</div>" for line in details)
            st.markdown(f"<div class='briefbox'><h4>重點數據判讀</h4>{bullets}</div>", unsafe_allow_html=True)
        else:
            st.caption("目前沒有更多國際市場細節可顯示。")


def _render_waiting_briefing(brief: dict | None):
    brief = brief or {}
    st.markdown("<div class='section-kicker'>WHILE UPDATING</div><div class='section-title'>更新等待閱讀區</div>", unsafe_allow_html=True)
    _render_plain_global_context(brief.get("global") or {})
    prev = brief.get("previous") or {}
    prev_date = str(prev.get("date") or "")
    if prev_date:
        short = "、".join(prev.get("short") or []) or "—"
        mid = "、".join(prev.get("mid") or []) or "—"
        long = "、".join(prev.get("long") or []) or "—"
        st.markdown(
            "<div class='briefbox'><h4>上一版模型先讀</h4>"
            f"<div class='briefline'>基準日 {esc(prev_date)}（僅供等待新版完成前參考）</div>"
            f"<div class='briefline'>短線：{esc(short)}<br>中線：{esc(mid)}<br>長線：{esc(long)}</div></div>",
            unsafe_allow_html=True,
        )
    news = brief.get("news") or {}
    items = news.get("items") or []
    if items:
        html_rows = []
        for row in items[:7]:
            bias = str(row.get("bias") or "待判讀")
            meta = " · ".join(x for x in [str(row.get("topic") or ""), bias, str(row.get("source") or ""), str(row.get("published") or "")] if x)
            title = esc(row.get("title") or "")
            link = str(row.get("link") or "")
            if link.startswith("http"):
                title_html = f"<a href='{esc(link)}' target='_blank' rel='noopener'>{title}</a>"
            else:
                title_html = title
            html_rows.append(f"<div class='newsitem'><b>{title_html}</b><div class='newsmeta'>{esc(meta)}</div></div>")
        st.markdown(
            "<div class='briefbox'><h4>可能影響台股的重要消息</h4>"
            "<div class='newsmeta'>中文標題優先，預設僅保留近 5 日內新聞；『可能偏多／偏空』只做保守關鍵字提示，不直接餵入選股分數。</div>"
            + "".join(html_rows) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("新聞快讀暫不可用；模型更新不受影響。")


def _market_header(snap: dict | None):
    now = _taipei_timestamp()
    current = session_reference_policy(now)
    if not snap:
        st.markdown(
            f"<div class='marketbar'><span><b>{esc(current.get('label'))}</b></span><span>尚未建立市場快照</span></div>",
            unsafe_allow_html=True,
        )
        st.caption(str(current.get("notice") or ""))
        return
    m = snap.get("market") or {}
    cov = snap.get("coverage") or {}
    off = cov.get("official_eod") or {}
    hist = cov.get("history_refresh") or {}
    sess = snap.get("session") or {}
    generated = str(snap.get("generated_at") or st.session_state.get("alpha_last_refresh") or "")
    if "T" in generated:
        generated = generated.replace("T", " ")[:19]
    sync_date = str(sess.get("common_complete_date") or off.get("model_sync_date") or snap.get("price_date") or "—")
    raw_tw = str(off.get("raw_twse_date") or off.get("twse_date") or "—")
    raw_otc = str(off.get("raw_tpex_date") or off.get("tpex_date") or "—")
    audit = assess_snapshot(snap)
    aligned = audit["safe_to_claim_synced"]
    parts = [
        f"<span><b>{esc(current.get('label'))}</b></span>",
        f"<span><b>同步完整基準 {esc(sync_date)}</b></span>",
        f"<span>{esc(REGIME.get(m.get('regime'),'大盤待確認'))}</span>",
        f"<span>{'上市／上櫃來源日期與模型日一致' if aligned else '資料日期或完整度待核對（見資料健檢）'}</span>",
    ]
    if generated:
        parts.append(f"<span>模型更新 {esc(generated)}</span>")
    model_n = int(snap.get("full_universe_model_n") or snap.get("candidate_n") or 0)
    mother_n = int(cov.get("requested") or 0)
    valid_n = int(cov.get("feature_valid") or 0)
    breadth_n = int(snap.get("research_breadth_n") or 0)
    elig = snap.get("selection_eligible_n") or {}
    if mother_n:
        parts.append(f"<span>普通股母體 <b>{mother_n:,}</b> 檔</span>")
    if model_n:
        parts.append(f"<span>可投資模型 <b>{model_n:,}</b> 檔（歷史足夠 {valid_n:,}）</span>")
    if elig:
        parts.append(f"<span>最終可比：短 {int(elig.get('short') or 0):,} / 中 {int(elig.get('mid') or 0):,} / 長 {int(elig.get('long') or 0):,}</span>")
    if breadth_n:
        parts.append(f"<span>公司/法人可比證據 {breadth_n:,} 檔</span>")
    if hist.get("mode"):
        mode_label = "增量快取" if hist.get("mode") == "incremental" else "完整歷史"
        parts.append(f"<span>歷史 {esc(mode_label)}</span>")
    if current.get("phase") == INTRADAY:
        parts.append("<span class='liveflag'><i class='dot'></i>全市場盤中雷達每 60 秒重評</span>")
    if sess.get("postclose_pending"):
        parts.append("<span>今日官方收盤待完整</span>")
    stale = int(cov.get("stale_excluded") or 0)
    if stale:
        parts.append(f"<span>{stale:,} 檔舊資料已排除</span>")
    errors = cov.get("errors") or []
    if errors:
        parts.append(f"<span>資料警示 {len(errors)}</span>")
    gctx = _cached_global_context()
    if gctx.get("available") and not gctx.get("stale"):
        shock = finite(gctx.get("shock_score"))
        if shock is not None:
            mode_label = {"PANIC":"恐慌", "STRESS":"壓力", "NORMAL":"正常"}.get(str(gctx.get("mode")), str(gctx.get("mode") or ""))
            parts.append(f"<span>國際隔夜壓力 <b>{shock:.0f}/100</b> · {esc(mode_label)}</span>")
    st.markdown("<div class='marketbar'>" + "".join(parts) + "</div>", unsafe_allow_html=True)

    if mother_n:
        with st.expander("模型涵蓋範圍｜為何不是所有掛牌股票都進最終排名", expanded=False):
            st.caption(
                f"普通股母體 {mother_n:,} 檔 → 歷史資料足夠 {valid_n:,} 檔 → 同步日期／價格／最低流動性後進入可投資模型 {model_n:,} 檔。"
            )
            excluded = []
            for label, key in (("歷史不足", "history_insufficient"), ("資料日期落後", "stale_excluded"), ("股價低於最低門檻", "below_price_excluded"), ("20日平均成交金額低於300萬元", "below_turnover_excluded")):
                v = int(cov.get(key) or 0)
                if v:
                    excluded.append(f"{label} {v:,} 檔")
            if excluded:
                st.caption("排除原因：" + "｜".join(excluded))
            if elig:
                st.caption(f"最終推薦再依週期做可執行性／證據門檻：短線 {int(elig.get('short') or 0):,} 檔、中線 {int(elig.get('mid') or 0):,} 檔、長線 {int(elig.get('long') or 0):,} 檔。短線要求較高流動性；長線要求較完整公司證據。")

    if current.get("phase") == INTRADAY:
        st.caption("盤中：完整日線模型固定在最近正式收盤，不使用未收盤日K；即時層只重新評估相對強弱、買點、建議買入區與剩餘報酬空間。")
    elif current.get("phase") == POSTCLOSE and sess.get("postclose_pending"):
        st.caption("盤後：交易所今日完整 EOD 尚未齊備時，完整短中長線仍使用最近正式收盤；若可取得今日收盤快照，『明日關注』會另顯示暫行清單，待官方資料齊備後再完整重算。")
    else:
        st.caption("盤前／休市：以最近完整交易日產生下一交易日關注清單；短、中、長線排名不混入舊的盤中報價。")
    if gctx.get("available"):
        summary = human_global_summary(gctx)
        factors = summary.get("factors") or []
        factor_text = "｜".join(f"{x.get('name')} {float(x.get('value_pct')):+.1f}%" for x in factors if x.get("value_pct") is not None)
        prefix = "國際市場快讀（資料可能延遲）" if gctx.get("stale") else "國際市場快讀"
        st.caption(f"{prefix}：{summary.get('headline')}")
        if factor_text:
            st.caption(f"主要數據：{factor_text}。")
    if not aligned:
        st.markdown(
            f"<div class='syncwarn'><b>交易所來源日期未完全一致。</b> 原始來源：上市 {esc(raw_tw)}、上櫃 {esc(raw_otc)}；為避免跨市場用不同交易日互相比較，V17.1 已把整個模型統一到 {esc(sync_date)}。稍後重新更新會再嘗試補齊較新的官方資料。</div>",
            unsafe_allow_html=True,
        )
    if errors:
        with st.expander("資料來源狀態", expanded=False):
            for err in errors[:8]:
                st.caption(str(err))


def _realtime_batch(snap: dict):
    """Fetch the liquid full-market quote universe, with a stable-core fallback."""
    tickers = full_market_tickers(snap, max_total=int(LIVE_SCAN.get("full_market_quote_max", 1800)))
    if not tickers:
        return [], pd.DataFrame(), None
    df, status = _cached_realtime_snapshot(str(snap.get("snapshot_id") or ""), tuple(tickers))
    if status is not None and status.available and not df.empty:
        return tickers, df, status
    # Provider limits/rate errors on a very large batch should not disable the
    # entire execution layer. Fall back to the completed-day core for this tick.
    core = candidate_tickers(
        snap,
        per_horizon=int(LIVE_SCAN.get("per_horizon", 80)),
        max_total=int(LIVE_SCAN.get("daily_core_max", 220)),
    )
    if core and core != tickers:
        df2, status2 = _cached_realtime_snapshot(str(snap.get("snapshot_id") or "") + "_core", tuple(core))
        if status2 is not None and status2.available and not df2.empty:
            return core, df2, status2
    return tickers, df, status


def _intraday_buy_render_once(snap: dict, horizon: str = "short", top_n: int = 6):
    now = _taipei_timestamp()
    if horizon not in {"short", "mid", "long"}:
        horizon = "short"
    if not market_is_open(now):
        st.markdown(
            f"<div class='offflag'>{esc(session_reference_policy(now).get('label'))} · {esc(now.strftime('%Y-%m-%d %H:%M:%S'))} · 盤中買點僅於 09:00–13:30 啟用</div>",
            unsafe_allow_html=True,
        )
        st.info("目前不是交易時段；改看『明日關注』，不要用昨日收盤報價冒充即時買點。")
        return

    tickers, df, status = _realtime_batch(snap)
    if status is None or not status.available or df.empty:
        reason = getattr(status, "reason", "NO_REALTIME") if status is not None else "NO_REALTIME"
        st.warning(f"盤中即時資料暫不可用：{reason}。完整日線排名仍可在短／中／長線頁查看。")
        return

    global_ctx = _cached_global_context()
    dynamic = dynamic_candidate_pool(snap, df, now=now, global_context=global_ctx)
    detail_tickers = dynamic.get("detail_tickers") or []
    # Price correctness is stricter than discovery. The broad one-minute pass may
    # use the fastest provider, but every stock that can produce a BUY/SELL/HOLD
    # decision is re-quoted from official TWSE/TPEx MIS before execution scoring.
    verified_df, execution_status = _cached_verified_execution_snapshot(
        str(snap.get("snapshot_id") or "") + "_exec", tuple(detail_tickers)
    ) if detail_tickers else (pd.DataFrame(), None)
    if execution_status is None or not execution_status.available or not getattr(execution_status, "verified", False) or verified_df.empty:
        reason = getattr(execution_status, "reason", "NO_VERIFIED_REALTIME") if execution_status is not None else "NO_VERIFIED_REALTIME"
        st.warning(f"已完成全市場異動掃描，但官方即時價驗證失敗（{reason}）；為避免用昨收或舊報價冒充盤中價，本輪不產生買入訊號。")
        return
    detail_df = verified_df
    # Only the bounded, official-price-verified detail pool receives the full
    # entry/forecast execution evaluation.
    live_pool = rerank_snapshot(snap, horizon, detail_df, top_n=max(len(detail_tickers), top_n), now=now)
    ranked_all = rank_intraday_buys(live_pool, horizon=horizon, n=max(1, len(live_pool)), global_context=global_ctx) if live_pool else []
    picks = ranked_all[:top_n]
    summary = summarize_buy_gate_failures(ranked_all, top_n=int(LIVE_SCAN.get("gate_summary_top", 6)))
    twii = verified_df[verified_df["stock_id"].astype(str) == "001"] if "stock_id" in verified_df.columns else pd.DataFrame()
    idx_change = finite(twii.iloc[-1].get("change_rate")) if not twii.empty else None
    fetched = (execution_status.fetched_at or now.isoformat(timespec="seconds")).replace("T", " ")[:19]
    stats = dynamic.get("stats") or {}
    eligible_total = int(summary.get("eligible") or 0)
    shock = finite(global_ctx.get("shock_score")) if global_ctx.get("available") and not global_ctx.get("stale") else None
    shock_html = f"<span>隔夜壓力 <b>{shock:.0f}/100</b></span>" if shock is not None else ""
    st.markdown(
        f"<div class='marketbar'><span class='liveflag'><i class='dot'></i>1 分鐘全市場雷達</span>"
        f"<span>{esc(fetched)}</span><span>執行價 {esc(execution_status.source)}（官方驗證）</span>"
        f"<span>即時報價 {int(stats.get('quoted_n') or len(tickers))} 檔</span>"
        f"<span>動態精算 {int(stats.get('detail_n') or len(detail_tickers))} 檔</span>"
        f"<span>錯殺韌性候選 {int(stats.get('panic_discovery_n') or 0)} 檔</span>"
        f"<span>可買 {eligible_total} 檔</span><span>加權 {esc(pp(idx_change,2))}</span>{shock_html}"
        f"<span>{esc(H_LABEL[horizon])}</span></div>",
        unsafe_allow_html=True,
    )
    if bool(global_ctx.get("panic_mode")) and not bool(global_ctx.get("stale")):
        st.warning("隔夜外部壓力偏高：已啟用『恐慌錯殺反轉』掃描。大跌本身不是買點，只有仍守住模型防守、相對大盤有韌性、從日低回拉且報酬/風險通過的股票，才允許小量試單。")
    if int(stats.get("discovery_only_n") or 0) > 0:
        st.caption(f"另發現 {int(stats.get('discovery_only_n'))} 檔盤中新異動尚未進入完整日線模型；只列為發現，不會在缺乏歷史證據時直接升格為買進推薦。")
    if not picks:
        st.info("即時資料已取得，但目前沒有足夠資料形成可比較買點。")
        return
    if eligible_total == 0:
        st.markdown(
            "<div class='buyempty'><b>目前沒有符合『可買』門檻的標的。</b><br>系統仍列出最接近條件的候選；現在會同時顯示每檔真正卡住的門檻，不再把所有情況都寫成『等拉回』。</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"動態精算池共有 {eligible_total} 檔通過可執行門檻；目前支援拉回承接、強勢續攻，以及廣泛殺盤時才啟用的恐慌錯殺反轉。")
    primary = summary.get("primary") or []
    if primary:
        chips = "".join(f"<span class='gatechip'>{esc(x.get('label'))} {int(x.get('count') or 0)} 檔</span>" for x in primary)
        st.markdown(f"<div class='gatebar'>{chips}</div>", unsafe_allow_html=True)
    for i, stock in enumerate(picks, 1):
        _row(stock, horizon, snap, i, live=True)


if hasattr(st, "fragment"):
    @st.fragment(run_every=int(LIVE_SCAN.get("refresh_seconds", 60)))
    def intraday_buy_fragment(snap: dict, horizon: str = "short"):
        _intraday_buy_render_once(snap, horizon)
else:
    def intraday_buy_fragment(snap: dict, horizon: str = "short"):
        _intraday_buy_render_once(snap, horizon)


def _postclose_preview(snap: dict, horizon: str, n: int = 5):
    """Use today's final quote snapshot only as a labelled provisional preview."""
    now = _taipei_timestamp()
    policy = session_reference_policy(now)
    sess = snap.get("session") or {}
    if policy.get("phase") != POSTCLOSE or sess.get("official_today_complete"):
        return None, None
    tickers, df, status = _realtime_batch(snap)
    if status is None or not status.available or df.empty:
        return None, status
    quote_date = str(getattr(status, "quote_date", "") or "")
    if quote_date != str(policy.get("today") or ""):
        return None, status
    live_pool = rerank_snapshot(snap, horizon, df, top_n=max(len(tickers), n), now=now)
    return rank_next_session_live(live_pool, horizon=horizon, n=n), status


def _render_next_session(snap: dict | None, horizon: str = "short", n: int = 5):
    if not snap:
        st.info("請先更新市場資料。")
        return
    if horizon not in {"short", "mid", "long"}:
        horizon = "short"
    preview, status = _postclose_preview(snap, horizon, n=n)
    if preview:
        fetched = (getattr(status, "fetched_at", "") or "").replace("T", " ")[:19]
        source = str(getattr(status, "source", "") or "暫行行情")
        st.warning(f"今日官方完整收盤資料尚未齊備；以下為 {fetched or '收盤後'} 的『暫行』明日清單（行情來源：{source}）。這不是盤中執行價；官方 EOD 齊備後再按更新，會完整重跑短中長線模型。")
        picks = preview
    else:
        picks = rank_next_session(snap, horizon=horizon, n=n)
        sess = snap.get("session") or {}
        if sess.get("analysis_mode") == "POSTCLOSE_FINAL":
            st.caption("已使用今日正式收盤資料，供下一交易日盤前規劃。")
        else:
            st.caption(f"以最近完整交易日 {snap.get('price_date') or '—'} 規劃下一交易日；建議買入區是條件區間，不代表開盤直接追價。")
    if not picks:
        st.info("目前沒有可產生下一交易日清單的標的。")
        return
    for i, stock in enumerate(picks, 1):
        # Post-close preview retains intraday fields to show today's final quote;
        # the attached `next_session` object remains the decision layer.
        _row(stock, horizon, snap, i, live=bool(preview))


def _overview(snap: dict | None):
    """Completed-day strategic overview. Realtime execution is rendered separately."""
    if not snap:
        st.info("請先更新市場資料。")
        return

    themes = snap.get("theme_leadership") or {}
    sectors = snap.get("sector_leadership") or {}
    pills = []
    source_map = themes if themes else sectors
    for industry, info in list(source_map.items())[:7]:
        score = finite((info or {}).get("score")) or 50.0
        cls = "hot" if score >= 68 else "weak" if score < 40 else ""
        pills.append(f"<span class='sectorpill {cls}'>{esc(industry)} <b>{score:.0f}</b></span>")
    if pills:
        st.markdown("<div class='section-kicker'>MARKET MAINLINE</div><div class='sectorbar'>" + "".join(pills) + "</div>", unsafe_allow_html=True)

    mapping = [("short", "短線 · 約2週"), ("mid", "中線 · 約2個月"), ("long", "長線 · 約6個月")]
    raw = {h: service.select_market_best(snap, h, n=5) for h, _ in mapping}
    cols_html = []
    dup_counts = {}
    for h, title in mapping:
        picks = raw.get(h, [])[:5]
        body = []
        for i, stock in enumerate(picks, 1):
            code = str(stock.get("ticker") or "")
            dup_counts[code] = dup_counts.get(code, 0) + 1
            name = str(stock.get("name") or code)
            fine = str(stock.get("fine_industry") or stock.get("industry") or "")
            block = (stock.get("horizons", {}) or {}).get(h, {}) or {}
            score = finite(block.get("ranking_score"))
            timing = block.get("entry_timing") or {}
            entry_score = finite(timing.get("score"))
            action = str(timing.get("action") or "")
            meta = f"{fine} · 標的 {nfmt(score,1)}"
            if entry_score is not None:
                meta += f" · 買點 {entry_score:.0f}"
            if "不追" in action or "暫不" in action:
                meta += " · 不追"
            body.append(f"<div class='ovitem'><div class='ovrank'>#{i}</div><div><div class='ovname'>{esc(name)} <span class='stockcode'>{esc(code)}</span></div><div class='ovmeta'>{esc(meta)}</div></div></div>")
        cols_html.append(f"<div class='ovcol'><div class='ovhead'>{esc(title)}</div>{''.join(body)}</div>")

    consensus = []
    for code, cnt in sorted(dup_counts.items(), key=lambda x: (-x[1], x[0])):
        if cnt >= 2:
            stock = next((s for s in snap.get("stocks", []) if s.get("ticker") == code), None)
            if stock:
                consensus.append(f"{stock.get('name')}（{cnt}/3）")
    if consensus:
        st.markdown("<div class='consensus'><b>跨週期共識</b><div class='mini-note'>" + esc("、".join(consensus[:6])) + "</div><div class='consensus-note'>共識是多個時間尺度都強，不代表此刻就是買點。</div></div>", unsafe_allow_html=True)

    unique_n = len(set(code for code in dup_counts if code))
    st.markdown(f"<div class='mini-note'>完整日線訊號｜15 個訊號席位共 {unique_n} 檔股票；盤中買點另由即時頁處理。</div>", unsafe_allow_html=True)
    st.markdown("<div class='overview'>" + "".join(cols_html) + "</div>", unsafe_allow_html=True)

    allocation = service.select_cross_horizon_shortlists(snap, n=5, max_appearances=2)
    metrics = service.shortlist_overlap_metrics(allocation)
    st.markdown(f"<div class='mini-note'>若用於實戰配置：去重後約 {metrics.get('unique_tickers',0)} 檔不同股票，單一股票最多跨 2 個週期。</div>", unsafe_allow_html=True)


def _compact_pick_record(stock: dict, horizon: str, rank: int, list_type: str = "完整日線") -> dict:
    block = (stock.get("horizons") or {}).get(horizon, {}) or {}
    timing = block.get("entry_timing") or {}
    plan = block.get("plan") or {}
    zone_low = nfmt(plan.get("zone_low")) if plan.get("zone_low") is not None else "—"
    zone_high = nfmt(plan.get("zone_high")) if plan.get("zone_high") is not None else "—"
    zone = f"{zone_low}–{zone_high}" if zone_low != "—" and zone_high != "—" else "—"
    return {
        "清單": list_type,
        "週期": H_LABEL.get(horizon, horizon),
        "排名": rank,
        "股票": str(stock.get("name") or stock.get("ticker") or ""),
        "代號": str(stock.get("ticker") or ""),
        "產業": str(stock.get("fine_industry") or stock.get("industry") or ""),
        "現價": nfmt(stock.get("price")),
        "標的分數": nfmt(block.get("ranking_score"), 1),
        "買點分數": nfmt(timing.get("score"), 0),
        "建議動作": str(timing.get("action") or block.get("view_title") or "觀察"),
        "建議區間": zone,
        "轉強確認": nfmt(plan.get("trigger")),
        "跌破重看": nfmt(plan.get("invalidation")),
    }


def _recommendation_board_df(snap: dict | None, top_n: int = 5) -> pd.DataFrame:
    rows = []
    if not snap:
        return pd.DataFrame()
    for horizon in ("short", "mid", "long"):
        picks = service.select_market_best(snap, horizon, n=top_n)
        for i, stock in enumerate(picks, 1):
            rows.append(_compact_pick_record(stock, horizon, i, list_type="完整日線"))
    for horizon in ("short", "mid", "long"):
        picks = rank_next_session(snap, horizon=horizon, n=top_n)
        for i, stock in enumerate(picks, 1):
            rows.append(_compact_pick_record(stock, horizon, i, list_type="明日關注"))
    return pd.DataFrame(rows)


def _board_filtered_rows(snap: dict | None, top_n: int, category: str, period: str, consensus_only: bool) -> pd.DataFrame:
    """Presentation-only filtering; does not change selection or execution ranking."""
    df = _recommendation_board_df(snap, top_n=top_n)
    if df.empty:
        return df
    if category != "全部":
        df = df[df["清單"] == category]
    if period != "全部":
        df = df[df["週期"].str.startswith(period)]
    if consensus_only:
        # Consensus counts DISTINCT strategic horizons, never counts the same
        # ticker twice because it also appears in the next-session list.
        core = _recommendation_board_df(snap, top_n=top_n)
        core = core[core["清單"] == "完整日線"]
        consensus = core.groupby("代號")["週期"].nunique()
        codes = set(consensus[consensus >= 2].index)
        df = df[df["代號"].isin(codes)]
    return df.reset_index(drop=True)


def _render_recommendation_board(snap: dict | None):
    st.markdown("<div class='section-kicker'>ALL PICKS</div><div class='section-title'>推薦個股一頁總覽</div>", unsafe_allow_html=True)
    if not snap:
        st.info("請先更新完整日線資料。")
        return
    audit = assess_snapshot(snap)
    if audit["status"] == "BLOCK":
        st.error("來源日期或覆蓋口徑無法確認；以下僅為舊快照研究參考，不得當作最新推薦。")
    elif audit["status"] == "CHECK":
        st.warning("部分來源資料尚待核對，請先查看「資料健檢」。")
    st.caption(f"模型完整交易日 {snap.get('price_date') or '—'}｜以下為策略觀察，不代表現在一定可成交買入。")
    c1,c2 = st.columns(2)
    with c1:
        category=st.selectbox("清單", ["全部","完整日線","明日關注"], key="board_category_v173")
    with c2:
        period=st.selectbox("投資週期", ["全部","短線","中線","長線"], key="board_period_v173")
    consensus=st.toggle("僅顯示跨週期共識（至少 2 個週期）", value=False, key="board_consensus_v173")
    top_n=st.select_slider("每個週期顯示前幾名", options=[3,5,8,15], value=5, key="board_count_v173")
    df=_board_filtered_rows(snap, int(top_n), category, period, bool(consensus))
    if df.empty:
        st.info("這組條件目前沒有符合的推薦標的。關閉『跨週期共識』或增加前幾名可看到更多。"); return
    unique=int(df["代號"].nunique())
    st.caption(f"目前 {len(df)} 筆訊號／{unique} 檔不同股票；同股跨週期不代表分數可以相加。")
    with st.expander("單頁 Top 15 精簡摘要卡", expanded=True):
        for _,r in df.head(15).iterrows():
            action=str(r["建議動作"])
            st.markdown(
                "<div class='briefbox' style='border-top-color:#1248c7;padding:10px 12px;margin:6px 0'>"
                f"<div style='font-weight:900;font-size:1.03rem'>{esc(r['股票'])} <small style='color:#666'>{esc(r['代號'])}</small></div>"
                f"<div class='briefline'><b>{esc(r['週期'])}</b> · {esc(r['清單'])} · 第 {esc(r['排名'])} 名 · "
                f"標的 {esc(r['標的分數'])} · 買點 {esc(r['買點分數'])}</div>"
                f"<div class='briefline'>參考價 {esc(r['現價'])}｜{esc(action)}</div>"
                f"<div class='newsmeta'>買入區 {esc(r['建議區間'])} · 防守 {esc(r['跌破重看'])}</div></div>",
                unsafe_allow_html=True)
    with st.expander("橫向比較表（全部符合條件的股票）", expanded=False):
        st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("盤中買賣以『盤中買點』及官方驗證價為準。本總表不以昨收冒充即時價，也不改原始選股排序。")


def _prime(snap: dict | None):
    if not snap:
        return
    used: set[str] = set()
    for h in HORIZONS:
        picks = service.select_market_best(snap, h, n=5)
        stock = next((x for x in picks if x.get("ticker") not in used), picks[0] if picks else None)
        if stock:
            used.add(str(stock.get("ticker")))
            st.markdown(f"<div class='section-kicker'>{esc(H_LABEL[h])}</div>", unsafe_allow_html=True)
            _row(stock, h, snap, 1, live=False)

def _doctor(snap: dict | None):
    st.markdown("<div class='mini-note'>輸入股票後，系統會依目前時段自動切換：盤中使用即時價量判斷是否可買；盤後／盤前使用最近完整交易日規劃下一交易日。已有持股則改用持股結構判斷續抱、減碼或退出，不會拿『新買進分數』直接決定賣出。</div>", unsafe_allow_html=True)

    mode = st.radio(
        "診斷目的",
        ["考慮買入", "已有持股"],
        horizontal=True,
        key="doctor_mode_v17",
    )
    with st.form("doctor_v17"):
        code = st.text_input("股票代碼", value="2330", placeholder="例如 2330 或 6187.TWO")
        h = st.selectbox("評估週期", list(H_LABEL), format_func=lambda x: H_LABEL[x], index=0)
        cost_text = ""
        stop_text = ""
        trail_text = ""
        thesis = "尚未確認"
        if mode == "已有持股":
            cost_text = st.text_input("持股成本（元／股，建議填寫）", value="", placeholder="例如 980；留白仍可做結構判斷")
            thesis = st.selectbox("原買進理由目前狀態", ["尚未確認", "仍成立", "已不成立"], index=0)
            st.caption("以下兩項只有你原本就有明確紀律時才填；留白時系統會顯示自己的『模型防守價／獲利保護參考』，不再用 0.00 代表未知。")
            c1, c2 = st.columns(2)
            with c1:
                stop_text = st.text_input("你原本的停損／結構失效價（選填）", value="", placeholder="例如 920")
            with c2:
                trail_text = st.text_input("你原本的獲利保護價（選填）", value="", placeholder="例如 1040")
        button_text = "分析現在是否適合買" if mode == "考慮買入" else "分析續抱／減碼／賣出"
        go_ = st.form_submit_button(button_text, type="primary", use_container_width=True)

    if go_:
        if not snap:
            st.warning("請先按上方更新建立市場快照；個股診斷需要與短／中／長線模型使用同一個完整交易日基準。")
            st.session_state.pop("alpha_doctor", None)
        else:
            with st.spinner("讀取個股歷史、目前時段與交易決策…"):
                dr = service.diagnose_with_live(code, snap, DATA_DIR, horizon=h, now=_taipei_timestamp())
            dr["h"] = h
            dr["doctor_input"] = {
                "mode": mode,
                "cost": _optional_float(cost_text),
                "original_stop": _optional_float(stop_text),
                "trailing_protection": _optional_float(trail_text),
                "thesis": thesis,
            }
            st.session_state["alpha_doctor"] = dr

    dr = st.session_state.get("alpha_doctor")
    if not dr:
        return
    if dr.get("error"):
        st.error("找不到足夠行情資料，請確認股票代碼或稍後重試。")
        return
    stock = dr.get("stock")
    if not stock:
        return

    h = dr.get("h", "short")
    inputs = dr.get("doctor_input") or {"mode": "考慮買入"}
    phase_info = dr.get("phase") or session_reference_policy(_taipei_timestamp())
    phase = str(phase_info.get("phase") or "")
    phase_label = str(phase_info.get("label") or "")
    live_status = dr.get("live_status") or {}
    mode_used = str(inputs.get("mode") or "考慮買入")

    if mode_used == "已有持股":
        thesis_code = {"已不成立": "BROKEN", "仍成立": "INTACT"}.get(str(inputs.get("thesis")), "UNKNOWN")
        decision = holding_decision(
            stock,
            h,
            phase,
            cost=finite(inputs.get("cost")),
            original_stop=finite(inputs.get("original_stop")),
            trailing_protection=finite(inputs.get("trailing_protection")),
            thesis_state=thesis_code,
        )
        action = str(decision.get("action_code") or "HOLD")
        cls = "sell" if action == "SELL" else "wait" if action in {"REDUCE", "PROTECT", "DATA"} else "hold"
        kicker = f"{phase_label}持股判定 · {H_LABEL.get(h,h)}"
        subtitle = f"價格來源：{decision.get('price_source','—')}｜完整日線基準：{stock.get('price_date') or dr.get('analysis_date') or '—'}"
        if phase == INTRADAY and live_status.get("verified"):
            stamp = str(live_status.get("fetched_at") or "").replace("T", " ")[:19]
            subtitle += f"｜官方驗證 {stamp or '本次'}"
        elif phase == INTRADAY:
            subtitle += "｜官方即時驗證未通過，本次不使用即時價"
        st.markdown(
            f"<div class='doctor-hero {cls}'><div class='doctor-kicker'>{esc(kicker)}</div><div class='doctor-title'>{esc(stock.get('name'))} {esc(stock.get('ticker'))}｜{esc(decision.get('headline'))}</div><div class='doctor-sub'>{esc(subtitle)}</div></div>",
            unsafe_allow_html=True,
        )
        pnl = decision.get("pnl_pct")
        expected = finite(decision.get("remaining_expected_return"))
        display_price = decision.get("price") if decision.get("price") is not None else decision.get("reference_price")
        price_label = "官方即時價" if phase == INTRADAY and live_status.get("verified") else ("完整日線參考價（非即時）" if phase == INTRADAY else "完整日線基準價")
        metrics = [
            (price_label, nfmt(display_price,2)),
            ("持股評分", nfmt(decision.get("score"),1)),
            ("目前損益", "—" if pnl is None else f"{pnl:+.1f}%"),
            ("模型防守價", nfmt(decision.get("model_stop"),2)),
            ("獲利保護參考", nfmt(decision.get("profit_protection"),2)),
            ("剩餘預期報酬", "—" if expected is None else f"{expected*100:+.1f}%"),
        ]
        st.markdown("<div class='doctor-grid'>"+"".join(f"<div><small>{esc(k)}</small><b>{esc(v)}</b></div>" for k,v in metrics)+"</div>", unsafe_allow_html=True)
        reasons = decision.get("reasons") or []
        if reasons:
            st.markdown("<div class='doctor-reasons'>"+"<br>".join("• "+esc(x) for x in reasons)+"</div>", unsafe_allow_html=True)
        st.caption("模型防守價是依最近完整交易日結構計算；若你有原始停損／獲利保護價，系統會優先尊重你輸入的既有紀律。獲利保護參考只有在已有足夠浮盈時才出現。")
    else:
        global_ctx = _cached_global_context()
        decision = buy_decision(stock, h, phase, global_context=global_ctx)
        action = str(decision.get("action_code") or "WAIT")
        cls = "buy" if action in {"BUY", "SMALL", "READY"} else "wait"
        kicker = f"{phase_label}買入判定 · {H_LABEL.get(h,h)}"
        subtitle = f"價格來源：{decision.get('price_source','—')}｜完整日線基準：{stock.get('price_date') or dr.get('analysis_date') or '—'}"
        if phase == INTRADAY and live_status.get("verified"):
            stamp = str(live_status.get("fetched_at") or "").replace("T", " ")[:19]
            subtitle += f"｜官方驗證 {stamp or '本次'}"
        elif phase == INTRADAY:
            subtitle += "｜官方即時驗證未通過，本次不使用即時價"
        st.markdown(
            f"<div class='doctor-hero {cls}'><div class='doctor-kicker'>{esc(kicker)}</div><div class='doctor-title'>{esc(stock.get('name'))} {esc(stock.get('ticker'))}｜{esc(decision.get('headline'))}</div><div class='doctor-sub'>{esc(subtitle)}</div></div>",
            unsafe_allow_html=True,
        )
        zone = decision.get("buy_zone") or {}
        expected = finite(decision.get("expected_return"))
        rr = finite(decision.get("reward_risk"))
        price_label = "官方即時價" if phase == INTRADAY and live_status.get("verified") else ("完整日線參考價（非即時）" if phase == INTRADAY else "完整日線基準價")
        metrics = [
            (price_label, nfmt(decision.get("price"),2)),
            ("標的分數", nfmt(decision.get("selection_score"),1)),
            ("進場分數", nfmt(decision.get("entry_score"),1)),
            ("買入優先分數", nfmt(decision.get("score"),1)),
            ("剩餘預期報酬", "—" if expected is None else f"{expected*100:+.1f}%"),
            ("報酬／風險", "—" if rr is None else f"{rr:.2f}"),
        ]
        gshock = finite(decision.get("global_shock_score"))
        if gshock is not None:
            metrics.append(("隔夜壓力", f"{gshock:.0f}/100"))
        st.markdown("<div class='doctor-grid'>"+"".join(f"<div><small>{esc(k)}</small><b>{esc(v)}</b></div>" for k,v in metrics)+"</div>", unsafe_allow_html=True)
        if zone.get("available"):
            plan_items = [
                ("建議買入區", f"{nfmt(zone.get('low'),2)}–{nfmt(zone.get('high'),2)}"),
                ("突破確認價", nfmt(zone.get("trigger"),2)),
                ("不追價上限", nfmt(zone.get("chase_limit"),2)),
                ("模型防守價", nfmt(zone.get("stop"),2)),
            ]
            st.markdown("<div class='doctor-plan'>"+"".join(f"<div><small>{esc(k)}</small><b>{esc(v)}</b></div>" for k,v in plan_items)+"</div>", unsafe_allow_html=True)
        blockers = [str(x.get("label") or "") for x in (decision.get("failed_gates") or []) if isinstance(x, dict) and x.get("label")]
        detail = str(decision.get("detail") or "")
        lines = ([detail] if detail else []) + blockers[:4]
        if lines:
            st.markdown("<div class='doctor-reasons'>"+"<br>".join("• "+esc(x) for x in lines)+"</div>", unsafe_allow_html=True)
        if phase == INTRADAY and not bool(live_status.get("verified")):
            st.warning("盤中執行價未通過官方驗證，因此本次只保留完整日線參考，不會誤標為『現在可買』。")

    if phase == INTRADAY and not bool(live_status.get("verified")) and mode_used == "已有持股":
        st.warning("盤中執行價未通過官方驗證，因此本次不會用昨收代替目前價格做續抱／減碼／賣出判斷。")

    with st.expander("查看完整模型資料、技術圖、營收／EPS／法人", expanded=False):
        _row(stock, h, snap or {"market": {}, "snapshot_id": "doctor"}, 1, live=bool(stock.get("intraday")))


def main():
    st.set_page_config(page_title="Alpha Radar 17.4", page_icon="◼", layout="wide", initial_sidebar_state="collapsed")
    _bootstrap_secrets()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<div class='mast'><div class='brand'>ALPHA<span>/TW</span></div><div class='version'>17.4 · DATA QUALITY · MOBILE HUB</div></div>", unsafe_allow_html=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = _taipei_timestamp()
    phase_policy = session_reference_policy(now)
    st.markdown(
        f"<div class='phasebar'><b>{esc(phase_policy.get('label'))}模式</b><div class='mini-note'>{esc(phase_policy.get('notice') or '')}</div></div>",
        unsafe_allow_html=True,
    )

    if st.session_state.get("alpha_version") != service.OPERATIONS_VERSION:
        for k in ["alpha_snapshot", "alpha_doctor", "alpha_error"]:
            st.session_state.pop(k, None)
        st.session_state["alpha_version"] = service.OPERATIONS_VERSION
        previous = service.load_dashboard(DATA_DIR / "dashboard_snapshot.json")
        if previous and previous.get("model_version") == service.OPERATIONS_VERSION:
            st.session_state["alpha_snapshot"] = service.compact_session_dashboard(previous)

    # Doctor/execution hotfixes should invalidate only stale diagnosis state, not
    # force a costly full-market rebuild when the frozen selection core is unchanged.
    if st.session_state.get("alpha_doctor_version") != DOCTOR_VERSION:
        st.session_state.pop("alpha_doctor", None)
        st.session_state["alpha_doctor_version"] = DOCTOR_VERSION

    with st.sidebar:
        st.markdown("### V17 標準模型 · 17.4")
        st.caption("正式排名已鎖定：流動性合格股票全數計算，不再由 400/700/1000 候選數改變結果。")
        st.caption(f"歷史基準：{CANONICAL_MODEL_POLICY['history_period']}；資料模式：完整資料；公司/法人採全市場可比官方快照，前段標的另載入完整明細。")
        st.caption("短／中／長線各自排名；美股隔夜情勢只影響進場與部位，不改股票品質排名。")
        provider_runtime_status()
        st.caption("完整日線：任何時段都可手動更新；盤中不把未收盤日K寫進模型。")
        st.caption(f"盤中買點：每 {int(LIVE_SCAN.get('refresh_seconds',60))} 秒掃描流動性合格全市場，再對最多 {int(LIVE_SCAN.get('detail_max',360))} 檔執行官方價驗證與買點精算。")
        st.caption("盤後：若今日官方 EOD 已發布，完整重算；尚未發布時保留最近正式基準。")
        if st.button("清除快取"):
            DailyPriceStore(DATA_DIR / "daily_prices.sqlite").clear()
            service.remove_saved_dashboard(DATA_DIR / "dashboard_snapshot.json")
            st.session_state.pop("alpha_snapshot", None)
            st.success("已清除")

    settings = service.RunSettings(
        canonical_mode=True,
        history_period=str(CANONICAL_MODEL_POLICY["history_period"]),
        model_family=str(CANONICAL_MODEL_POLICY["model_family"]),
    )

    update_label = str(phase_policy.get("update_label") or "更新市場資料與模型")
    if st.button(update_label, type="primary", use_container_width=True):
        started = time.monotonic()
        previous_for_brief = st.session_state.get("alpha_snapshot")
        with st.spinner("先整理國際市場與重要消息快讀…"):
            waiting_brief = build_waiting_brief(DATA_DIR, _cached_global_context, previous_for_brief)
        _render_waiting_briefing(waiting_brief)
        st.info("目前正在執行模型更新；上方快讀已先顯示，更新期間本頁會暫時處於處理狀態，完成後顯示新快照。")
        bar = st.progress(0, text="0% · 準備更新")
        try:
            with scan_lock(DATA_DIR / "market_scan.lock"):
                def update(stage, value):
                    v = min(1.0, max(0.0, float(value)))
                    elapsed = int(time.monotonic() - started)
                    heartbeat = " · 仍在處理" if 0.18 <= v < 0.98 else ""
                    bar.progress(v, text=f"{int(v*100):d}% · {stage} · {elapsed}s{heartbeat}")

                scan_now = _taipei_timestamp()
                snap = service.run_scan(DATA_DIR, settings, progress=update, now=scan_now)
                st.session_state["alpha_snapshot"] = service.compact_session_dashboard(snap)
                st.session_state.pop("alpha_error", None)
                st.session_state["alpha_last_refresh"] = scan_now.strftime("%Y-%m-%d %H:%M:%S")
                gc.collect()
                bar.progress(1.0, text=f"100% · 更新完成 · {int(time.monotonic()-started)}s")
                mode = (snap.get("session") or {}).get("analysis_mode")
                if mode == "INTRADAY_BASELINE":
                    st.success("更新完成：完整日線基準已刷新；盤中買點將使用最新即時價量，不會把半根日K混入長期模型。")
                elif mode == "POSTCLOSE_FINAL":
                    st.success("更新完成：已納入今日正式收盤資料，可直接查看下一交易日短／中／長線與明日關注清單。")
                elif mode == "POSTCLOSE_PENDING":
                    st.warning("更新完成，但今日交易所完整 EOD 尚未齊備；完整模型先保留最近正式收盤，『明日關注』會在可取得今日收盤快照時提供暫行版本。稍後再按更新即可轉為正式盤後模型。")
                else:
                    st.success("更新完成：已使用最近完整交易日，產生下一交易日盤前關注清單。")
        except ScanBusyError as exc:
            st.warning(str(exc) + "。本頁會繼續使用上一份成功快照。")
        except Exception as exc:
            token = os.getenv("FINMIND_TOKEN", "")
            st.session_state["alpha_error"] = safe_error_text(exc, mask_tokens=(token,))
            st.error("更新未完成，已保留上一份成功快照。")
        finally:
            time.sleep(0.15)
            bar.empty()

    snap = st.session_state.get("alpha_snapshot")
    _market_header(snap)
    if st.session_state.get("alpha_error"):
        st.error(st.session_state.get("alpha_error"))

    view = st.radio("功能", VIEWS, horizontal=True, label_visibility="collapsed", key="view_v172")
    phase_now = session_reference_policy(_taipei_timestamp()).get("phase")

    if view == "總覽":
        st.markdown("<div class='section-kicker'>OVERVIEW</div><div class='section-title'>全時段決策總覽</div>", unsafe_allow_html=True)
        if snap and phase_now == INTRADAY:
            st.markdown("<div class='section-kicker'>BUY NOW</div><div class='section-title'>盤中最適合進場</div>", unsafe_allow_html=True)
            intraday_buy_fragment(snap, "short")
        elif snap:
            st.markdown("<div class='section-kicker'>NEXT SESSION</div><div class='section-title'>下一交易日優先關注</div>", unsafe_allow_html=True)
            _render_next_session(snap, "short", n=3)
        st.markdown("<div class='section-kicker'>DAILY CORE</div><div class='section-title'>完整日線短／中／長線</div>", unsafe_allow_html=True)
        _overview(snap)

    elif view == "盤中買點":
        st.markdown("<div class='section-kicker'>LIVE EXECUTION</div><div class='section-title'>盤中可執行買點</div>", unsafe_allow_html=True)
        if not snap:
            st.info("先建立完整日線基準模型，盤中才有經過篩選的候選池。")
        else:
            live_h = st.radio("盤中週期", ["short", "mid", "long"], horizontal=True, format_func=lambda h: H_LABEL[h], label_visibility="collapsed", key="live_h_v164")
            intraday_buy_fragment(snap, live_h)

    elif view == "明日關注":
        st.markdown("<div class='section-kicker'>NEXT SESSION</div><div class='section-title'>下一交易日盤前清單</div>", unsafe_allow_html=True)
        if not snap:
            st.info("請先更新完整日線資料。")
        else:
            next_h = st.radio("規劃週期", ["short", "mid", "long"], horizontal=True, format_func=lambda h: H_LABEL[h], label_visibility="collapsed", key="next_h_v164")
            _render_next_session(snap, next_h, n=5)

    elif view == "推薦總表":
        _render_recommendation_board(snap)

    elif view in {"短線", "中線", "長線"}:
        h = {"短線": "short", "中線": "mid", "長線": "long"}[view]
        st.markdown(f"<div class='section-kicker'>{esc(H_LABEL[h])}</div><div class='section-title'>完整日線前 5 名</div>", unsafe_allow_html=True)
        st.caption("此頁固定顯示最近完整收盤後的策略排名，不套用盤中價格；盤中執行請到『盤中買點』。")
        _render_daily_list(snap, h, 5)

    elif view == "資料健檢":
        st.markdown("<div class='section-kicker'>DATA INTEGRITY</div><div class='section-title'>資料完整度與同步日期</div>", unsafe_allow_html=True)
        report = assess_snapshot(snap)
        if report["status"] == "OK":
            st.success(report["label"] + "（僅代表快照內部檢查，並非外部行情驗證）")
        elif report["status"] == "BLOCK":
            st.error(report["label"] + "；請檢查來源與重跑更新，舊快照僅供歷史參考。")
        else:
            st.warning(report["label"] + "；不代表本次更新已成功同步兩市場。")
        if report.get("dates"):
            cols = st.columns(3)
            for col, (key, value) in zip(cols, report["dates"].items()):
                col.metric(key, value)
        if report.get("metrics"):
            items = list(report["metrics"].items())
            for offset in range(0, len(items), 3):
                cols = st.columns(3)
                for col, (key, value) in zip(cols, items[offset:offset + 3]):
                    col.metric(key, f"{value:,}")
        for issue in report["issues"]:
            st.markdown("- " + str(issue))
        st.caption("完整母體、歷史有效、最終可投資是不同口徑；不可將可投資家數誤當成上市上櫃總家數。此頁只檢查已存快照，不修改選股分數。")
    else:
        st.markdown("<div class='section-kicker'>CHECK</div><div class='section-title'>個股診斷</div>", unsafe_allow_html=True)
        _doctor(snap)

    st.caption("V17.4：新增資料健檢檢查上市上櫃來源日、普通股母體與可投資口徑；保留 V17.3 單頁推薦總表可篩選週期與跨週期共識；統一顯示同步基準日，新增『推薦總表』、國際市場快讀收合區、中文優先且近 5 日內的新聞快讀，並加強手機版閱讀對比。正式模型對所有流動性合格且具足夠歷史的股票計算短／中／長線；全球隔夜情勢只影響進場與風險預算，不改股票品質排名。模型估計不保證未來報酬。")


if __name__ == "__main__":
    main()
