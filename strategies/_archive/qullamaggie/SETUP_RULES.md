# Qullamaggie Trading Setups — Complete Entry, Exit & Position Sizing Rules

> **Kristjan Kullamägi (Qullamaggie)** — Swedish swing trader who turned $5,000 into $100M+ trading 3 timeless setups.

---

## Universal Position Sizing Rules (All Setups)

| Rule | Value |
|------|-------|
| Position size per trade | 10–20% of account |
| Max overnight in any single stock | ≤ 30% of account |
| Account risk per trade | 0.25–1% |
| Stop width limit | Never wider than 1× ADR (average daily range) |

**Position size formula:**
```
Shares = (Account Size × Risk %) ÷ (Entry Price − Stop Price)
```
*Example: ₹10L account, 1% risk (₹10,000), stop ₹20 below entry → buy 500 shares*

---

## Setup 1 — Breakout from Consolidation

**Type:** Swing trade · Daily chart

### Prerequisites (must have ALL)
- Stock up 30–100%+ in the past 1–3 months
- Consolidation of 2 weeks to 2 months with higher lows and tightening range
- Price "surfing" the rising 10-day and 20-day MA during consolidation
- ADR > 4%
- Stock is in the top 1–2% by 1-month, 3-month, and 6-month return
- **Young trend preferred** (Bonde's 2LYNCH "Y"): 1st–3rd breakout leg since
  the stock's last reset (a ≥25% drawdown) is low-risk; 4th+ leg is "extended"
  — scored as a bonus conviction filter (`trend_stage` / `f_young_trend` in
  `src/indicators/trend_stage.py`), not a hard exclusion, since Bonde treats
  it as a preference rather than a rule

### Exact Entry Trigger
- Buy when stock breaks above the **opening range high**
- Opening range = high of the first 1-min, 5-min, or 60-min candle (9:30–10 AM on 60-min)
- Can also watch the daily chart and enter as the stock starts breaking out
- **Volume must expand:** 1.5× average or more on the breakout day
- Stock must be above the 50-day MA

### Stop Loss
- Initial stop = **low of the day** (day of entry)
- Hard rule: stop cannot be wider than 1× ATR/ADR
  - If ADR is 5%, stop max 5% below entry
  - If ATR is $0.50, stop max $0.50 below entry
- If the stop distance would exceed 1× ADR → **skip the trade entirely**

### Partial Exit — Lock In Profits
- Sell **1/3 to 1/2** of the position after **3–5 days** OR when trade reaches **2–3R profit**
- Immediately move stop on remaining shares to **breakeven**

### Trail Remaining Position
- Trail remaining shares with the **10-day or 20-day MA** on the daily chart
- Use 10-day for faster-moving stocks; 20-day for calmer ones
- Beginners: default to 10-day
- **Exit signal:** first daily CLOSE below the 10-day MA

### Potential Return
- No fixed profit target — let the MA trail decide
- In a bull market: expect **10–20× initial risk** on the best trades

---

## Setup 2 — Episodic Pivot (EP)

**Type:** Intraday + swing · Best risk:reward of all 3 setups · Rarest

### Prerequisites (must have ALL)
- Gap up of **10%+** at open on a major catalyst
  - Catalysts: earnings beat, earnings guidance raise, FDA approval, major news, analyst upgrade, government regulation
- Volume **2× average or more** in the first 15–30 minutes
- Stock was ideally "neglected" before the catalyst — new institutional attention incoming
- Best EPs occur during **earnings season** (4 windows per year, 3–4 weeks each)

### Exact Entry Trigger
- Buy when stock moves above the **early morning high** (opening range breakout)
- Opening range = high of first 5-min or 15-min candle on the catalyst day
- If stock cannot clear the morning high by midday → **skip the trade**
- Alternative: buy on first pullback when price reclaims the morning high on volume

### Stop Loss
- Stop = **low of the catalyst day** (morning low)
- This is the tightest stop of all 3 setups → best risk:reward
- A genuine move should not revisit the morning low
- Still must not exceed 1× ADR

### Partial Exit — Lock In Profits
- Sell **1/3 to 1/2** after **3–5 days** OR at **2–3R profit**
- Move stop on remainder to **breakeven** immediately after the partial sale

### Trail Remaining Position
- Trail with **10-day or 20-day MA** on the daily chart
- Exit on first daily close below the MA
- Institutional buyers accumulate for weeks after a catalyst — ride that wave
- If treated as intraday: exit same day if stock shows hesitation or gaps into resistance

### Potential Return
- No fixed target — best EPs run for weeks or months
- Because stop is so tight: **5–30×+ R:R** on the best setups
- Highest-conviction, lowest-noise setup of the three

---

## Setup 3 — Parabolic Short (or Long)

**Type:** Intraday · Hardest psychologically · Use smaller size

### Prerequisites — Short Side
- Stock has gone vertical (parabolic) in a short period: 100%+ in days or weeks
- Move is clearly unsustainable — near-vertical chart angle
- Often accompanied by a huge gap up or blow-off candle
- Signs of exhaustion: large red candles, long upper wicks, fading volume

### Exact Entry Trigger — Short
- Short when stock shows **first clear sign of reversal**
- = confirmed break below a key intraday support, or first significant red candle after the blow-off top
- Wait for a bearish reversal candle or break below a pivot — **do not anticipate**
- Use **smaller size than normal** — volatility is extreme

### Stop Loss — Short
- Stop = **above the day's high** (or the blow-off top candle high)
- If stock makes a new high after entry → you are wrong → **exit immediately**
- These stocks can run further than anyone expects before reversing

### Partial Exit — Short
- Cover **1/3 to 1/2** after **2–3 days** or at **2–3R profit**
- These moves are fast — parabolic drops happen in 2–4 days
- Take partial profits quickly; trail remainder with intraday or daily structure

### Parabolic Long Variation
- When a parabolic short has dropped **50–60%+** in a few days → sets up for a long bounce
- Entry: opening range highs, or first green 5-min candle, or any range break upward
- These can bounce **50–100% in a few days**
- Same stop rules: below the day's low

### Potential Return
- **5–10× initial risk** on ideal setups
- Lower ceiling than EP, but win rate tends to be higher when patient
- No fixed price target — exit when momentum dies or MA is reclaimed

---

## Summary Cheat Sheet

| | Breakout | Episodic Pivot | Parabolic Short |
|---|---|---|---|
| **Frequency** | Most common | Rarest | Occasional |
| **Entry** | Opening range high breakout | Opening range high on catalyst day | First reversal signal after blow-off |
| **Stop** | Low of day (≤ 1× ADR) | Morning low of catalyst day | Above day's high |
| **Partial sell** | 1/3–1/2 at 3–5 days or 2–3R | 1/3–1/2 at 3–5 days or 2–3R | 1/3–1/2 at 2–3 days or 2–3R |
| **Trail** | 10-day or 20-day MA | 10-day or 20-day MA | Intraday or daily structure |
| **Exit signal** | Close below 10-day MA | Close below 10-day MA | Momentum dies / MA reclaimed |
| **Max R:R** | 10–20×+ | 5–30×+ | 5–10× |
| **Position size** | 10–20% of account | 10–20% of account | Smaller than normal |

---

## Core Philosophy
- **Low win rate is fine** — edge comes from asymmetric risk:reward (5–20× winners vs 1R losers)
- **Cut losers fast** — if price hits your stop, exit with no hesitation
- **Let winners run** — the partial exit + breakeven stop gives a "free ride" on remaining shares
- **Master ONE setup first** before adding the others
- **Scan for leaders:** stocks in top 1–2% by 1-month, 3-month, 6-month performance
- **Never risk more than 1%** of account on a single trade

---

*Source: Qullamaggie.com, YouTube stream "My setups, methodology, and how to build trading mastery" (KciAjkEFA6s)*
