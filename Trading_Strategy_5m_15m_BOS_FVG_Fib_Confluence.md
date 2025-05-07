# Systematic Trading Strategy: 5m/15m BOS/FVG/Fib Confluence - $1 Fixed Risk

**Last Updated:** May 7, 2025

## 1. Overview

This document outlines a systematic, high-frequency intraday trading strategy designed for top cryptocurrency futures on Centralized Exchanges (CEXs). The strategy aims to identify high-probability entry points by looking for a confluence of Break of Structure (BOS), Fair Value Gap (FVG) filling, and Fibonacci retracement levels. It employs a strict $1 fixed dollar risk per trade, utilizing maximum leverage for margin efficiency on a precisely calculated position size.

**Trading Style:** Intraday / Scalping
**Primary Instruments:** Top 5-10 Crypto Futures (e.g., BTCUSDT, ETHUSDT, SOLUSDT)
**Execution Timeframe:** 5-minute chart
**Contextual Timeframe:** 15-minute chart

## 2. Core Concepts

* **Market Structure (BOS - Break of Structure):**
    * **Bullish BOS:** A clear, impulsive price move that closes above a significant recent swing high. Indicates potential continuation of buying pressure.
    * **Bearish BOS:** A clear, impulsive price move that closes below a significant recent swing low. Indicates potential continuation of selling pressure.
* **Impulsive Move:** A strong, fast price movement in one direction, often characterized by large-bodied candles, that causes the BOS.
* **Retracement (Pullback):** A temporary counter-move in price after an impulsive move, before potentially resuming the original direction.
* **Fair Value Gap (FVG):** A three-candle pattern indicating an imbalance or inefficiency in price delivery.
    * **Bullish FVG:** The space between the high of the first candle and the low of the third candle, where the second candle is a strong bullish candle. Price often revisits this gap to mitigate it.
    * **Bearish FVG:** The space between the low of the first candle and the high of the third candle, where the second candle is a strong bearish candle.
* **Fibonacci Retracement:** A tool drawn on the impulsive move (from its start to its end after the BOS) to identify potential support (in an uptrend) or resistance (in a downtrend) levels where the retracement might end. Key levels: 0.50 (50%), 0.618 (61.8% - Golden Ratio), 0.786 (78.6%). The "Golden Pocket" is often considered the 0.618-0.650 zone.
* **Point of Interest (POI) / Confluence:** A price zone where multiple technical signals align, increasing the probability of a reaction. For this strategy, it's typically where an FVG overlaps with a key Fibonacci level and the retest of the previously broken structure.

## 3. Operational Parameters

* **Execution Timeframe:** 5-minute chart (for identifying entry signals, fine-tuning FVGs, and placing SL/TP).
* **Contextual Timeframe:** 15-minute chart (to identify broader intraday trends, more significant swing points for BOS, larger FVGs, and drawing Fibonacci levels for the POI).
* **Instruments:** Top 5-10 cryptocurrencies by trading volume and liquidity on your chosen CEX futures market.
* **Leverage:** Maximum leverage allowed by the CEX for each specific trading pair. This is used for margin efficiency; the actual risk is controlled by the position size based on the $1 fixed risk.
* **Risk Per Trade:** Strictly **$1 (one US dollar)** fixed monetary risk if the stop-loss is triggered.

## 4. Systematic Trading Plan

### Phase 1: Pre-Trade Analysis & Setup Identification (15m Context)

* **Step 1.1: Determine 15m Contextual Bias & Structure (BOS)**
    * Identify the prevailing trend on the 15-minute chart (e.g., series of higher highs and higher lows for bullish bias).
    * Wait for a clear impulsive move on the 15m chart that results in a Break of Structure (BOS) – a close above a recent significant 15m swing high for a long setup, or below a 15m swing low for a short setup.
* **Step 1.2: Identify Key 15m Levels from the Impulsive Move**
    * After the 15m BOS, draw a Fibonacci retracement tool from the start (swing low/high) of the impulsive leg to the end (new swing high/low created by the BOS).
    * Identify any clear 15m Fair Value Gaps (FVGs) that were created during this impulsive leg.
* **Step 1.3: Define 15m Point of Interest (POI)**
    * The POI is the zone where you anticipate price retracing to before potentially continuing in the direction of the BOS.
    * Look for a confluence:
        1.  A key Fibonacci retracement level (0.50, 0.618, 0.786).
        2.  A 15m FVG that aligns with or is near one of these Fib levels.
        3.  The area around the previously broken 15m swing high (now potential support for longs) or swing low (now potential resistance for shorts).

### Phase 2: Entry Execution (5m Execution)

* **Step 2.1: Monitor Price Approaching 15m POI on 5m Chart**
    * Once price begins to retrace towards the identified 15m POI, switch focus to the 5-minute chart for entry signals.
* **Step 2.2: Entry Triggers (Long Example - reverse for shorts)**
    * **Option A: FVG Entry on 5m:**
        * Price enters the 15m POI and mitigates (touches or enters) a clear FVG visible on the 5-minute chart (this could be the refined view of a 15m FVG or a distinct 5m FVG formed within the POI).
        * Enter LONG when the 5m candle shows rejection from the FVG (e.g., wicks into it and closes bullishly, or the next candle confirms bullish momentum away from the FVG).
    * **Option B: 5m Market Structure Shift (MSS)/BOS Confirmation:**
        * Price enters the 15m POI and initially respects it.
        * Wait for a *miniature* Break of Structure on the 5-minute chart in the direction of the 15m bias (e.g., for a long, price takes out a recent 5m swing high that formed during the retracement into the POI).
        * Enter LONG on the retest of this broken 5m structure or a new 5m FVG formed during this 5m MSS.

### Phase 3: Stop-Loss (SL) Placement (based on 5m structure)

* **Step 3.1: Logic and Systematic Rules**
    * The SL must be placed at a level that, if breached, clearly invalidates the reason for the 5-minute entry.
    * **For Longs:** Place the SL a few ticks (or a small, predefined price increment suitable for the asset, e.g., $10-20 for BTC, $1-2 for ETH) *below*:
        * The low of the 5-minute FVG that was mitigated for entry.
        * The 5-minute swing low that formed just before the confirmatory 5m MSS/BOS.
        * The low of the 5m candle that wicked into the 15m POI and showed strong rejection.
    * Ensure the SL is beyond the immediate 5-minute structural point.

### Phase 4: Take-Profit (TP) Placement (based on 5m risk & 15m/5m structure)

* **Step 4.1: Options**
    * **Option A: Fixed Risk:Reward Ratio (R:R) - Recommended for System Consistency**
        * **TP1:** Set at a 1:2 risk-to-reward ratio (e.g., if SL is 20 points from entry, TP is 40 points).
        * **TP2 (Optional):** Set at a 1:3 or 1:5 R:R. Consider moving SL to breakeven after TP1 is hit.
    * **Option B: Structural Targets**
        * **TP1:** The 15-minute swing high/low that was initially broken by the BOS.
        * **TP2:** The next significant 15-minute or 5-minute resistance/support level.
        * **TP3:** Fibonacci extension levels (-0.272, -0.618, -1.0) of the initial 15-minute impulsive leg, projected from the 5m entry point.

## 5. Risk Management

* **Per Trade: $1 Fixed Dollar Risk:**
    * **Position Size Calculation is CRUCIAL:**
        1.  Determine Entry Price and Stop-Loss Price (from 5m chart analysis).
        2.  Calculate SL Distance in Price: `SL_distance_price = |Entry Price - SL Price|`.
        3.  Obtain Contract Specifications from CEX:
            * Tick Size (minimum price fluctuation).
            * Value per Tick (how much $1 contract changes value per tick).
            * (Alternatively: Contract Size and Value per point movement of the underlying).
        4.  Calculate Risk per Full Contract if SL is Hit: `Risk_per_contract = (SL_distance_price / Tick_Size) * Value_per_Tick`.
        5.  Calculate Number of Contracts for $1 Risk: `Position_Size = $1.00 / Risk_per_contract`.
    * The calculated `Position_Size` is then used with maximum leverage for margin efficiency.
* **Per Session/Day: Daily Loss Limit:**
    * Define a maximum number of consecutive losing trades (e.g., 3-4) OR a maximum total dollar loss for the day (e.g., $3-$4).
    * **If this limit is reached, STOP TRADING for the day. This is non-negotiable.**

## 6. Portfolio Management

* **Number of Concurrent Trades:** Limit to 1-2 active trades to maintain focus and manage risk exposure.
* **Correlated Assets Consideration:** Avoid taking multiple trades in the same direction on highly correlated assets simultaneously. Choose the setup with the clearest confluence.
* **Awareness of Funding Rates & Fees:** Understand how CEX funding rates (typically every 8 hours, but check specifics) and trading fees (maker/taker) will impact net profitability, especially with frequent trades.

## 7. Pre-Trade Checklist (Example for a Long Trade)

1.  [ ] **15m Chart:** Bullish trend bias clear (higher highs/lows)?
2.  [ ] **15m Chart:** Recent, clear BOS above a significant 15m swing high?
3.  [ ] **15m Chart:** Fibonacci drawn on the impulsive leg causing BOS?
4.  [ ] **15m Chart:** Clear FVG(s) identified within the impulsive leg?
5.  [ ] **15m Chart:** POI identified (confluence of Fib level + FVG +/- retest of broken high)?
6.  [ ] **5m Chart:** Price has retraced into the 15m POI?
7.  [ ] **5m Chart:** Valid entry signal triggered (FVG mitigation & reaction, OR 5m MSS/BOS confirmation)?
8.  [ ] **5m Chart:** Stop-Loss level determined based on 5m structure below entry?
9.  [ ] **5m Chart:** Take-Profit level(s) determined (Fixed R:R or structural)?
10. [ ] Position Size calculated for $1 risk based on SL distance?
11. [ ] Within daily loss limits / max concurrent trade limits?
12. [ ] Major news events checked for the asset?

## 8. Disclaimer

Trading cryptocurrency futures, especially on low timeframes with high leverage, carries an **EXTREME LEVEL OF RISK**. This strategy outline is for informational and educational purposes only and does not constitute financial advice. The volatility of cryptocurrencies can lead to rapid and substantial losses. A $1 risk per trade limits individual trade loss but does not prevent accumulated losses from multiple losing trades. Past performance is not indicative of future results. Always conduct your own thorough research, backtest rigorously, and consider paper trading before risking any real capital. Understand the mechanics of leverage, liquidation, and exchange-specific risks. You are solely responsible for your trading decisions.