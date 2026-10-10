# Alpha Radar V17.1 — Validation Status

## PASS — offline engineering / model-integrity validation

- one synchronized completed-session date is enforced across TWSE, TPEx and benchmark;
- if official exchange dates disagree, one repair attempt is made and unresolved cases roll the entire model back to the latest common date;
- no mixed-date cross-sectional ranking is published;
- baseline investable universe widened to 3 million TWD 20-day average turnover;
- short/mid/long final lists use separate liquidity/evidence guardrails;
- frozen short/mid/long selection weights are unchanged;
- global/US context remains an execution-risk layer, not a ranking factor;
- waiting briefing/news is display-only and cannot alter scores;
- full-history refresh cadence is bounded while daily official EOD overlay remains active;
- verified MIS executable-price rules remain intact;
- Doctor, Panic Reversal and research-data regressions remain passing;
- all major Streamlit surfaces pass offline smoke tests.

## Real-market performance

**NOT CLAIMED.**

This environment does not provide reliable full live-provider connectivity, so the package does not claim that a real-market 2026 walk-forward or a complete Streamlit Cloud end-to-end provider run was completed here. The included networked validation workflows remain the correct next step for measured short/mid/long out-of-sample performance.
