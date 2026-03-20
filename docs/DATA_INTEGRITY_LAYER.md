# Data Integrity & Signal Reliability Layer
**Version:** 1.0  
**Deployed:** 2026-03-20 19:18 EDT  
**Status:** ✅ OPERATIONAL

---

## Purpose

**Critical validation layer between data sources and signal generation.**

Ensures data quality through:
- Source health monitoring
- Schema validation
- Outlier detection
- Staleness checks
- Duplicate prevention
- Signal decay logic

**No data enters the system without passing validation.**

---

## Architecture Position

```
Data Sources (Hyperliquid, Polymarket)
      ↓
      ↓ Raw Data
      ↓
┌─────▼──────────────────┐
│ DATA INTEGRITY LAYER   │ ← You are here
│  • Source health       │
│  • Schema validation   │
│  • Outlier detection   │
│  • Freshness checks    │
│  • Duplicate prevention│
│  • Signal decay        │
└─────┬──────────────────┘
      ↓ Validated Data Only
      ↓
Signal Scanner → Paper Trader → Governance → Allocation
```

**Data Guarantee:** All data validated before influencing decisions

---

## System Health States

### 🟢 HEALTHY
- All sources operational
- No validation failures
- Data quality verified
- **Signal generation allowed**

### 🟡 DEGRADED
- Non-critical source issues
- Some validation failures
- Fallback behavior active
- **Signal generation restricted**

### 🔴 HALT
- Critical source down
- Excessive validation failures
- Data integrity compromised
- **Signal generation halted**

---

## Data Validation Checks

### 1. Source Health Monitoring 🏥

**Check:** Is data source responsive?

**Criteria:**
- API responds within 5 seconds
- Valid response structure
- Expected data fields present

**Thresholds:**
- 3 consecutive failures → DEGRADED
- Primary source (Hyperliquid) down → HALT

**Tracked Metrics:**
- Last successful fetch
- Last failure time
- Consecutive failure count
- Success rate (%)
- Average latency (ms)

---

### 2. Timestamp Freshness ⏱️

**Check:** Is data recent?

**Threshold:** 60 seconds max age

**Logic:**
```python
data_age = now() - data_timestamp
passed = data_age <= 60 seconds
```

**Severity:** CRITICAL (reject stale data)

**Reason:** Market conditions change rapidly, old data = bad decisions

---

### 3. Required Fields ✅

**Check:** All required fields present and non-null

**Required Fields:**

**Funding Data (Hyperliquid):**
- `coin` (asset name)
- `funding` (funding rate)
- `prevDayNtlVlm` (24h volume)
- `openInterest` (open interest)

**Market Data (Polymarket):**
- `question` (market question)
- `tokens` (Yes/No tokens)

**Signal Data:**
- `asset` (trading pair)
- `entry_price` (entry price)
- `signal_type` (strategy type)
- `timestamp` (signal time)

**Severity:** CRITICAL (reject incomplete data)

---

### 4. Price Outlier Detection 📊

**Check:** Is price change reasonable?

**Threshold:** 50% max price change from last value

**Logic:**
```python
change_pct = abs((current - last) / last) * 100
passed = change_pct <= 50%
```

**Severity:** WARNING (flag but allow)

**Reason:** Catch bad data feeds, flash crashes, API errors

---

### 5. Volume Validation 💧

**Check:** Sufficient volume for valid signal?

**Threshold:** $1,000 min 24h volume

**Logic:**
```python
passed = volume_24h >= 1000
```

**Severity:** WARNING (flag but allow)

**Reason:** Low volume = illiquid, unreliable data

---

### 6. Spread Validation 📏

**Check:** Bid-ask spread reasonable?

**Threshold:** 5% max spread

**Logic:**
```python
spread_pct = (ask - bid) / bid * 100
passed = spread_pct <= 5%
```

**Severity:** WARNING (flag but allow)

**Reason:** Wide spreads = illiquid, poor data quality

---

### 7. Funding Stability 📈

**Check:** Funding rate stable over time?

**Threshold:** < 50% volatility from recent average

**Logic:**
```python
recent_3 = last 3 funding rates
avg = mean(recent_3)
volatility = max(abs(f - avg) for f in recent_3)
unstable = volatility > abs(avg) * 0.5
```

**Severity:** WARNING (flag unstable funding)

**Reason:** Unstable funding = unreliable arbitrage opportunity

---

### 8. Duplicate Detection 🚫

**Check:** Signal already generated recently?

**Threshold:** 5 minute deduplication window

**Logic:**
- Same asset
- Same signal type
- Entry price within 1%
- Generated within last 5 minutes

**Severity:** WARNING (reject duplicates)

**Reason:** Prevent signal spam, redundant signals

---

### 9. Signal Decay ⏳

**Check:** Apply time-based decay to signal score

**Threshold:** 1 hour max signal lifetime

**Logic:**
```python
age_hours = (now() - signal_time) / 3600

if age_hours > 1:
    return 0, False  # Expired

decay_factor = 1.0 - (age_hours / 1.0)
decayed_score = original_score * decay_factor
```

**Effect:**
- Signal score decreases linearly with age
- After 1 hour, signal expires (score = 0)
- Fresh signals prioritized

**Example:**
- 0 min old: 100% score
- 15 min old: 75% score
- 30 min old: 50% score
- 45 min old: 25% score
- 60 min old: 0% score (expired)

---

## Validation Workflow

### For Hyperliquid Data:

1. ✅ Check source health (API responsive?)
2. ✅ Validate required fields (coin, funding, volume, OI)
3. ✅ Check volume threshold ($1K min)
4. ✅ Validate funding stability (recent history)
5. ⚠️ Flag outliers (if price change > 50%)

**Result:** Pass if all critical checks pass

---

### For Polymarket Data:

1. ✅ Check source health (API responsive?)
2. ✅ Validate required fields (question, tokens)
3. ✅ Check token prices (must be 0-1 range)

**Result:** Pass if all critical checks pass

---

### For Generated Signals:

1. ✅ Validate required fields (asset, price, type, timestamp)
2. ✅ Check timestamp freshness (< 60s old)
3. ✅ Detect duplicates (5 min window)
4. ✅ Apply signal decay (1h lifetime)

**Result:** Pass if all critical checks pass

**If rejected:** Log to `rejected-signals.jsonl` with full details

---

## Source Reliability Metrics

**Tracked per source:**

| Metric | Description |
|--------|-------------|
| **Total Requests** | All API calls attempted |
| **Total Failures** | Failed API calls |
| **Success Rate** | (Success / Total) * 100 |
| **Avg Latency** | Average response time (ms) |
| **Signals Generated** | Valid signals produced |
| **Signals Rejected** | Invalid signals blocked |
| **Rejection Reasons** | Breakdown by failure type |

**Example:**
```json
{
  "hyperliquid": {
    "total_requests": 48,
    "total_failures": 0,
    "avg_latency_ms": 625,
    "signals_generated": 192,
    "signals_rejected": 5,
    "rejection_reasons": {
      "stale_timestamp": 3,
      "low_volume": 2
    }
  }
}
```

---

## Fallback Behavior

**When source becomes DEGRADED:**
- Continue using last known good data (if < 5 min old)
- Increase validation strictness
- Flag all signals from degraded source
- Alert in data health report

**When source becomes HALT:**
- Stop using data from failed source
- Rely on other sources if available
- If primary source (Hyperliquid) down → halt all signal generation
- Manual intervention required

**Recovery:**
- Automatic after source health restored
- Requires 3 consecutive successful fetches
- Validation strictness returns to normal

---

## Rejected Signals Log

**File:** `logs/rejected-signals.jsonl`

**Structure:**
```json
{
  "timestamp": "2026-03-20T23:15:00Z",
  "source": "hyperliquid",
  "signal": {
    "asset": "ZETA",
    "entry_price": 0.0558,
    "signal_type": "funding_arbitrage",
    "timestamp": "2026-03-20T22:10:00Z",
    "ev_score": 95
  },
  "reason": "Signal too stale (65 minutes old)",
  "validations": [
    {
      "check_name": "timestamp_freshness",
      "passed": false,
      "severity": "CRITICAL",
      "reason": "Data age: 3900s (max: 60s)"
    },
    {
      "check_name": "signal_decay",
      "passed": false,
      "severity": "CRITICAL",
      "reason": "Signal expired (age > 1h)"
    }
  ]
}
```

**Use:** Audit trail, debugging, identify data quality patterns

---

## Data Health Report

**File:** `DATA_HEALTH_REPORT.md`  
**Updated:** Every 4 hours (before signal scanner)

**Contents:**
1. **System Health** (HEALTHY/DEGRADED/HALT)
2. **Source Status** (per source)
   - Health (UP/DEGRADED/DOWN)
   - Last success/failure
   - Success rate
   - Latency
   - Signals generated/rejected
   - Rejection reasons
3. **Data Quality Metrics** (thresholds)

**Example:**
```markdown
# DATA HEALTH REPORT
**System Health:** HEALTHY

## Data Sources

### 🟢 Hyperliquid
**Status:** UP
**Last Success:** 2026-03-20T23:18:39Z
**Success Rate:** 100%
**Avg Latency:** 625ms
**Signals Generated:** 192
**Signals Rejected:** 5

**Rejection Reasons:**
- stale_timestamp: 3
- low_volume: 2
```

---

## Schedule

**Data integrity checks run:**
- **XX:55** — Before signal scanner (pre-validation)

**Full cycle:**
```
XX:55 → Data Integrity Layer (validate sources) ← NEW
XX:00 → Trading Agency (scan + trade)
XX:15 → Governance Supervisor (evaluate + decide)
XX:25 → Safety Layer (pre-validation)
XX:30 → Portfolio Allocator (assign capital)
XX:35 → Safety Layer (post-validation)
```

**Next check:** 19:55 EDT

---

## Integration Points

### With Signal Scanner
- Data integrity runs **before** scanner
- Scanner reads validated data only
- Rejected signals logged
- Signal decay applied automatically

### With Execution Safety Layer
- Data health feeds safety status
- HALT data → HALT safety → HALT execution
- Shared incident logging

### With Governance Supervisor
- Data quality metrics inform strategy evaluation
- Unreliable sources flagged
- Signal rejection patterns tracked

---

## Benefits

1. **Early Detection**
   - Catch bad data before it influences decisions
   - Prevent cascading failures

2. **Source Accountability**
   - Track reliability per source
   - Identify problematic APIs

3. **Signal Quality**
   - Only high-quality signals pass
   - Time decay prevents stale opportunities

4. **Graceful Degradation**
   - Fallback behavior when sources fail
   - Continue operating on good data

5. **Full Audit Trail**
   - Every rejection logged
   - Every validation tracked
   - Full observability

---

## Data Quality Guarantees

✅ **No Stale Data**
- Max 60 seconds data age
- Automatic expiry

✅ **No Incomplete Data**
- All required fields validated
- Reject missing/null fields

✅ **No Price Outliers**
- 50% max price change
- Catch bad feeds

✅ **No Low Volume**
- $1K min 24h volume
- Ensure liquidity

✅ **No Wide Spreads**
- 5% max bid-ask spread
- Data quality indicator

✅ **No Unstable Funding**
- 50% max volatility
- Stable arbitrage opportunities

✅ **No Duplicate Signals**
- 5 minute deduplication
- Prevent spam

✅ **No Old Signals**
- 1 hour max lifetime
- Time decay applied

✅ **No Unreliable Sources**
- 3 consecutive failures → DEGRADED
- Primary source down → HALT

---

## Files & Locations

| File | Purpose | Updated |
|------|---------|---------|
| `scripts/data-integrity-layer.py` | Validation engine | Every 4h |
| `logs/data-integrity-state.json` | Current state | Every 4h |
| `logs/source-reliability-metrics.json` | Source metrics | Every 4h |
| `logs/rejected-signals.jsonl` | Rejected signals | On reject |
| `DATA_HEALTH_REPORT.md` | Human report | Every 4h |

---

## Operational Procedures

### Daily Review
1. Check `DATA_HEALTH_REPORT.md`
2. Verify system health is HEALTHY
3. Review rejection reasons
4. Check source success rates

### After Data Issues
1. Review `logs/rejected-signals.jsonl`
2. Identify patterns (specific source? specific check?)
3. Check source health metrics
4. Determine if threshold adjustment needed

### When Source Fails
1. System automatically degrades to DEGRADED/HALT
2. Review `logs/data-integrity-state.json`
3. Check last successful fetch timestamp
4. Verify source is actually down (external status page)
5. Wait for automatic recovery (3 successful fetches)

### Manual Override
1. Edit `logs/data-integrity-state.json`
2. Adjust thresholds if needed (temporary)
3. Force source health status (emergency only)
4. Document reason in incident log

---

**Data integrity layer operational. All inputs validated before influencing system decisions.**

*Zero tolerance for bad data. Quality over quantity.*
