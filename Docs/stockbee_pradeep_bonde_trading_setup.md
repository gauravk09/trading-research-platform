# Pradeep Bonde (Stockbee) — Trading Setup Reference

> **Pradeep Bonde** (aka "Stockbee") — veteran US-market swing/momentum trader, founder of the Stockbee community, and mentor to traders including Kristjan Kullamägi (Qullamaggie). Former head of marketing for DHL and FedEx in India; transitioned to full-time trading in the early 2000s. Known for the "hitting singles" philosophy — compounding many small, high-probability gains rather than chasing home runs.
>
> Primary sources:
> - https://stockbee.blogspot.com/2014/01/how-to-identify-good-momentum-burst-and.html
> - https://stockbee.blogspot.com/2017/07/my-process-loop-to-trade-4-bo-and-bo.html
> - https://qullamaggie.net/stockbees-momentum-burst/ (faithful transcription of Bonde's own momentum burst guidelines)
> - https://retailtradersrepository.substack.com/p/pradeep-bonde-episodic-pivots (2024 TraderLion talk recap)
> - https://retailtradersrepository.substack.com/p/pradeep-bonde-momentum-bursts (2024 TraderLion talk recap)

---

## Overview

Bonde's edge is built on one structural observation: stocks do not trend smoothly — they move in sharp, short **"momentum bursts"** of 3 to 5 days, gaining 8–40% during that window before stalling for weeks or months. His entire approach is designed to capture only the explosive part of the move and stay out of the dead periods in between.

He runs two main families of setups:

1. **Momentum Burst** (the high-frequency "bread and butter" — pattern + probability based, no catalyst required)
2. **Episodic Pivot (EP)** (lower-frequency, catalyst-driven, aiming for much larger moves)

Both are gamed around the same core belief: enter at the *start* of a swing (range expansion off a quiet base), never chase an extended move, and cut losers ruthlessly because the move should work almost immediately.

A note on credibility: Bonde's track record is communicated through community testimonials rather than an independently audited record (unlike, say, Peter Brandt). The framework is widely respected and his most famous student has a verified championship record, but treat the performance claims accordingly.

---

## Universal Rules (Apply to All Setups)

| Rule | Value |
|------|-------|
| Hold period | 3 to 5 days, counted **from the breakout day itself** |
| Typical move captured | 5–8% per trade (you only get part of the full 8–20% burst) |
| Trade frequency required | 200–1,000+ trades/year; this is a high-frequency, low-per-trade method |
| Core risk rule | Cut the loss immediately if the trade doesn't work right away |
| Market filter | Only buy breakouts when market breadth supports it ("Situational Awareness") |

**Position sizing:** Bonde teaches detailed position sizing and risk-per-trade on his members' site but does not publish exact percentages publicly. Confirmed principles only: he scales aggressiveness up in healthy breadth environments and down (or to cash) when breakouts are failing; he warns that buying extended stocks demands "extremely good risk control and position sizing." Exact % of account per trade and max exposure are **not publicly documented.**

**The "FFM" rule — Find Free Money:** Use situational awareness to only press hard when conditions hand you easy money; otherwise stand aside. The biggest destroyer of momentum-burst traders is getting "chopped" — death by a thousand small losses from trading breakouts in the wrong environment.

---

## Setup 1 — Momentum Burst (4% Breakout / $ Breakout)

**Type:** Swing trade · Daily chart · His most frequent, "bread and butter" setup · No catalyst required

### The scan (range-expansion net)

The literal 4% breakout scan he uses:

```
c/c1 >= 1.04  AND  v > v1  AND  v >= 100000
```

In words: today's close is up **4%+** vs. yesterday's close, **volume is greater than the prior day**, and volume is at least **100,000 shares**. For higher-priced stocks that move in dollar terms rather than percent, he runs a parallel **"$ breakout"** scan to catch range expansion that may not register as a 4% move.

The scan deliberately throws a **wide net** — a 4% breakout is *not* an automatic buy. Roughly **95%+ of scan hits get eliminated** by the selection filters below.

### Prerequisites (the stock must meet ALL of these before you consider entry)

Bonde's selection checklist — summarized by his "2Lynch" mnemonic plus his written guidelines:

- **Not up 2–3 days in a row** ("2"). If it's already run 3 days, the burst has started and you've missed the low-risk entry.
- **Linearity** ("L"). The prior uptrend traded smoothly and linearly — not choppy, not full of shakeouts.
- **Negative or Narrow day before breakout** ("N"). The day *before* the breakout should be a down day or a very narrow-range day — proof the stock wasn't already expanding.
- **Quality consolidation** ("C"). An orderly, low-volatility, volatility-contraction base — ideally **5 to 10 days**, preferably under 10 days. Buyer/seller in equilibrium.
- **Closes near the high** ("H") on the breakout day. If buying intraday (e.g., 10am), it should still be closing strong.
- **Range expansion on breakout day** — the breakout bar is bigger than the prior 3–5 (ideally 5–10) days' bars.
- **Volume on breakout day > prior day.**
- **Young trend.** First, second, or third breakout out of a 3–6 month base is ideal. Avoid breakouts on stocks already extended 6+ months near all-time highs — failure probability rises as trends extend.

**Long-consolidation variant ("2Lynch + CV"):** if the base is longer than ~1 month, require two extra conditions — a **Catalyst** (long bases tend to fail without one) and a **Volume** surge of **1.5–2× the 50-day average volume.**

### Vehicle selection (what kind of stock)

- **High-priced stocks (>$100):** smoother, less volatile moves — Bonde's personal preference for a large account.
- **Small-cap (<$1B), sector-specific:** biggest moves come from **Biotech, Technology, and Consumer Discretionary.**
- General tendencies for bigger bursts: **lower price, lower market cap, lower float, higher short interest.** Most big-move stocks are **$10B market cap and under.**

### Entry Rule

- Enter **on the first day of range expansion**, intraday, as soon as the stock shows up in the scan and meets the selection criteria. He runs the scan throughout the day and buys candidates as they trigger.
- Alternative: **Anticipation** — buy *before* the breakout by pre-building a watchlist of stocks in tight range-contraction, then entering as range expansion begins. This gets a better entry price and captures more of the breakout-day move (which you otherwise miss, since the stock may already be up 4–10% by the time it triggers the scan).

### Stop Loss

- Hard rule: **if it doesn't work almost immediately, cut it.** The setup is predicated on instant follow-through, so a failure to follow through is itself the exit signal.
- Exact stop placement (e.g., breakout-day low vs. a fixed %) is taught on his members' site via video and is **not precisely documented in public text.** Common community practice derived from his teaching is a stop below the breakout-day low or the low of the consolidation, kept tight. *(Flagged as community interpretation, not a confirmed published number.)*

### Partial Exit / Riding the Winner

- He **exits on the 3rd to 5th day** from breakout, OR scales out — selling a partial position into strength and trailing the remainder.
- Key discipline: **sell into the explosive phase, while strength is still there** — do not wait for the reversal. The 3rd day is when novices pile in; professionals sell into that euphoria.

### Full Exit

- By the end of the 3–5 day window regardless, because momentum typically dies after that and the stock often gives back the entire burst gain (sometimes intraday).

### Expected Return

- ~**5–8% average per trade** (capturing part of a full 8–20% burst). Edge comes from frequency and compounding, not per-trade size.

---

## Setup 2 — Episodic Pivot (EP)

**Type:** Swing trade · Catalyst-driven · Lower frequency, much larger target moves

An **Episodic Pivot** is a stock that gaps significantly on a catalyst-worthy event that forces the market to completely re-rate it. The goal here is the opposite of momentum bursts — a *few big trades* that move the account meaningfully. Bonde splits these into "Real" catalysts and "Story" catalysts.

### "Real" EP criteria — the **MAGNA53 + Cap10·10IPO** checklist

**MAGNA is required; 53 adds conviction; Cap10·10 adds explosiveness:**

- **MA** — *Massive Acceleration* in profit growth (double/triple-digit, or a huge beat vs. analyst expectations).
- **G** — *Gap up* (a genuine surprise should gap the stock).
- **N** — *Neglected* — no recent news flow, little analyst coverage, low mutual-fund ownership. The longer the neglect (months to years), the bigger the potential swing.
- **A** — *Acceleration in sales growth* (revenue can't be financially engineered the way EPS can; he weights **sales > earnings**). Any sales growth **above ~39%** on consecutive reports has a high probability of a big move.
- **5** — Short interest of **5 days or more** (to cover).
- **3** — **3+ analysts** raising price targets.
- **Cap10** — small market cap (he looks roughly in the **$10M–$100M** range for the biggest moves).
- **10IPO** — IPO'd within the **last 10 years** (most big moves happen in a company's first decade).

Two flavors of Real EP:
- **Growth type** — clean accelerating fundamentals (example he cited: CRDO).
- **Turnaround type** — a beaten-down, neglected name that surprises; these often run **bigger and longer** than growth EPs (example: ANF).

### "Story" EPs

Catalyst is a narrative/theme rather than hard numbers (e.g., the AI theme, example ACHR). Lower conviction than a "real" EP because there are no tangible numbers backing it, but story stocks can move *further* than fundamentally-backed ones.

### Entry Rule

- If criteria are met, **enter at the open.**
- Or **wait a few minutes** to see how the market digests the news (there are shakeouts near the open).
- Or play a **Delayed Reaction** — enter a day or more later, when he doesn't trust the first-day move.
- A strong enough catalyst makes it a **"Must-Buy"** (his SMCI example, Jan 2024); a weaker one he'll play as a delayed reaction (his SRPT example).
- Mnemonic for when to do the work: **"NTRT, MTRT"** — Night Time is Right Time, Morning Time is Right Time (scanning happens pre/post-market).

### Stop Loss

- Normally a **2.5% stop** at entry.
- If stopped but he still has conviction in the catalyst, he will **re-enter.**
- If the stock **hesitates** right after entry (no strong buying pressure near the open), he often just closes it.
- For an expected triple-digit move, he'll tolerate a **wider ~10% stop**, because the reward is a large multiple of that risk.

### Exit Rule

- He sets an **approximate profit target based on catalyst strength and past experience**, and is patient: if he expects a 60–70% move, he won't rush to exit at +30%.

### Expected Frequency & Win Rate

- **Good market:** ~70% win rate; ~10–12 "Classic" EPs per year.
- **Choppy/bad market:** lucky to get 3–4 Classic EPs per year.

### EP Sub-Variations

- **Stocks in Play** — pure intraday/day-trade plays where liquidity dries up after day one.
- **Delayed Reaction** — enter a day after the catalyst; works especially well on the short side (negative-catalyst gap-downs that reverse intraday then drift lower after 3–4 days once "news is priced in").
- **9 Million EP** — his current main EP workhorse. A neglected, low-volume stock that suddenly surges on **9 million+ shares** of volume, usually with a story/narrative. Expects **100–300 trades/year** on these (example: GME).
- **Sugar Babies** — a string of repeated 9-Million-EP bursts in the same name producing 40–50% moves in just a few days (example: MARA).

---

## Setup 3 — Short / Bearish Setups (Breakdowns & Exhaustion)

**Type:** Swing trade · Daily chart · 3–5 day holds on the **short** side · For bearish/correcting markets only

Bonde's short side is the mirror image of his long side: the same momentum-burst structure runs in reverse. During established downtrends, stocks fall in sharp **3–5 day bearish bursts**, and he harvests them with breakdown and exhaustion scans. He stresses these are *not* all-weather setups — they only work when the broader market is genuinely weak.

> **Critical market filter (non-negotiable):** Only trade shorts when a downtrend is **clearly established on a 10-plus-day timeframe**, or during a fast/selling correction. In a bull market, 3-day bearish setups produce mostly failed breakdowns and short squeezes, because the market's structural positive bias works against you. There are simply more bullish bursts than bearish ones over time.

### Where the opportunities come from (two buckets)

During a market correction, Bonde hunts shorts at **both ends** of the prior rally:

1. **Rally leaders that ran up too far** — the strongest 30-day gainers. In a broad correction these get hit hardest, often correcting **20–25%**. You short them via **buyer-exhaustion** or breakdown.
2. **Laggards that underperformed the rally** — weak stocks that never participated; they tend to **break down first** as the market rolls over.

His process: build a "Rally Leaders" watchlist (top 100–200 stocks by % gain over the rally window, after filtering out sub-$5 and illiquid names), then run a breakdown or exhaustion scan against that list to narrow ~100 names down to **5–6 actionable shorts**.

### The scans (Bonde's own formulas)

**4% Breakdown scan** (bearish mirror of the 4% breakout):

```
C <= .96 * C1  AND  V >= 1000  AND  V > V1
```

In words: today's close is **down 4%+** vs. yesterday's close, volume is meaningful (the `V >= 1000` term is in Telechart's hundreds-of-shares units, i.e. ≥100,000 shares), and **volume is greater than the prior day** — a down-move on expanding volume.

**$ Breakdown scan** — the dollar-move equivalent for higher-priced stocks whose breakdown may not register as a clean 4% drop.

**Swing Exhaustion scan** (for shorting extended rally leaders — finds a stock that ran up several green days and just printed its first down day):

```
C < C1  AND  C1 > C2  AND  C2 > C3  AND  C1 > O1  AND  C2 > O2  AND  C3 > O3
```

In words: the stock closed up (close > open) for **three consecutive days**, then today closed **lower** than yesterday — the first crack after an exhausted run-up.

### Prerequisites (the ideal "weak structure" short)

The cleanest breakdown short Bonde describes: a stock that had **3 down days in a row**, then a **small pause / weak bounce**, and then **broke down again** (showing up on the 4% breakdown scan). The pause that fails to recover is the tell — it confirms sellers remain in control rather than a genuine reversal. Look for:

- A clearly established downtrend or a hard market correction underway.
- Breakdown happening on **volume greater than the prior day** (institutional selling).
- A failed bounce / weak structure rather than a stock still holding key support — wait for the **confirmed** break, not the anticipation of one, to avoid squeezes.

### Entry Rule

- Enter **on the breakdown day** as the stock triggers the 4% / $ breakdown scan (the bearish equivalent of buying first-day range expansion).
- For exhaustion shorts, enter as the first down day confirms the run-up has stalled.

### Stop Loss

- Same discipline as the long side, inverted: **cut immediately if it doesn't follow through.** A breakdown that quickly reclaims its level is a failed short — exit. Exact stop level (e.g., above the pause-day high or the breakdown candle's high) is taught on his members' site and is **not precisely published**; community practice places the stop just above the breakdown bar / recent swing high, kept tight.

### Exit / Cover

- Same **3–5 day** burst window as the long side, in reverse — cover into the downside follow-through while it's still falling; don't wait for the reversal back up.
- On a deep market correction, individual leaders can offer **10–25%** down-moves, but the default is to bank the 3–5 day burst.

### Notes & Caveats

- **Delayed Reaction shorts** (from the EP section) also live here: a negative catalyst gaps a stock down, it reverses *up* intraday, and then — once traders assume the "news is priced in" after 3–4 days — it **drifts lower again.** That delayed drift is the short.
- Shorting carries asymmetric risk (unlimited upside loss, hard-to-borrow names, squeeze risk). Bonde's repeated message: shorting is a **specialist, market-condition-dependent** activity, secondary to the long book given the market's long-term upward bias.

---

## Situational Awareness (the market filter that makes both setups work)

Every morning Bonde tries to answer **one question: "Are breakouts likely to work today?"**

- He uses his **Market Monitor (MM)** — a breadth dashboard tracking market-wide buying vs. selling pressure. **Mostly green columns → good time to buy breakouts. Any of the first few columns red → expect chop; trade light or stand aside.**
- He layers a **TC2000 market-strength indicator** and constantly tracks **which themes and sectors are leading.**
- This is purely an on/off + aggressiveness filter. Without it, traders buy breakouts in all conditions, get chopped, lose discipline, and blow up.

---

## Summary Cheat Sheet

| | Momentum Burst (long) | Episodic Pivot | Short / Breakdown |
|---|---|---|---|
| **Frequency** | Very high (200–1,000+ trades/yr) | Low (10–12 classic/yr in good markets) | Only in corrections/bear phases |
| **Catalyst needed?** | No | Yes (real numbers or a story/theme) | No (or a negative catalyst) |
| **Scan / trigger** | `c/c1>=1.04 and v>v1 and v>=100000` off a tight 5–10 day base | Gap-up on MAGNA53-type catalyst | `C<=.96*C1 and v>v1 and v>=100000` (4% breakdown); or swing-exhaustion scan |
| **Entry** | First day of range expansion, intraday | At the open (or wait / delayed reaction) | On the breakdown day / first down day after exhausted run-up |
| **Stop** | Tight; cut on no immediate follow-through (exact level taught privately) | 2.5% normal; up to ~10% for expected triple-digit movers | Tight, above breakdown bar / swing high; cut if it reclaims |
| **Hold / exit** | 3–5 days from breakout; sell into strength | Hold to a catalyst-based profit target; patient | 3–5 day burst; cover into the decline |
| **Target per trade** | ~5–8% (slice of an 8–20% burst) | Large (30% to triple-digit) | 3–5 day burst; leaders can drop 10–25% |
| **Win rate** | High via probability + frequency | ~70% in good markets | Condition-dependent; squeeze-prone in bull markets |
| **Market regime** | Healthy/green breadth | Any (catalyst-driven) | **Established downtrend (10+ day) only** |

---

## Core Philosophy

- **Stocks move in 3–5 day momentum bursts — this is structural and has held for 100+ years.** Build your trading around capturing that impulse, not around holding through dead time.
- **Always buy range expansion at the *beginning* of a swing.** Never chase a stock up 3 days in a row — the third-day buyer becomes the bag holder.
- **Hit singles.** Compound many small, low-risk gains. Frequency and discipline beat swinging for the fences.
- **Cut losers instantly.** The setup must work almost immediately; if it doesn't, the thesis is wrong — exit.
- **Sell into strength, not reversal.** Exit while the move is still explosive; don't give back the burst.
- **Situational awareness is the master switch.** Only press when breadth says breakouts are working. Avoiding chop is most of the edge.
- **Copy shamelessly, then adapt.** 80% of new traders have no defined setup. Borrow a proven one (like actors imitating before finding their own style), then make it yours.
- **Deep dive before risking a dollar.** Study thousands of past breakouts/EPs to internalize the pattern — books alone won't build an edge.
- **Self-leadership.** This work requires self-motivation; it isn't for everyone.

---

*Sources researched: stockbee.blogspot.com (momentum burst, process loop, stop & exit posts, "How to find shorts" and "How to find shorts opportunities Part 1" with the 4% breakdown and swing-exhaustion scans), qullamaggie.net/stockbees-momentum-burst, retailtradersrepository.substack.com (2024 TraderLion EP and Momentum Burst recaps), trendsandbreakouts.com, grokipedia.com/page/Pradeep_Bonde*
*Last updated: June 13, 2026*

> Note: The provided YouTube link (youtube.com/watch?v=40HtmiuyocE) could not be fetched directly (rate-limited), so this reference is compiled from Bonde's own blog and transcribed guidelines plus faithful recaps of his 2024 TraderLion presentation. Exact public position-sizing percentages and the precise momentum-burst stop level are taught on his paid members' site and are flagged above where not publicly documented.
