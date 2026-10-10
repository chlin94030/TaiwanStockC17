# Alpha Radar V17.1 — Synced Market / Fast Brief Debug Report

## Why V17.1 was required

Production V17.0 exposed three issues that could undermine trust in the published ranking even though the core scoring engine itself had not changed:

1. The UI could show TWSE and TPEx official EOD dates from different sessions (for example, TWSE one day behind TPEx). V17.0 could then build a cross-sectional model with mixed exchange dates.
2. The label “full model” hid the fact that the canonical universe still applied history, freshness, price and liquidity filters. A 10 million TWD 20-day average-turnover floor was especially restrictive and could leave roughly one thousand modeled names without explaining the rest of the mother universe.
3. Global context was displayed with raw abbreviations (SOX/NDX/TSM ADR/VIX/NQ), and a long model update left the user staring at a progress bar without useful reading material.

The user also reported that the selected stocks “felt off”. The largest model-integrity risk found in this audit was not a new weighting formula; it was the mixed-date comparison and one-size-fits-all final investability gate.

## Date synchronization fix

`radar_service.run_scan()` now enforces one completed-session date for every published cross-sectional ranking.

- During PREOPEN/INTRADAY it derives the newest safely cached completed session and uses that date as an explicit official-data target hint.
- If TWSE and TPEx return different official dates, the app retries once using the newer returned date as an explicit date-specific target.
- If the retry still cannot align both exchanges, the model deliberately rolls *all* markets back to the latest common confirmed date.
- TWSE, TPEx and benchmark cutoffs used by the model are then identical.
- The raw exchange dates are retained only as diagnostics: `raw_twse_date`, `raw_tpex_date`, `raw_index_date`.
- The actual model date is recorded as `model_sync_date`.

Therefore V17.1 cannot publish a Top-N ranking that compares a TWSE stock at D-1 with a TPEx stock at D.

## Coverage and “why not every listed stock?”

V17.1 separates four concepts that V17.0 compressed into “full model”:

1. ordinary-share mother universe;
2. sufficient completed-day history;
3. baseline investable model universe;
4. final horizon-specific comparable universe.

The baseline 20-day average-turnover floor is reduced from 10 million TWD to 3 million TWD, widening the modeled universe. Final recommendations then use horizon-specific guardrails without changing raw ranking scores:

- short: >= 10 million TWD average turnover and >= 60% evidence coverage;
- mid: >= 5 million TWD and >= 70% evidence coverage;
- long: >= 3 million TWD, >= 78% evidence coverage, empirical estimate available, and company evidence (financials plus revenue or valuation).

The UI now discloses mother-universe size, history-valid size, baseline modeled size, short/mid/long eligible counts, and exclusion counts (history insufficient, stale date, low price, low turnover).

## Global context readability

Raw abbreviations are mapped to plain Traditional Chinese labels, for example:

- SOX -> 美國半導體
- NDX -> 那斯達克100
- TSM ADR -> 台積電ADR
- VIX -> 市場恐慌指數
- NQ futures -> 那斯達克100期貨
- SPX -> 標普500
- US10Y -> 美國10年債殖利率
- DXY -> 美元指數

Global context remains an execution/risk layer only. It does not mutate short/mid/long selection scores.

## Useful reading while the full model updates

A new `market_briefing.py` creates an early waiting brief before the expensive canonical scan begins. It fetches in parallel:

- plain-language overnight/global market context;
- a public news headline digest focused on Taiwan/TSMC/AI/semiconductors, Fed/inflation/yields, and major chip-policy/export-control developments;
- the previous successful model’s short/mid/long leaders, clearly marked as the previous baseline only.

The news digest is reading-only. Its conservative “possibly bullish / possibly bearish / needs interpretation” keyword hint never enters the ranking model.

If news or global endpoints fail, the canonical Taiwan model update continues. Cached brief data can be shown when available.

## Performance change

Five-year history remains the canonical model window, but a full historical provider refresh is now a maintenance operation (default every 30 days). Daily operation still overlays official completed EOD data. Same-date core reuse remains active, so repeated updates on the same completed session should avoid unnecessary multi-year refetch/recompute work.

## Stock-selection guardrails

The frozen raw selection weights are unchanged. V17.1 adds only publication-quality guardrails after the raw scores are calculated. Buy-now and next-session recommendation functions skip names explicitly marked ineligible for their horizon.

Each stock card also exposes the high-level score components (technical / historical / fundamental / institutional flow / evidence coverage) so an unexpected leader can be audited from the UI instead of appearing as a black box.

## Offline regression executed

`run_full_qa.py` completed successfully after the final V17.1 changes.

Passed groups include:

- architecture regression;
- Doctor buy/hold/sell regression;
- verified executable-price regression (including the 2059/川湖 stale-close case);
- V16.7.2 full QA;
- Panic Reversal regression;
- V17 full-universe canonical regression;
- V17.1 synchronization / briefing / horizon-guardrail regression;
- research data/detail/preload/UI regressions;
- app import, decision views, all major surfaces and app-main smoke tests.

Final result: `ALL V17.1 OFFLINE QA PASSED`.

## Validation boundary

The offline suite proves code-path, time-boundary and ranking-integrity rules. It does **not** prove profitability. This environment cannot reliably execute a full real-network TWSE/TPEx/MIS/Yahoo/FinMind end-to-end run, so the actual Streamlit deployment remains the final live-provider check. Real 2026 walk-forward validation is still required before claiming alpha or retuning the frozen selection weights.
