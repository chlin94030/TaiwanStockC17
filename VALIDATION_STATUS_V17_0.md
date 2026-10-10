# V17.0 Validation Status

## PASS — engineering / architecture

- full liquid-universe canonical candidate contract;
- short/mid/long frozen weight integrity;
- comparable market-wide ranking research;
- neutral missing-evidence handling;
- completed-day vs intraday separation;
- official verified execution-price boundary;
- Pullback / Continuation / Panic-Reversal entry paths;
- Doctor buy/hold/reduce/sell separation;
- same-date completed-core reuse;
- all legacy research/UI/parser regressions;
- all major app surfaces smoke tested.

## Real 2026 performance replay

**NOT_RUN in this packaging container.**

A real-data probe of `validate_v17_2026_walkforward.py --stocks 20 --points 10` stopped because the environment retrieved 0 TWSE and 0 TPEx universe rows. The validator wrote `validation_not_run.json` and did not substitute synthetic prices.

The GitHub workflow `Validate V17 2026 walk-forward` is configured for 150 real stocks, 12 shared 2026 cutoffs and Top-5 evaluation at 10/40/120 sessions. Historical fundamentals/flows remain excluded from replay unless a true point-in-time archive is available; using current fundamentals in past dates would create look-ahead bias.

## Interpretation

V17.0 is validated as a coherent, reproducible decision system, not as a guaranteed alpha strategy. Any claim of superior realized return must wait for the networked point-in-time replay and subsequent live observations.
