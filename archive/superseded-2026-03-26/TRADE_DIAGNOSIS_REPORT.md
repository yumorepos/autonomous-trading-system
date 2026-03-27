# Trade Diagnosis Report

> Generated: 2026-03-26T02:53:27.272581+00:00
> Trades analyzed: 1

## hl-prove-20260326 — PROVE (❌ LOSS: $-0.4984)
**Failures:** funding_misread, wrong_direction
**What worked:** Early exit on broken thesis — limited loss; Quick exit — didn't let loser run
**What failed:** Entered funding arb but paid funding instead of earning; Price moved against position direction
**Should change:** Add funding direction verification before entry; Consider adding trend alignment filter
**Confidence:** low

## Failure Distribution
- **funding_misread** (1x): Entered funding arb but paid funding instead of earning
- **wrong_direction** (1x): Price moved against position direction

## Feature Importance
- **signal_score**: win_avg=0 vs loss_avg=5.6 → higher_losses [low]
- **funding_annualized**: win_avg=0 vs loss_avg=1.37 → higher_losses [low]
- **volume_24h**: win_avg=0 vs loss_avg=4112361.0 → higher_losses [low]
- **hold_minutes**: win_avg=0 vs loss_avg=94.7 → higher_losses [low]

## Recommendations
- 👁️ **funding_misread** (1x) [observation_only]
  Seen 1x — monitor but don't change yet (need 3+)
- 👁️ **wrong_direction** (1x) [observation_only]
  Seen 1x — monitor but don't change yet (need 3+)
