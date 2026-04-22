"""D41 backtest-retroactive gate validation.

Applies the live CompositeSignalScorer formula (with documented proxies for
features unavailable in historical data) to the canonical 180-day backtest
trade log. Partitions trades by the 0.70 execution gate and classifies
the gate's effect per D41 thresholds (AMPLIFIES / NEUTRAL / HARMS / UNKNOWN).

Read-only wrt the canonical artifact
(`artifacts/backtest_trades_d31.jsonl`, sha256 2ee4f37...).
"""
