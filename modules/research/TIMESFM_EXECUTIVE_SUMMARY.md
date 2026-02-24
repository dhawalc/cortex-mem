# TimesFM 2.5 for SPX 0DTE Trading - Executive Summary

**Date:** 2026-02-21  
**Bottom Line:** ❌ **NOT RECOMMENDED** for zero-shot deployment

---

## TL;DR

Google's TimesFM 2.5, while impressive as a general-purpose time-series foundation model, **performs poorly on SPX intraday trading** without fine-tuning:

- ❌ **50% directional accuracy** (random guessing)
- ❌ **35.8% worse** than simple linear trend
- ❌ **Miscalibrated uncertainty** estimates
- ❌ **Not trained on financial data**

**Verdict:** Do NOT use zero-shot. Fine-tuning required (2-3 weeks, $500-1000 GPU costs).

---

## Key Findings

### ✅ What Works
- Architecture is solid (decoder-only transformer)
- Fast inference (~100ms after warmup)
- Provides quantile forecasts
- Handles variable context/horizon lengths
- Reasonable resource requirements (200M params)

### ❌ What Doesn't Work
- Zero-shot forecasting on SPX (no edge)
- Direction prediction (50% = coin flip)
- Volatility forecasting (overestimates by 4x)
- Quantile calibration (severely off)
- Intraday patterns (worse on 1-min than daily)

---

## Performance Summary

| Metric | Result | Baseline | Status |
|--------|--------|----------|--------|
| Direction accuracy (5-min) | 53.2% | 50% | ❌ No edge |
| MAE vs last-value | $27.49 | $24.17 | ❌ +13.7% worse |
| MAE vs linear trend | $24.83 | $18.28 | ❌ +35.8% worse |
| Trading simulation | 50% correct | 50% | ❌ Random |
| Inference time | ~100ms | <1ms (baseline) | ⚠️ Acceptable |

---

## Why It Fails

**Training Data Mismatch:**
- Trained on: Google Trends, Wikipedia pageviews, weather, retail
- Needs: Financial market microstructure, orderflow, regime dynamics

**Financial markets are different:**
- Non-stationary (regime changes)
- Fat-tailed distributions (black swans)
- Weak autocorrelation (efficient markets)
- High noise (tick-level chaos)

---

## Recommendations

### Immediate (Do NOT):
- ❌ Do NOT deploy zero-shot TimesFM in production
- ❌ Do NOT rely on quantile forecasts for risk management
- ❌ Do NOT expect trading edge without fine-tuning

### Short-term (Next 2 weeks):
- ✅ Stick with proven technical indicators
- ✅ Enhance orderflow/volume analysis
- ✅ Use simple ML for regime classification
- ✅ Improve risk management (dynamic stops)

### Medium-term (1-2 months):
- Consider XGBoost/LightGBM on engineered features
- Build custom LSTM on YOUR proprietary data
- Focus on volatility prediction (easier than price)
- Ensemble multiple simple models

### Long-term (3-6 months, if resources allow):
- Fine-tune TimesFM on 3-5 years SPX data
- Requires GPU cluster (A100) and 2-3 weeks
- Use as ONE signal (30% weight), not sole decision
- Extensive validation required before production

---

## Cost-Benefit Analysis

### Fine-Tuning Investment
- **Time:** 2-3 weeks
- **Cost:** $500-1,000 (GPU hours)
- **Risk:** May not improve over simpler models
- **Benefit:** Potential edge IF successful

### Alternative: Simple ML
- **Time:** 1-2 weeks
- **Cost:** <$100 (CPU sufficient)
- **Risk:** Lower (well-understood methods)
- **Benefit:** Proven track record in finance

**Recommendation:** Try simple ML first, then consider TimesFM if you have spare resources.

---

## Integration Strategy (IF You Fine-Tune)

```
Trading Signal = 
  60% Traditional (RSI, MACD, volume) +
  30% TimesFM (direction, volatility) +
  10% Risk (quantile-based position sizing)
```

**Never use ML as sole decision maker!**

---

## Files & Code

All evaluation artifacts in: `/home/dhawal/.openclaw/workspace/timesfm_tests/`

**Key files:**
- `TIMESFM_TECHNICAL_ASSESSMENT.md` - Full 20-page technical report
- `comprehensive_evaluation.py` - Complete test suite
- `integration_examples.py` - Reference integration code
- `timesfm_evaluation_results.json` - Raw metrics
- `multi_timeframe_results.json` - Cross-timeframe comparison

**Run tests:**
```bash
cd ~/.openclaw/workspace/timesfm_tests
source ../timesfm/venv/bin/activate
python comprehensive_evaluation.py  # Full evaluation (~2 min)
python integration_examples.py      # Integration demo
```

---

## Alternative Approaches

| Approach | Effort | Cost | Proven? | Recommended? |
|----------|--------|------|---------|--------------|
| Technical indicators | Low | Free | ✅ Yes | ✅ Start here |
| XGBoost/LightGBM | Medium | <$100 | ✅ Yes | ✅ Yes |
| Custom LSTM | Medium | $100-300 | ⚠️ Mixed | ⚠️ Maybe |
| Fine-tune TimesFM | High | $500-1000 | ❌ Unproven | ⚠️ Low priority |
| GPT-4 forecasting | Very High | $1000+ | ❌ Poor results | ❌ No |

---

## Questions & Next Steps

### If you want to proceed with TimesFM:
1. Collect 3-5 years of high-quality intraday data
2. Set up GPU cluster (A100 recommended)
3. Fine-tune for 2-3 weeks with careful validation
4. Backtest extensively before paper trading
5. Start with small position sizes

### If you want better alternatives:
1. Read: "Advances in Financial Machine Learning" by Marcos López de Prado
2. Try: Feature engineering + XGBoost on your data
3. Focus: Regime classification, not pure price prediction
4. Remember: In trading, simple often beats complex

---

## Contact & Resources

**Full technical assessment:** `TIMESFM_TECHNICAL_ASSESSMENT.md`  
**Paper:** https://arxiv.org/abs/2310.10688  
**Code:** https://github.com/google-research/timesfm  
**Model:** https://huggingface.co/google/timesfm-2.5-200m-pytorch

**Assessment by:** OpenClaw AI Research  
**Date:** February 21, 2026  
**Research time:** ~1 hour (thorough hands-on evaluation)

---

## One-Line Summary

**TimesFM is an impressive foundation model, but stick with traditional technical analysis for 0DTE trading until you can invest 2-3 weeks in proper fine-tuning on market data.**

🎯 **Actionable takeaway:** Don't chase shiny ML models. Master the basics first!
