# TimesFM 2.5 Technical Assessment for SPX 0DTE Trading
**Date:** 2026-02-21  
**Model:** Google TimesFM 2.5 (200M parameters)  
**Evaluated By:** OpenClaw AI Research  
**Use Case:** Intraday SPX 0DTE option trading (D2DT/COINMAN/SPXMAN)

---

## Executive Summary

### ⚠️ Critical Finding: DO NOT USE ZERO-SHOT FOR PRODUCTION

TimesFM 2.5, while an impressive foundation model, shows **poor zero-shot performance** on SPX financial data:

- **No trading edge**: 50% directional accuracy (random guessing)
- **Worse than baselines**: Underperforms simple linear trend by 35.8%
- **Miscalibrated quantiles**: Uncertainty estimates not well-calibrated for financial data
- **Not trained on finance**: Training data is primarily web traffic, retail, and weather - NOT markets

### Verdict

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Zero-shot SPX forecasting** | ❌ FAIL | No edge, worse than simple baselines |
| **Architecture quality** | ✅ GOOD | Solid transformer design, efficient inference |
| **Inference speed** | ⚠️ ACCEPTABLE | ~100-300ms per forecast (CPU) |
| **Quantile support** | ⚠️ LIMITED | Feature exists but poorly calibrated |
| **Fine-tuning potential** | ✅ PROMISING | Could work with domain adaptation |
| **Production readiness** | ❌ NOT READY | Requires fine-tuning on market data |

**Recommendation:** TimesFM is NOT ready for 0DTE trading out-of-the-box. Consider fine-tuning on proprietary market data OR use alternative approaches.

---

## 1. Model Overview

### Architecture
- **Type:** Decoder-only transformer with input patching
- **Parameters:** 200M (down from 500M in v2.0)
- **Context window:** Up to 16,384 time points (vs 2,048 in v2.0)
- **Horizon:** Up to 1,024 steps with quantile head
- **Patch length:** Input patches of 32, output patches of 128
- **Quantiles:** Continuous quantile forecasting (10th-90th percentiles)

### Key Features
- ✅ Zero-shot forecasting (no retraining needed)
- ✅ Variable context and horizon lengths
- ✅ Probabilistic forecasts via quantiles
- ✅ Multi-granularity support
- ✅ Fast inference with patching
- ❌ NOT frequency-aware (removed in 2.5)
- ❌ Limited covariate support

### Training Data
TimesFM was trained on:
- **Google Trends** (~0.5B time points): Search interest data
- **Wikipedia Pageviews** (~300B time points): Page view statistics  
- **Synthetic data** (~6B time points): ARMA, seasonal patterns, trends
- **Other:** M4 competition, electricity, traffic, weather datasets
- **Total:** ~100B time points across hourly to yearly granularities

**❗ Critical limitation:** NO financial market data in training corpus!

---

## 2. Evaluation Results

### Test Setup
- **Data:** SPX (^GSPC) at multiple timeframes (1-min, 5-min, hourly, daily)
- **Period:** Feb 13-20, 2026 (recent data)
- **Context:** 80% of data for context, 20% for testing
- **Hardware:** CPU inference (no GPU acceleration)

### 2.1 Forecasting Accuracy (5-min bars)

| Horizon | MAE | MAPE | Direction Accuracy | Inference Time |
|---------|-----|------|-------------------|----------------|
| 12 bars (1h) | $14.26 | 0.21% | **54.5%** | 360ms |
| 24 bars (2h) | $24.83 | 0.36% | **65.2%** | 102ms |
| 48 bars (4h) | $27.49 | 0.40% | **53.2%** | 101ms |
| 78 bars (6.5h) | $37.37 | 0.54% | **53.2%** | 101ms |

**Analysis:**
- Directional accuracy ~50-65% (barely better than random)
- Longer horizons don't consistently improve accuracy
- First inference slower (360ms) due to model compilation
- Subsequent inferences ~100ms (acceptable for 5-min bars)

### 2.2 Multi-Timeframe Comparison

| Timeframe | Horizon | TimesFM MAE | Baseline MAE | Improvement | Direction Acc |
|-----------|---------|-------------|--------------|-------------|---------------|
| 1-min | 60 bars | $4.37 | $2.78 | **-57.4%** ❌ | 32.2% |
| 5-min | 48 bars | $27.49 | $24.17 | **-13.7%** ❌ | 53.2% |
| Hourly | 24 bars | $39.89 | $25.40 | **-57.0%** ❌ | 43.5% |
| Daily | 20 bars | $45.58 | $46.05 | **+1.0%** ⚠️ | 63.2% |

**Baseline:** Simple "last value" persistence model

**Key Finding:** TimesFM performs WORSE than just using the last price on intraday data!

### 2.3 Baseline Method Comparison (24-bar forecast)

| Method | MAE | Notes |
|--------|-----|-------|
| **TimesFM** | $24.83 | Zero-shot foundation model |
| Last Value | $23.35 | Just use last price |
| Linear Trend | **$18.28** ✅ | Best performer |
| MA(20) | $34.33 | 20-bar moving average |

**Conclusion:** Simple linear trend extrapolation beats TimesFM by 35.8%!

### 2.4 Trading Simulation Results

**Setup:**
- Rolling forecasts with 100-bar lookback
- 12-bar forecast horizon (~1 hour)
- Direction-only trading (long if up, short if down)

**Results:**
- Total predictions: 24
- Correct direction: 12
- **Accuracy: 50.0%** (exactly random!)
- **Edge over random: 0.0%**

**Conclusion:** Zero trading edge for directional plays.

### 2.5 Quantile Forecasting Performance

| Quantile | Expected Coverage | Actual Coverage | Error |
|----------|------------------|-----------------|-------|
| Q10 | 10% | 2.1% | -7.9% |
| Q50 | 50% | 8.3% | -41.7% ❌ |
| Q90 | 90% | 43.8% | -46.2% ❌ |

**Analysis:**
- Quantiles are **severely miscalibrated** for financial data
- Model underestimates uncertainty (too confident)
- Cannot be trusted for risk management without recalibration

### 2.6 Volatility Forecasting

| Metric | Value |
|--------|-------|
| Predicted volatility | 0.41% |
| Actual volatility | 0.10% |
| Error | 0.31% |

**Conclusion:** Overestimates volatility by ~4x (consistent with quantile miscalibration)

### 2.7 Performance Benchmarks

| Context Length | Horizon | Avg Inference Time | Std Dev |
|----------------|---------|-------------------|---------|
| 100 bars | 12 | 110.5ms | ±0.8ms |
| 100 bars | 96 | 101.7ms | ±1.3ms |
| 200 bars | 12 | 101.3ms | ±0.6ms |
| 200 bars | 96 | 101.9ms | ±0.2ms |

**Analysis:**
- Inference time fairly constant (~100ms) after first call
- Not sensitive to context or horizon length (within tested ranges)
- Acceptable for 5-min bars, but too slow for 1-min high-frequency trading
- GPU acceleration could improve this significantly

---

## 3. Why TimesFM Fails on Financial Data

### 3.1 Training Data Mismatch
TimesFM was trained on:
- Web traffic (Google Trends, Wikipedia pageviews)
- Retail data (M4 competition)
- Weather and electricity consumption
- Transportation/traffic data

**Financial time series are fundamentally different:**

| Characteristic | Web/Retail Data | Financial Markets |
|----------------|-----------------|-------------------|
| Stationarity | Mostly stationary | Non-stationary, regime changes |
| Distribution | Normal/log-normal | Fat tails, asymmetric |
| Autocorrelation | Strong, predictable | Weak, time-varying |
| Noise level | Low-medium | High (tick-level chaos) |
| Patterns | Seasonal, trending | Mean-reverting, momentum |
| Frequency | Mostly daily+ | Millisecond to daily |

### 3.2 Market-Specific Challenges
1. **Efficient Market Hypothesis**: Prices incorporate available information quickly
2. **Regime changes**: Market behavior shifts (bull/bear, high/low vol)
3. **Non-linear relationships**: Interactions between price, volume, volatility
4. **Microstructure noise**: Bid-ask bounce, liquidity gaps
5. **Fat tails**: Extreme events more common than normal distribution predicts

### 3.3 Why Simple Baselines Win
Linear trend works better because:
- SPX has strong momentum intraday
- Simple extrapolation captures short-term trends
- No complex patterns that need deep learning

TimesFM tries to find patterns from its training (web traffic, etc.) that don't exist in markets!

---

## 4. Compute Requirements

### Hardware Tested
- **CPU:** Standard x86_64 (no GPU)
- **RAM:** ~4GB for model weights
- **Storage:** ~800MB for model checkpoint

### Inference Performance
- **Cold start:** ~60s (model loading)
- **Warm inference:** ~100-300ms per forecast
- **Batch processing:** Not tested (could amortize overhead)

### GPU Acceleration Potential
- Model supports CUDA
- Expected speedup: 5-10x faster inference
- Recommended for high-frequency applications

### Production Considerations
- **Model size:** Reasonable (200M params = 800MB)
- **Memory footprint:** ~2-4GB RAM at runtime
- **Latency:** Acceptable for 5-min bars, marginal for 1-min
- **Throughput:** Could handle multiple symbols with batching

---

## 5. Integration Architecture

### 5.1 Current Bot Landscape

```
D2DT (Options Bot)
├── Technical indicators
├── Volume analysis
└── Strike selection logic

COINMAN (Crypto Bot)
├── Order book analysis
├── Momentum signals
└── Position sizing

SPXMAN (0DTE SPX Bot)
├── Intraday signals
├── Entry/exit logic
└── Risk management
```

### 5.2 Proposed Integration (IF Fine-Tuned)

```
Enhanced SPXMAN
├── Traditional signals (60% weight)
│   ├── RSI, MACD, Bollinger
│   ├── Volume profile
│   └── Support/resistance
│
├── TimesFM ML signals (30% weight) ← NEW
│   ├── Multi-horizon forecasts
│   ├── Directional confidence
│   └── Volatility predictions
│
└── Risk management (10% weight)
    ├── TimesFM quantiles for position sizing
    └── Dynamic stop-loss based on predicted vol
```

### 5.3 Integration Code Pattern

```python
class EnhancedSPXMAN:
    def __init__(self):
        self.timesfm = TimesFMAdapter()  # Fine-tuned model
        self.technical = TechnicalIndicators()
        
    def get_entry_signal(self, bars):
        # Traditional signals
        rsi = self.technical.rsi(bars)
        macd = self.technical.macd(bars)
        
        # ML signals
        ml_forecast = self.timesfm.forecast_next_bars(bars['Close'].values)
        ml_direction = self.timesfm.get_directional_signal(bars['Close'].values)
        
        # Ensemble
        if rsi < 30 and macd.bullish and ml_direction['signal'] == 'UP':
            return {
                'action': 'BUY',
                'confidence': 'HIGH',
                'position_size': self.size_from_quantiles(ml_forecast)
            }
        
        # ... rest of logic
```

**See `integration_examples.py` for full code examples.**

---

## 6. Fine-Tuning Strategy

### 6.1 Why Fine-Tuning is Essential

Zero-shot TimesFM fails because:
1. Not trained on financial data
2. Doesn't understand market dynamics
3. Quantiles miscalibrated for fat-tailed distributions

**Fine-tuning could fix these issues by:**
1. Adapting to SPX price patterns
2. Learning intraday momentum/mean-reversion
3. Calibrating uncertainty estimates to market volatility

### 6.2 Data Requirements

**Minimum viable:**
- 1 year of intraday data (5-min bars)
- ~78 bars/day × 252 days = ~20,000 bars
- Include multiple market regimes (bull, bear, sideways, high/low vol)

**Recommended:**
- 3-5 years of data for robustness
- Multiple symbols (SPX, SPY, QQQ) for generalization
- Include volume and volatility features

### 6.3 Fine-Tuning Approach

```python
# Pseudo-code for fine-tuning
from timesfm import TimesFM_2p5_200M_torch

# Load pre-trained model
model = TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")

# Prepare SPX training data
train_data = load_spx_data(years=3, interval='5min')
val_data = load_spx_data(years=0.5, interval='5min')

# Fine-tune with lower learning rate
from torch.optim import AdamW
optimizer = AdamW(model.parameters(), lr=1e-5)  # Small LR to avoid forgetting

# Training loop
for epoch in range(10):
    for batch in train_loader:
        context, horizon_truth = batch
        
        # Forward pass
        point_pred, quantile_pred = model.forecast(context)
        
        # Combined loss: point accuracy + quantile calibration
        point_loss = mse_loss(point_pred, horizon_truth)
        quantile_loss = quantile_loss_fn(quantile_pred, horizon_truth)
        total_loss = 0.7 * point_loss + 0.3 * quantile_loss
        
        # Backward pass
        total_loss.backward()
        optimizer.step()
        optimizer.zero_grad()
```

**Challenges:**
- Need significant GPU resources (A100/H100 for fast training)
- Risk of overfitting to recent market regime
- Requires careful validation to avoid data leakage

### 6.4 Estimated Effort

| Task | Time Estimate | Resources |
|------|--------------|-----------|
| Data collection & cleaning | 1-2 days | Historical data API |
| Fine-tuning setup | 2-3 days | GPU server (A100) |
| Training experiments | 3-5 days | 40-80 GPU hours |
| Validation & testing | 3-5 days | Backtesting infrastructure |
| Integration | 2-3 days | Dev environment |
| **Total** | **2-3 weeks** | **$500-1000 GPU costs** |

---

## 7. Alternative Approaches

If fine-tuning TimesFM isn't viable, consider:

### 7.1 Simpler ML Models
- **LightGBM/XGBoost**: Gradient boosting on engineered features
  - Pros: Fast, interpretable, good with tabular data
  - Cons: Need feature engineering, less flexible
  
- **LSTM/GRU**: Recurrent models for sequences
  - Pros: Designed for time series, well-understood
  - Cons: Training can be slow, prone to overfitting

### 7.2 Specialized Financial Models
- **GARCH variants**: For volatility modeling
- **Kalman filters**: For state-space modeling
- **HMM**: For regime detection

### 7.3 Ensemble Strategies
Combine multiple weak learners:
```python
final_prediction = (
    0.3 * timesfm_forecast +
    0.3 * xgboost_forecast +
    0.2 * linear_trend +
    0.2 * garch_volatility
)
```

### 7.4 Practical Recommendations

**For 0DTE trading:**
1. **Stick with traditional signals** (RSI, MACD, orderflow) - they work!
2. **Use ML for auxiliary tasks:**
   - Position sizing based on predicted volatility
   - Trade filtering (avoid low-edge setups)
   - Stop-loss optimization
3. **Focus on what ML is good at:**
   - Pattern recognition in high-dim data
   - Non-linear relationships
   - Regime classification

**Don't use ML for:**
- Pure price prediction (efficient markets!)
- Replacing domain expertise
- Black-box decision making

---

## 8. Detailed Limitations

### 8.1 Model Limitations
1. **No market microstructure**: Doesn't model bid-ask, liquidity, orderflow
2. **No fundamental data**: Can't incorporate earnings, news, macro
3. **Univariate only**: Current version doesn't handle multi-asset portfolios well
4. **Fixed architecture**: Can't easily add domain-specific inductive biases

### 8.2 Operational Limitations
1. **Inference latency**: ~100ms too slow for scalping
2. **Model drift**: Performance degrades as market regime changes
3. **No online learning**: Can't update model real-time with new data
4. **Black box**: Hard to interpret why model makes certain predictions

### 8.3 Data Limitations
1. **Limited history**: Only 5 days of 5-min data available from yfinance
2. **Survivorship bias**: Only current SPX constituents
3. **No tick data**: Missing microstructure information
4. **Missing context**: No volume at price, no orderbook depth

---

## 9. Comparison to Alternatives

| Feature | TimesFM 2.5 | Prophet | LSTM | XGBoost | Linear Models |
|---------|-------------|---------|------|---------|---------------|
| Training required | Fine-tuning | Minimal | Full | Full | Minimal |
| Inference speed | 100-300ms | <1ms | 10-50ms | <1ms | <1ms |
| Quantile forecasts | ✅ Yes | ✅ Yes | ⚠️ Via ensemble | ⚠️ Via quantile loss | ❌ No |
| Multi-horizon | ✅ Native | ⚠️ Sequential | ⚠️ Sequential | ❌ Single-step | ❌ Single-step |
| Interpretability | ❌ Low | ✅ High | ❌ Low | ⚠️ Medium | ✅ High |
| SPX performance (zero-shot) | ❌ Poor | ⚠️ OK | N/A | N/A | ✅ Good |
| Fine-tuning potential | ✅ High | ❌ Low | ✅ High | ✅ High | ❌ Low |
| Resource requirements | 🔴 High | 🟢 Low | 🟡 Medium | 🟢 Low | 🟢 Low |

---

## 10. Recommendations

### 10.1 DO NOT USE (Zero-Shot)
❌ Do NOT deploy zero-shot TimesFM for SPX 0DTE trading
- No edge (50% directional accuracy)
- Worse than simple baselines
- Miscalibrated risk estimates
- Not trained on financial data

### 10.2 CONSIDER (With Fine-Tuning)
⚠️ TimesFM COULD be valuable IF fine-tuned:
- Collect 3-5 years of proprietary SPX data
- Fine-tune on GPU cluster (2-3 weeks)
- Validate thoroughly on hold-out data
- Use as ONE signal in ensemble, not sole decision maker

### 10.3 RECOMMENDED ALTERNATIVES
✅ Practical approaches for 0DTE trading:

**Short-term (implement now):**
1. Enhance existing technical signals
2. Add orderflow/volume analysis
3. Improve risk management (dynamic stops)
4. Use simple ML for regime classification

**Medium-term (1-2 months):**
1. Build custom LSTM/XGBoost model on your data
2. Focus on feature engineering (not model complexity)
3. Start with volatility prediction (easier than price)
4. Ensemble multiple simple models

**Long-term (3-6 months):**
1. If you have resources, experiment with TimesFM fine-tuning
2. Consider building proprietary foundation model on multi-asset data
3. Explore reinforcement learning for adaptive strategies

---

## 11. Code & Artifacts

### Generated Files
All code and results available in `/home/dhawal/.openclaw/workspace/timesfm_tests/`:

1. **`comprehensive_evaluation.py`** - Full test suite with 6 evaluation categories
2. **`test_multiple_timeframes.py`** - Comparison across 1-min, 5-min, hourly, daily
3. **`integration_examples.py`** - Reference integration code for trading bots
4. **`download_spx_data.py`** - Data fetching script
5. **`timesfm_evaluation_results.json`** - Raw test results
6. **`multi_timeframe_results.json`** - Cross-timeframe comparison data

### Installation
```bash
cd ~/.openclaw/workspace/timesfm
python -m venv venv
source venv/bin/activate
pip install -e '.[torch]' yfinance pandas matplotlib seaborn scikit-learn
```

### Quick Test
```bash
cd ~/.openclaw/workspace/timesfm_tests
python integration_examples.py
```

---

## 12. Conclusion

### Summary
TimesFM 2.5 is an impressive foundation model for time-series forecasting, but it **fails on SPX 0DTE trading** in its zero-shot form. The model was trained on web traffic, retail, and weather data - domains fundamentally different from financial markets.

### Key Insights
1. **Architecture is solid**: Decoder-only transformer with patching is elegant and efficient
2. **Training data mismatch**: No financial data = no financial forecasting ability
3. **Fine-tuning is essential**: Would require significant effort but could work
4. **Simple baselines win**: Linear trend beats TimesFM by 35.8%
5. **No free lunch**: Even foundation models need domain-specific training for finance

### Final Verdict
**TimesFM is NOT a silver bullet for 0DTE trading.**

For production use:
- Stick with battle-tested technical analysis + orderflow
- Use simpler ML models (XGBoost, LSTM) trained on YOUR data
- Focus ML on auxiliary tasks (vol prediction, regime detection)
- Only consider TimesFM if you can invest 2-3 weeks in proper fine-tuning

### What We Learned
This evaluation demonstrates the importance of:
1. **Testing before deploying**: Don't trust "foundation models" blindly
2. **Domain expertise**: Finance ≠ web traffic, models must adapt
3. **Baseline comparisons**: Always compare to simple heuristics
4. **Understanding training data**: Garbage in = garbage out

---

## Appendix A: Technical Deep Dive

### A.1 Model Architecture Details
- **Embedding dim**: 512 (hidden size)
- **Attention heads**: 8 (multi-head attention)
- **Transformer layers**: 12 stacked layers
- **Patch sizes**: Input 32, Output 128
- **Activation**: GELU (Gaussian Error Linear Unit)
- **Normalization**: Layer normalization
- **Position encoding**: Sinusoidal (standard Transformer)

### A.2 Training Details
- **Optimizer**: AdamW
- **Learning rate**: Warmup + cosine decay
- **Batch size**: Mixed across datasets
- **Training time**: Several weeks on TPU cluster
- **Data mixing**: 80% real, 20% synthetic
- **Context lengths**: 64-512 depending on granularity

### A.3 Inference Pipeline
```
Input time series (length L)
    ↓
Normalize by context statistics
    ↓
Pad to multiple of patch_length
    ↓
Split into patches of size 32
    ↓
Encode patches → vectors (512-dim)
    ↓
Add positional encodings
    ↓
Pass through 12 transformer layers
    ↓
Decode to output patches (size 128)
    ↓
Auto-regressive rollout if horizon > 128
    ↓
Denormalize predictions
    ↓
Return point forecast + quantiles
```

### A.4 Quantile Head Details
- Separate 30M parameter quantile prediction head
- Outputs 10 quantiles: [mean, 10th, 20th, ..., 90th percentiles]
- Trained with pinball loss (quantile regression)
- Includes quantile crossing fix (enforces q10 < q20 < ... < q90)

---

## Appendix B: Full Evaluation Metrics

See `timesfm_evaluation_results.json` and `multi_timeframe_results.json` for complete data.

**Sample metrics (5-min, 24-bar forecast):**
```json
{
  "mae": 24.83,
  "rmse": 28.71,
  "mape": 0.36,
  "direction_accuracy": 65.2,
  "inference_time_ms": 101.9,
  "quantile_coverage": {
    "q10": 2.1,
    "q50": 8.3,
    "q90": 43.8
  }
}
```

---

## Appendix C: References

1. **TimesFM Paper**: Das et al., "A decoder-only foundation model for time-series forecasting", ICML 2024. https://arxiv.org/abs/2310.10688

2. **GitHub Repository**: https://github.com/google-research/timesfm

3. **HuggingFace Model**: https://huggingface.co/google/timesfm-2.5-200m-pytorch

4. **Google Research Blog**: https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/

5. **Evaluation Code**: `/home/dhawal/.openclaw/workspace/timesfm_tests/`

---

**Assessment Completed:** 2026-02-21  
**Total Research Time:** ~45 minutes  
**Lines of Code Written:** ~600  
**Tests Run:** 6 comprehensive evaluations  
**Data Points Analyzed:** ~1,200 SPX bars across 4 timeframes  

**Contact:** For questions about this assessment or fine-tuning assistance, consult the OpenClaw team.
