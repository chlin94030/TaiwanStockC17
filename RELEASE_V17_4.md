# Alpha Radar V17.4 — Release and acceptance notes

## Deployment

Upload the **contents** of this folder to the GitHub repository root, preserving `.github/workflows/qa_v17.yml`. Do not upload any API tokens, `data/`, `__pycache__/`, or SQLite history. In Streamlit Cloud select `app.py` as entrypoint and re-deploy. Preserve existing server-side data storage where persistent storage is configured; Streamlit Cloud ephemeral disk is not guaranteed across restarts.

**Do not clear historical cache by default.** This update does not require redownloading five years of bars. The initial run on a fresh deployment still requires full historical data.

## Included V17.4 changes

- Retains V17.3 compact recommendation board, 3/5/8/15 top-N view, period/category filters and correct distinct-horizon consensus.
- Stronger conservative snapshot audit (OK / CHECK / BLOCK), with validated source dates, safe date rollback, price/model date consistency and mother/valid/model-count invariants.
- Market header never claims synchronized sources when the audit is CHECK or BLOCK.
- Recommendation board prominently labels an unreliable saved snapshot as historical research only.
- QA suite includes regression tests for V17.3 mobile board and V17.4 integrity.
- Updated on-screen progress wording to avoid incorrectly asserting background execution.
- Existing quote TTL cache and same-date technical feature reuse are retained. There is **no new demonstrated latency reduction** in this release.

## Honest acceptance boundaries

Offline tests assert model contracts using fixtures. They are **not** proof of real-time availability, full-market completeness on the live exchange, actual execution fills, higher returns, or faster server/network response.

A live acceptance test must still verify: official TWSE and TPEx same-date EOD; the genuine common completed-session cutoff; actual ticker population; quote freshness and provenance during market hours; update elapsed time on target Streamlit deployment; news freshness; and historical walk-forward returns versus benchmark and Gemini recommendations. Without these observations this build should not be represented as live-verified or profit-validated.

## Run tests

```
python -m compileall -q .
python test_v174_integrity.py
python test_v17_3_mobile_board.py
python test_v17_1_sync_briefing.py
python test_full_qa_v16_7_2.py
python test_v17_goal_complete.py
python smoke_all_views_v16_7_2.py
python smoke_app_main.py
python run_full_qa.py
```

`run_full_qa.py` runs a large suite and can take several minutes. The GitHub Action runs it on pushes.
