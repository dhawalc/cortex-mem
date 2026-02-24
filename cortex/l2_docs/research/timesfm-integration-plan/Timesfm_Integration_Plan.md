# TimesFM Integration Plan for SPX 0DTE Options Forecasting
**Agent A - Round 1 Technical Analysis**
*Date: 2026-02-21*

## Executive Summary
**Recommendation: Conditional YES** - TimesFM shows promise for SPX microstructure forecasting but requires careful implementation given 0DTE latency constraints.

---

## 1. FEASIBILITY ANALYSIS

### Model Specifications (TimesFM 2.5)
- **Parameters:** 200M (down from 500M in v2.0)
- **Context length:** Up to 16k datapoints
- **Forecast horizon:** Up to 1k steps
- **Quantile forecasting:** Native support (10th-90th percentiles)
- **Architecture:** Decoder-only transformer (patched attention)

### Compute Requirements

#### Inference Latency (Critical for 0DTE)
**Target:** <100ms for actionable signals (0DTE requires sub-second decision loops)

**Estimated Performance:**
- **CPU (baseline):** ~500-1500ms for 1024 context → 128 horizon forecast
- **GPU (T4/A10):** ~50-150ms 
- **GPU (A100):** ~20-50ms
- **Optimized (Flax + XLA):** Potential 30-40% reduction

**Reality Check:** TimesFM is NOT real-time native. Needs:
- Model compilation (`torch.compile()` or JAX XLA)
- Batch prediction caching
- Pre-warmed inference server
- Likely GPU requirement for sub-100ms

#### Hardware Recommendations
**Minimum viable:**
- NVIDIA T4 (16GB VRAM) - ~$0.35/hr on GCP
- 8 CPU cores, 32GB RAM
- NVMe storage for tick data

**Production optimal:**
- NVIDIA A10G/A100 for <50ms inference
- 16+ CPU cores for parallel feature engineering
- Redis for sub-ms feature cache

### Data Requirements

#### Input Format
TimesFM expects:
- **1D array per series:** `[price_t-n, ..., price_t-1, price_t]`
- **Normalization:** Built-in (zero-mean, unit variance)
- **No frequency indicator needed** (v2.5 removed this)

#### 0DTE-Specific Data Pipeline
**Context window (1024 samples):**
- **1-min bars:** Last 17 hours (~1 trading session + premarket)
- **5-sec bars:** Last 85 minutes (intraday microstructure)
- **Tick-level:** Last ~2-3 minutes at 10 ticks/sec

**Proposed Multi-Timeframe Approach:**
1. **Primary series:** SPX spot price (5-sec bars, 1024 context)
2. **Auxiliary series (XReg covariates):**
   - VIX spot (volatility regime)
   - /ES futures (lead indicator)
   - SPY volume delta
   - Put/call ratio (CBOE data)
   - Market maker gamma exposure (optional, if accessible)

**Data freshness:** Must be <1sec old when forecast executes

---

## 2. POTENTIAL EDGE/ALPHA vs CURRENT INDICATORS

### Current Bot Capabilities (Assumed Baseline)
- **COINMAN/SPXMAN likely use:**
  - Technical indicators (RSI, MACD, Bollinger)
  - Volume/momentum signals
  - Static threshold-based entries
  - Rule-based position sizing

### TimesFM Advantages

#### 1. **Probabilistic Forecasting = Better Risk Management**
- **Built-in quantile forecasts** (10th-90th percentiles)
- Can estimate expected move AND tail risk
- **Example:** 
  - Point forecast: SPX +2.5 pts in 5min
  - 10th percentile: -1.2 pts (downside risk)
  - 90th percentile: +6.8 pts (upside potential)
  - **Action:** Size position based on asymmetry

#### 2. **Microstructure Pattern Recognition**
- Trained on massive time-series corpus
- Can detect:
  - Intraday mean-reversion vs momentum regimes
  - Pre-FOMC/event volatility clustering
  - Open/close auction dynamics
  - Gamma squeeze patterns (if trained on similar assets)

#### 3. **Zero-Shot Adaptability**
- No retraining needed for regime shifts
- Can handle unprecedented volatility (COVID-like events)
- Works across different market conditions out-of-box

#### 4. **Multi-Horizon Forecasting**
- Single inference → forecast next 5min, 15min, 30min
- **Alpha:** Align option expiry time with forecast horizon
  - 0DTE at 2PM → forecast to 4PM close (120min horizon)
  - Scale position size by forecast confidence decay

### Expected Alpha (Conservative Estimate)

**Hypothesis:** TimesFM adds 1-3% to Sharpe ratio
- **Baseline Sharpe (current bots):** ~0.8-1.2 (typical for retail algo trading)
- **With TimesFM:** ~1.0-1.5
- **Mechanism:** Better entry timing, reduced false signals, improved sizing

**Key Metrics to Track:**
- Win rate improvement: +3-5%
- Average win/loss ratio: +10-15%
- Max drawdown reduction: -5-10%

---

## 3. INTEGRATION APPROACH

### Architecture: Hybrid Indicator + TimesFM

```
┌─────────────────────────────────────────────────┐
│          Data Ingestion Layer                   │
│  (SPX tick/1min, VIX, /ES, Options flow)        │
└────────────┬────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│       Feature Engineering Pipeline              │
│  • Normalize to TimesFM format                  │
│  • Build 1024-bar context windows               │
│  • Cache recent predictions (Redis)             │
└────────────┬────────────────────────────────────┘
             │
        ┌────┴────┐
        ▼         ▼
   ┌─────────┐  ┌──────────────────┐
   │ Classic │  │ TimesFM Forecast │
   │ Signals │  │   (5-120min)     │
   │ (Fast)  │  │   GPU Server     │
   └────┬────┘  └─────────┬────────┘
        │                 │
        └────────┬────────┘
                 ▼
      ┌────────────────────┐
      │  Signal Fusion     │
      │  (Weighted Blend)  │
      └──────────┬─────────┘
                 │
                 ▼
      ┌────────────────────┐
      │  COINMAN/SPXMAN    │
      │  Position Mgmt     │
      └────────────────────┘
```

### Implementation Phases

#### Phase 1: Offline Validation (Week 1-2)
**Goal:** Prove predictive power on historical data

1. **Backtest setup:**
   - Pull 3 months SPX 1-min data (Polygon/IEX)
   - Simulate TimesFM forecasts at 9:30, 10:00, 11:00, 2:00, 3:00 ET
   - Compare forecast vs actual next 5/15/30/60min moves
   - Metrics: MAE, RMSE, directional accuracy

2. **Benchmark vs baseline:**
   - Compare TimesFM vs simple ARIMA/LSTM
   - Compare vs "last hour trend continuation" naive model

3. **Success criteria:**
   - Directional accuracy >55% (5min horizon)
   - Forecast error <0.15% of SPX price
   - Quantile calibration within 5% (10th percentile captures 10% of outcomes)

#### Phase 2: Live Inference Server (Week 3)
**Stack:**
- **Framework:** FastAPI server
- **Model loading:** 
  ```python
  model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
      "google/timesfm-2.5-200m-pytorch"
  )
  model.compile(...)  # Torch compile for speed
  ```
- **Endpoints:**
  - `POST /forecast` - Single prediction
  - `POST /batch_forecast` - Multiple series
  - `GET /health` - Model warm status

**Deployment:**
- Docker container on GPU instance
- Health checks every 30s
- Auto-restart on OOM/GPU crash

#### Phase 3: COINMAN/SPXMAN Integration (Week 4)
**Signal Fusion Logic:**

```python
# Pseudocode
def generate_entry_signal(timestamp):
    # Classic indicators (fast, always available)
    rsi = get_rsi(period=14)
    macd = get_macd()
    classic_score = score_classic_signals(rsi, macd)
    
    # TimesFM forecast (cached or real-time)
    tfm_forecast = get_timesfm_forecast(
        horizon=12,  # 12 * 5sec = 1min ahead
        use_cache=True,
        max_age_sec=5
    )
    
    # Fusion
    if tfm_forecast.available:
        # Weighted average (tune in paper trading)
        signal = 0.6 * tfm_forecast.score + 0.4 * classic_score
        confidence = tfm_forecast.quantile_spread  # Wider = less confident
    else:
        # Fallback to classic only
        signal = classic_score
        confidence = 0.5  # Medium confidence
    
    # Position sizing
    position_size = base_size * confidence * (1 - current_risk_utilization)
    
    return signal, position_size
```

**Key Integration Points:**
1. **Async prediction:** Don't block on TimesFM, use last cached forecast if new one isn't ready
2. **Fallback mode:** If GPU crashes, revert to classic indicators automatically
3. **Confidence throttling:** Reduce position size when forecast uncertainty is high

#### Phase 4: Paper Trading (Week 5-8)
- Run parallel: live bot vs TimesFM-enhanced bot (paper accounts)
- Track P&L, Sharpe, drawdown side-by-side
- A/B test signal weights (50/50, 60/40, 70/30)

#### Phase 5: Live Deployment (Week 9+)
- Start with 10% of capital
- Ramp up if 2-week Sharpe > baseline

---

## 4. RISKS & LIMITATIONS

### Critical Risks

#### 1. **Latency Death Spiral** ⚠️ HIGH RISK
**Problem:** 
- TimesFM inference = 50-150ms (GPU)
- Data fetch + feature prep = 20-50ms
- Total loop time = 70-200ms
- 0DTE options move in <500ms during volatility spikes

**Mitigation:**
- Pre-cache features in Redis (update every 1sec)
- Run predictions every 5-10sec, not every tick
- Use forecast as "bias" not absolute signal
- Keep classic indicators for sub-second reactions

**Residual Risk:** May miss fast reversals. Acceptable if win rate improves overall.

#### 2. **Training Data Mismatch** ⚠️ MEDIUM RISK
**Problem:**
- TimesFM trained on generic time-series (likely web data, IoT, retail)
- SPX has unique market microstructure:
  - Non-stationarity (regime changes)
  - Volatility clustering
  - Gamma/delta hedging flows
  - Event risk (FOMC, earnings)

**Evidence of Mismatch:**
- Zero-shot models excel at "average" patterns
- May fail at tail events (flash crashes, squeezes)

**Mitigation:**
- **Fine-tuning (not officially supported in v2.5 yet):** Wait for LoRA/adapter support
- **Ensemble approach:** Blend TimesFM with domain-specific LSTM trained on SPX
- **Regime detection:** Disable TimesFM during high-VIX (>30) or low-liquidity periods

#### 3. **Overfitting to Backtest** ⚠️ MEDIUM RISK
**Problem:**
- Choosing optimal forecast horizon, signal weights via backtest
- May not generalize to future market structure

**Mitigation:**
- Walk-forward validation (train on 2024, test on 2025, deploy on 2026)
- Use separate tuning period vs validation period
- Monitor live performance daily, auto-disable if Sharpe drops <0.5

#### 4. **Cost Blowup** ⚠️ LOW-MEDIUM RISK
**GPU Costs:**
- A10G = ~$0.50-1.00/hr × 12 trading hours/day = $6-12/day = $130-260/month
- Only justified if alpha > $500/month (>2x cost)

**Mitigation:**
- Start with CPU inference (slower but free on existing infra)
- Upgrade to GPU only if backtest shows >1% Sharpe improvement
- Use spot instances (70% cheaper, handle interruptions gracefully)

#### 5. **Model Staleness**
**Problem:** TimesFM 2.5 released Sept 2025, trained on pre-2025 data
- May not capture 2026 market dynamics

**Mitigation:**
- Monitor forecast calibration monthly
- If 10th percentile captures >15% outcomes (vs expected 10%), model is mis-calibrated
- Plan for v2.6 or fine-tuning path

### Limitations (Accept & Work Around)

1. **No Explanability:** 
   - TimesFM is a black box (transformer attention)
   - Can't debug "why" it predicted X
   - **Workaround:** Use for alpha, not compliance/risk reporting

2. **No Options-Specific Features:**
   - Model doesn't natively understand implied vol, greeks, skew
   - **Workaround:** Feed IV/gamma as covariates (XReg), let model learn correlation

3. **Requires Stable Data Pipeline:**
   - Any gap in data = context window breaks
   - **Workaround:** Implement gap-filling (linear interpolation, or skip prediction)

---

## 5. SUCCESS CRITERIA

### Go/No-Go Metrics (After Phase 1 Backtest)

**GO if:**
- Directional accuracy >54% (5min horizon, 1000+ samples)
- Sharpe improvement >0.1 vs baseline
- Inference latency <200ms (p95)

**NO-GO if:**
- Accuracy <52% (no better than coin flip)
- High correlation with existing indicators (redundant)
- GPU cost >$300/month for <$1000 alpha/month

### Live Trading KPIs

**Track weekly:**
- TimesFM signal contribution to P&L (attribution analysis)
- Forecast calibration (actual vs predicted quantiles)
- Latency p50/p95/p99
- GPU uptime %

**Auto-disable triggers:**
- 3-day losing streak attributable to TimesFM signals
- Forecast calibration error >20%
- Latency p95 >500ms

---

## 6. RESOURCE REQUIREMENTS

### Dev Time
- **Phase 1 (backtest):** 20-30 hours
- **Phase 2 (inference server):** 15-20 hours
- **Phase 3 (integration):** 25-35 hours
- **Phase 4 (paper trade monitoring):** 10 hours setup + 4 weeks observation
- **Total:** ~80-100 dev hours (~2-3 weeks full-time)

### Infrastructure
- **GPU:** $130-260/month (can defer to Phase 4)
- **Data:** Polygon/IEX market data (if not already subscribed)
- **Monitoring:** Prometheus + Grafana (or reuse existing)

### Ongoing Maintenance
- Model performance review: 2 hours/week
- Pipeline debugging: 4-6 hours/month (expected)

---

## CONCLUSION

**TimesFM is a HIGH-POTENTIAL, MEDIUM-RISK addition to SPX 0DTE strategy.**

**Strengths:**
- Native probabilistic forecasting (risk management edge)
- Zero-shot = no retraining overhead
- Multi-horizon = flexible expiry targeting
- Proven foundation model architecture

**Weaknesses:**
- Latency may limit tick-level reactivity
- Unproven on options microstructure
- GPU costs need alpha justification
- No fine-tuning path yet (v2.5)

**Recommendation:**
1. **Invest 2 weeks in rigorous backtest** (Phase 1)
2. **If directional accuracy >54% → proceed to paper trading**
3. **Run parallel 4-week A/B test**
4. **Go live only if Sharpe improvement >0.15 AND alpha > 3x GPU cost**

**Alternative Path (if backtest fails):**
- Use TimesFM for regime detection only (high/low vol, trend/mean-revert)
- Keep entry signals classic, use TimesFM for position sizing
- Explore fine-tuning when Google releases adapter support

---

**Next:** Agent B critique & challenge assumptions.
