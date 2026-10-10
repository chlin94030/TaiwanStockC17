# Alpha Radar V17.3 — Mobile Recommendation Board

## Implemented
- V17.2 source retained, with V17.1 synchronized EOD and global context architecture.
- Recommendation total board now has watchlist category filter, short/mid/long horizon filter, consensus-only filter, and 3/5/8/15 ranks controls.
- Consensus counts only **distinct completed-day horizons**, never the same name in both daily and next-session lists.
- Single-page Top 15 compact cards show ticker, name, horizon, list, ranking, selection score, entry score, buy zone, invalidation and action.
- Full wider comparison table is in a collapsed expander for mobile use.
- The board is **presentation-only**. No change to return_first_model, policy_engine, market_data or strategy_config; no new weighting rules.

## Performed offline checks
- Python compileall PASS.
- Streamlit import stub smoke PASS.
- Decision view smoke PASS.
- test_v17_3_mobile_board.py PASS (horizon/category/consensus/duplicate rules).

## Unverified
No live Streamlit Cloud or verified broker/market feed end-to-end in this container. No historical return validation was performed for this UI-only change.
