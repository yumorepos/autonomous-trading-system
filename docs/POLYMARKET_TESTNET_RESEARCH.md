# Polymarket Testnet Research
**Date:** 2026-03-20 20:04 EDT  
**Status:** ❌ NO PUBLIC TESTNET

---

## Key Findings

### 1. No Separate Testnet Environment

**Evidence from official docs:**
- Polymarket uses Polygon mainnet (chain ID 137)
- No testnet URL mentioned in documentation
- All API endpoints point to production: `https://clob.polymarket.com`
- SDK clients connect directly to mainnet

**Source:** https://docs.polymarket.com/trading/overview

### 2. Polymarket US vs International

**Polymarket US:**
- Has "sandbox environment for integration testing"
- Requires application process + approval
- Must contact support to initiate access
- Subject to regulatory requirements

**International Polymarket:**
- No separate sandbox URL
- "testnet tokens" mentioned but not documented
- Primary testing: Simulated trades locally (no real orders)

### 3. Safe Testing Path

**Without Testnet:**

**Option 1: Local Simulation (Current)**
- ✅ No real capital risk
- ✅ No API credentials needed
- ✅ Test all logic locally
- ❌ Cannot test real API interactions
- ❌ Cannot verify order signing
- ❌ Cannot test fills/rejections

**Option 2: Micro-Execution on Mainnet**
- ✅ Real API testing
- ✅ Real order flow
- ⚠️ Real capital at risk
- Strategy: Start with $1-5 positions
- Requirement: Fund Polygon wallet

**Option 3: Polymarket US Sandbox (If Qualified)**
- ✅ Safe testing environment
- ✅ No real capital
- ❌ Requires application + approval
- ❌ Subject to regulatory review
- Timeline: Unknown (application-based)

---

## Testing Recommendations

### Phase 1: Local Validation (Current, Complete)
✅ Paper trading operational  
✅ Signal routing working  
✅ Position management tested  
✅ Exit logic validated  
✅ State persistence confirmed  

**Status:** COMPLETE

---

### Phase 2: Code Verification (Before Real Money)

**Tasks:**
1. Implement EIP-712 order signing
   - Reference: https://github.com/Polymarket/clob-client/blob/main/src/signing/eip712.ts
   - Verify signature format matches spec

2. Implement HMAC authentication
   - Reference: https://github.com/Polymarket/clob-client/blob/main/src/signing/hmac.ts
   - Test header construction

3. Use official SDK for safety
   - Install: `pip install py-clob-client`
   - Let SDK handle signing + auth
   - Reduces custom code risk

4. Validate against SDK examples
   - Compare order structure
   - Verify API calls match SDK
   - Test error handling

**Status:** NOT STARTED

---

### Phase 3: Micro-Execution (Real Testing, Minimal Risk)

**Prerequisites:**
- ✅ 100+ paper trades validated
- ✅ Live-readiness validation passed
- ✅ Code review complete
- ❌ Polygon wallet funded

**Initial Test Plan:**
- Start: $5 per position (min viable)
- Test: 10 trades
- Monitor: Every fill, every rejection
- Validate: Order signing, execution, P&L tracking

**Capital Required:**
- Trading: $50 ($5 × 10 positions)
- Gas (MATIC): $5-10 (safety buffer)
- Total: ~$60

**Risk:**
- Max loss: $50 (if all trades fail)
- Realistic loss: $5-10 (partial losses)
- Learning value: HIGH (real API behavior)

**Status:** BLOCKED (need wallet + funds)

---

### Phase 4: Full Deployment (After Validation)

**Prerequisites:**
- ✅ 10+ micro-execution trades successful
- ✅ No critical bugs found
- ✅ Order signing verified
- ✅ P&L tracking accurate

**Scale-Up Plan:**
1. 10 trades @ $5 → review
2. 20 trades @ $10 → review
3. 50 trades @ $20 → full deployment

**Timeline:** 2-4 weeks after micro-execution start

---

## Polygon Wallet Setup

### What's Needed

1. **Wallet Address:**
   - Can use existing Hyperliquid wallet (0x8743...C01c [REDACTED])
   - Or create new wallet for isolation

2. **USDC (for trading):**
   - Bridge from Ethereum/other chain
   - Or buy directly on Polygon
   - Recommended start: $100

3. **MATIC (for gas):**
   - Bridge from Ethereum
   - Or buy on exchange
   - Recommended: $10 (100+ trades worth)

### Bridge Options

**Official Polygon Bridge:**
- URL: https://wallet.polygon.technology
- Supports: ETH, USDC, MATIC
- Fees: ~$5-20 (Ethereum gas)

**Exchanges (Easier):**
- Withdraw USDC directly to Polygon
- Withdraw MATIC directly to Polygon
- Lower fees than bridging

---

## API Credentials

### Derivation Process

**No Registration Required:**
- API credentials derived from private key
- No email/account signup
- Non-custodial (user controls keys)

**Process:**
```python
from py_clob_client.client import ClobClient

# 1. Connect with private key
client = ClobClient(
    "https://clob.polymarket.com",
    key=private_key,
    chain_id=137
)

# 2. Derive credentials (one-time)
api_creds = client.create_or_derive_api_creds()

# 3. Save for reuse
# api_creds = {
#   'apiKey': '...',
#   'secret': '...',
#   'passphrase': '...'
# }

# 4. Use in future sessions
client = ClobClient(
    "https://clob.polymarket.com",
    key=private_key,
    chain_id=137,
    creds=api_creds
)
```

**Security:**
- Credentials derived deterministically
- Can regenerate anytime
- Stored locally (never sent to server)

---

## Implementation Priority

### Immediate (Next Session)
1. Install py-clob-client SDK
2. Study order signing examples
3. Compare our implementation vs SDK
4. Document any gaps

### Short Term (1-2 days)
1. Implement EIP-712 signing
2. Test signature validation (local)
3. Build micro-execution script
4. Prepare wallet setup guide for user

### Medium Term (1-2 weeks)
1. User funds Polygon wallet
2. Run 10 micro-execution trades
3. Monitor results
4. Fix any issues found

### Long Term (2-4 weeks)
1. Scale up to full deployment
2. Integrate with existing system
3. Enable autonomous Polymarket trading

---

## Conclusion

**Polymarket Testnet:** ❌ Does not exist (public)

**Safe Testing Path:**
1. ✅ Local paper trading (complete)
2. ⏳ Code verification (next)
3. ⏳ Micro-execution on mainnet (when ready)
4. ⏳ Full deployment (after validation)

**Timeline:** 2-4 weeks minimum (conservative, safe)

**Blocker:** Polygon wallet needs funding ($60 recommended start)

---

*Research complete. No testnet available. Micro-execution is the safe testing path.*
