# Alpha Radar V17.1 — Synced Market / Fast Brief

V17.1 is a production-integrity release on top of V17.0. It fixes mixed TWSE/TPEx completed-date risk, makes universe coverage explicit, adds horizon-specific final investability/evidence guardrails, translates global-market abbreviations into plain Traditional Chinese, and gives the user a useful global/news/previous-model briefing while the expensive canonical update runs.

Key invariants remain unchanged: short/mid/long raw selection weights are frozen; global news/context never changes stock-quality ranking; intraday executable decisions still require verified prices; Panic Reversal remains a downstream entry route rather than a selection factor.

See `DEBUG_REPORT_V17_1.md` and `VALIDATION_STATUS_V17_1.md` for the exact synchronization, coverage and QA contract.

---

# Alpha Radar V17.0 — Goal Complete / Full-Market Canonical

V17.0 is the first release whose production contract is explicitly aligned with the original goal: **at any query time, identify the best available Taiwan-stock candidates for short (10 sessions), mid (40 sessions), and long (120 sessions), then separately decide whether the current price is actionable.**

## Canonical production model

The normal UI no longer exposes candidate-count/history-length knobs that could silently change the answer. Production is fixed to:

- completed-day history: 5 years;
- universe: every liquid common stock with sufficient completed-day history;
- model family: full evidence;
- short/mid/long selection weights unchanged from the frozen core;
- global/US context affects execution risk and panic-reversal logic only, never stock-quality ranking.

## V17.0 changes

1. **Full liquid-universe baseline** — `candidate_size` no longer truncates production ranking. Every liquid stock with adequate history gets short/mid/long forecasts.
2. **Comparable breadth research** — official TWSE/TPEx market-wide revenue, latest financial, valuation and institutional evidence are loaded on one comparable scale for ranking. Rich historical research is loaded for leading names for display only and cannot change the published ranking.
3. **Missing evidence is neutral, not rewarded** — absent fundamental/flow evidence is neutral-imputed and receives a small bounded coverage penalty. Missing fields no longer inflate the remaining weights through re-normalization.
4. **Same-date core reuse** — if the completed-session date has not changed, the expensive historical/analog core is reused and only comparable research/ranking is refreshed.
5. **Full-market intraday discovery** — the one-minute scan quotes up to 2,500 liquid names and sends a bounded detail pool through official MIS price verification before BUY/SELL/HOLD execution scoring.
6. **Three entry routes remain separate** — Pullback, Continuation and Panic Reversal. Falling knives, structural breaks and near-limit-down situations remain blocked.
7. **Doctor consistency** — on-demand stock diagnosis uses the same comparable ranking evidence as the market selector; rich research is display detail, not an unfair ranking advantage.

## Time-of-day behavior

- **Pre-open:** latest completed-day canonical ranking + next-session watchlist + overnight global context.
- **Intraday:** completed-day ranking stays frozen; quotes refresh every 60 seconds; official MIS-verified execution prices drive buy/hold/sell decisions.
- **Post-close:** today's official EOD is used when complete; otherwise the last completed model remains authoritative and is clearly labeled pending.
- **Off-day:** latest completed session is reused; no fake daily candle is created.

## Core selection weights (unchanged)

| Horizon | Technical | Historical analog | Fundamental | Institutional flow |
|---|---:|---:|---:|---:|
| Short | 52% | 20% | 8% | 20% |
| Mid | 42% | 22% | 22% | 14% |
| Long | 34% | 22% | 34% | 10% |

Selection answers **what is worth owning**. Entry timing answers **whether this price is worth paying now**. Market/global regimes size risk; they do not rewrite selection quality.

## Verification

Run:

```bash
python run_full_qa.py
```

The bundled GitHub workflow `.github/workflows/qa_v17.yml` runs the same suite on push. A separate `validate_v17_2026_walkforward.py` performs leakage-controlled real-stock 2026 replay when external market data are reachable.

## Validation boundary

Offline engineering QA is complete. Real-market profitability is **not claimed** from the packaging container because external Taiwan market connectivity is unavailable there. The validator refuses to substitute synthetic data for real performance.

## Deployment

Upload the package source files to the repository; do **not** upload `__pycache__` or `.pyc` files. Existing price/research SQLite caches can be kept, but the first V17 update must build a new V17 dashboard snapshot because the model version changed.

## V17.3 — Mobile Recommendation Board

A new compact **推薦總表** board supports list filters (completed daily or next-session), horizon filters (short/mid/long), cross-horizon consensus (>=2 *distinct completed-day horizons*) and 3/5/8/15 picks per horizon. A Top 15 expandable summary and separately collapsed full comparison table reduce mobile scrolling. This release does not alter model weights or historical ranking logic.

See `DEBUG_REPORT_V17_3.md` and run `python test_v17_3_mobile_board.py`.
