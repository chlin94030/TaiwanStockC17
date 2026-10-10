# Alpha Radar V17.0 — Debug / Architecture Report

## Design-goal audit result

V16.8 correctly separated selection, intraday strength, entry timing, position sizing and Doctor decisions, but its completed-day model was still capped by `candidate_size` and richer research could be present for only a subset of stocks. That meant it could truthfully claim “best within the evaluated pool,” not “best across every liquid eligible stock.”

V17.0 closes those gaps without retuning the frozen short/mid/long weights.

## Structural changes

- Production `RunSettings.canonical_mode=True` forces the 5-year/full-evidence canonical contract.
- `model_candidates()` returns every liquid eligible name in canonical mode.
- `ResearchDataClient.official_breadth_snapshot()` builds market-wide comparable evidence from bulk official endpoints rather than thousands of independent research requests.
- Ranking uses `stock["ranking_research"]`; rich `stock["research"]` is presentation/detail only.
- `_combined_ranking_score()` uses fixed evidence weights with neutral imputation + bounded coverage penalty instead of re-normalizing missing evidence upward.
- Institutional one-day breadth evidence is reliability-shrunk toward neutral; richer multi-session data can express a larger signal in display/research mode but do not silently change canonical ranking.
- Same completed-day V17 price/analog cores are reused from the saved dashboard snapshot; only new/missing names are recomputed.
- Intraday full-market quote cap raised to 2,500; detailed official-verified execution pool remains bounded at 360.
- Doctor on-demand evaluation uses the same comparable breadth ranking evidence.

## Regression invariants retained

- incomplete intraday daily candles never enter historical features;
- TWSE/TPEx MIS `z` is the executable price; previous close is never relabeled live;
- market regime changes position budget, not ranking;
- global/US context changes execution/risk, not ranking;
- limit-up/near-limit-up names can rank highly but remain non-buyable when chasing risk is excessive;
- panic reversal requires broad stress + resilience + rebound + intact structure + expected-return/RR/evidence gates;
- existing-holder decisions remain separate from new-entry timing.

## Executed offline QA

`run_full_qa.py` completed successfully after the final V17 code changes. It includes all legacy architecture/Doctor/verified-price/research/UI regressions plus `test_v17_goal_complete.py`.

V17-specific passes include:

- canonical mode ignores candidate-count truncation;
- non-canonical research mode can still intentionally cap candidates;
- display research cannot alter canonical ranking;
- missing research cannot gain an artificial score via weight re-normalization;
- official breadth parsing for revenue/financial/valuation/institutional data;
- canonical UI no longer exposes history/candidate-count controls;
- frozen selection weights remain unchanged.

## Performance note

A local synthetic probe of the shared 3-horizon historical engine measured about 0.10 s/name on this packaging CPU (200 names in ~20 s), implying a first full 1,500-name computation on the order of minutes, not seconds. Same-date V17 snapshots reuse the expensive completed-day core, so repeated intraday updates do not repeat that full computation. Real cloud timing depends on provider/network/cache state.

## Limitation

The packaging container cannot reach the real TWSE/TPEx universe endpoints, so true networked end-to-end and real 2026 profitability validation are not claimed here.
