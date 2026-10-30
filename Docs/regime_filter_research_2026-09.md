# Market Regime Filters — Research Survey (2026-09-26)

**Scope:** research only. Nothing is built from this document yet.
**Goal:** decide which market-regime gates are worth testing for our NSE swing strategies (long breakouts and the F&O short), and how to test them honestly.
**Sources:** peer-reviewed papers, practitioners' published rules and tests, and this repo's earlier studies. The repo studies are labelled **UNVERIFIED** throughout: they ran before the Aug-7 harness audit, and the user does not trust the repo's filters.

Evidence labels:
- **[I]** independently tested
- **[B]** backtested only by the method's author
- **[A]** anecdote or practitioner claim
- **[R]** repo result, unverified

---

## 1. Bottom line

1. **A regime filter mainly cuts drawdowns. It rarely adds return.** Index-trend filters roughly halved worst-case drawdowns in century-long tests. CAGR stayed about the same, for example Faber: 10.2% vs 9.3%, max DD 42% vs 84%. Once look-ahead and costs are removed, the return edge over buy-and-hold is statistically nil (Zakamulin 2018) [I].
2. **Momentum and breakout longs do better after the market has been rising.** This is the strongest academic support for gating our kind of trading. It is monthly-horizon evidence, not per-trade 5-day evidence (Cooper et al. 2004; EM replications) [I].
3. **The worst danger is the rebound after a crash, not the bear market itself.** 14 of the 15 worst momentum months came when the market was down over 2 years but rebounding that month (Daniel & Moskowitz 2016) [I]. This matters most for our **short** strategy.
4. **Simple and slow beats complex.** No peer-reviewed study shows an HMM or Markov-switching model beating a 200-day or 10-month moving average out of sample after costs. Many HMM backtests quietly use future data ("smoothed" probabilities) [I].
5. **Breadth (the Stockbee and IBD kind) is what discretionary traders use, but it is barely tested.** One serious cross-country paper supports it (Zaremba et al. 2021); the rest is anecdote. Breadth is good at spotting **bottoms** and lags at **tops**. Bonde says this himself, and Bulkowski found distribution days only "work" once the market is already falling [A/I].
6. **Nobody has published an honest test on NSE.** There is no peer-reviewed or credible practitioner study of a daily regime filter on Indian breakouts. We would be producing the evidence, not copying it.

---

## 2. What a regime filter can and cannot do

| It CAN | It CANNOT (on current evidence) |
|---|---|
| Keep you out of long bear markets (smaller drawdowns) | Reliably make each trade better |
| Cut how often you trade in bad tapes | Call tops early (breadth and distribution days lag) |
| Scale size down when volatility is high | Catch the first leg of a new bull market (slow filters re-enter late) |
| Stop shorts during panic rebounds | Transfer between long and short strategies unchanged |

**What this means for us:** judge a filter by **which trades it removes**. Ask two questions:
- Did the removed trades lose money on average?
- How many winners were removed along with them?

Judging a filter by the Sharpe ratio alone is not enough.

---

## 3. The candidate filter families, ranked by evidence

### A. Index trend switch — strongest evidence, main benefit is drawdown [I]
- **Faber, 10-month SMA** (1901–2012):
  - Invested about 70% of the time, with fewer than one round trip a year.
  - Underperformed in about half of all years, including the 1990s.
- **Clenow:** no new buys while the S&P 500 is below its 200-DMA; existing positions are kept.
- **Bensdorp:** new buys only while SPX is above 0.98 × its 200-day SMA (a 2% band against whipsaw).
- **Antonacci / Alpha Architect:** equities only while the 12-month return is above T-bills. Standard lookbacks, not fitted ones.
- **Weinstein:** index above a *rising* 30-week MA = Stage 2. A 2026 point-in-time test found Stage 2's edge is simply the MA trend [I, abstract only].
- **Radge:** removing the index filter from an ASX momentum system cost about 3%/yr CAGR and allowed drawdowns above 30% [B, snippet]. Some of his systems with tight stops need no filter.
- **Failure modes:**
  - Whipsaw in sideways markets. One comparison of 20 filters found fast filters cost 3–4%/yr.
  - Late re-entry after V-bottoms (2020).
  - Choosing the MA length is itself a form of overfitting. Judge by the **median across parameter values**, not the best one.

### B. Market-state filter for momentum longs [I]
- **Cooper, Gutierrez & Hameed (2004):** state = the market's lagged 36-month return. Momentum earned +0.93%/month after UP states and −0.37%/month after DOWN states (1929–1995).
- **Emerging markets:** 0.29%/month UP vs −0.02% DOWN [source paper not confirmed].
- **Asem & Tian (2010):** momentum suffers most at **transitions** between states.
- **Han, Yang & Zhou (2013):** MA timing adds most on **high-volatility, small-cap** portfolios, which is our breakout universe.
- **Gap:** no peer-reviewed test on Minervini/Qullamaggie-style breakouts specifically.

### C. Crash-state / rebound filter, critical for shorts [I]
- **Daniel & Moskowitz (2016):** crashes come in "panic states": the market is down over 2 years, volatility is high, and the market is rebounding. A dynamic strategy that avoids these states roughly **doubled** Sharpe.
- **Barroso & Santa-Clara (2015):** scaling momentum by its own recent volatility raised Sharpe from 0.53 to 0.97 and "virtually eliminates crashes".
- **Caveat:** Cederburg et al. (2020) tested 103 strategies and found volatility scaling does **not** generalise beyond momentum. It helps for momentum-type strategies, not for everything.
- **For our F&O lone-loser short:** its known drawdown driver is squeeze gap-throughs. That is exactly this panic-rebound mechanism.

### D. Breadth — widely used, thinly tested [A, one I]
- **Stockbee Market Monitor** (published thresholds on a US universe of about 6,000 stocks):
  - 10-day 4% up/down ratio ≥ 2 = long side; ≤ 0.5 = short side; below 1 = breakouts fail.
  - T2108 (% of stocks above their 40-day MA) < 20 = bottoms.
  - Up-25%-in-a-quarter count < 200 = bullish extreme.
  - Bonde's caveat: good at bottoms, "significant time lag" at tops.
- **Our universe is about 2,100 stocks, not 6,000.** Absolute counts (300, 500, 1000, 200) do **not** transfer. Only ratios and percentiles do.
- **India practitioners** use % of Nifty 500 above the 200-DMA: >70% bull, <30% bear, <20% bottoms [A, untested].
- **Zaremba et al. (2021, 64 countries):** high breadth predicts higher next-period returns. But this ranks countries and industries against each other; it is not a timing switch within one market [I].
- **Zweig breadth thrust:** very rare, about 33 occurrences since 1932, and practitioner-only.

### E. IBD follow-through days and distribution days [I, weak]
- **FTD rules:**
  - Day 4 or later of a rally attempt.
  - Index up at least 1–1.25% (historically 1.7%), on higher volume than the prior day.
- **Quantifiable Edges (1971–2008):** only about **55%** of FTDs succeeded (about 45% on a stricter test). Every rally had one, so an FTD is **necessary but not sufficient**.
- **Distribution days:** index down ≥0.2% on higher volume; 4–6 within 4–5 weeks = warning. Bulkowski found they predicted declines **only in markets already falling**, so they give no early warning at tops.
- **Mechanised IBD Market Pulse (CrystalBull, a vendor):** about 130% vs 338% buy-and-hold since 2013, with many false "uptrend" calls in 2007–09.

### F. Your own trades as the regime signal [A]
- **Minervini:** progressive exposure. Size up only after trades work; shrink after losses.
- **Qullamaggie:** index 10/20-DMA **plus** "are my breakouts working?"
- This is hard to backtest from scan data. It is cheap to apply live, though: count recent stop-outs.

### G. Volatility and India VIX [weak for direction]
- Volatility predicts **volatility** well and **direction** poorly.
- India VIX bands (<15 calm, >20 elevated, >30 panic) are folklore; there is no rigorous NSE swing test.
- **Best use:** size down, or pause shorts, in panic states (see C). Do not use it as a buy/sell signal.

### H. HMM, Markov switching and jump models [not recommended yet]
- Gains show up mainly in papers written by the method's own developers.
- Raw signals flip too often; the fix is a transition penalty, which is effectively a slower filter.
- **Look-ahead trap:** the same HMM on SPY had Sharpe **0.78** using real-time ("filtered") probabilities and **1.74** using full-sample ("smoothed") ones.
- There is no demonstrated edge over a 200-DMA.

---

## 4. How this repo's earlier findings line up — ALL UNVERIFIED [R]

These studies ran on 2026-07-25, **before** the Aug-7 harness audit found three bugs (sizing, selection order, no random-entry control). Treat each row as a hypothesis to re-test.

| Repo finding [R] | External evidence | Agreement |
|---|---|---|
| Breadth score is anti-predictive for individual breakout trades; it works only by reducing how many trades appear | Breadth tests are thin; Bonde: lags at tops; Zaremba: cross-sectional only | Plausible, but untrusted |
| FTD was the only signal that passed calibration | QE: FTDs succeed only about 55% of the time | Partial. Worth re-testing, expect modest effect |
| Distribution days were "inverted": more distribution days led to better breakouts | Bulkowski: no value in uptrends | Consistent. Distribution days look useless as a gate |
| T2108 < 20 washout → median +2.7% over 20 days, both eras | Bonde: "<20 leads to bottoms"; India practitioners: <20% = bottoms | Consistent. Strongest candidate for "bottom" detection |
| Index-trend gate "inverted" at D+5 | **Conflicts** with Cooper et al., Faber and Clenow | **Key conflict.** The repo tested 5-day pre-stop returns with D+1-open entry; the literature is monthly-horizon. Re-test at 20–60 day horizons |
| Circuit-breaker: after 3 days of heavy stop-outs, the next day is −0.5R | Minervini/Qullamaggie's "are my trades working" | Consistent in spirit. Biggest repo effect, so it needs independent re-derivation |
| Net-4%-movers LOW = burst kill-switch | Stockbee: ratio < 1 = breakouts fail | Consistent in spirit |

---

## 5. Pitfalls — the testing rules we should adopt

1. **Pre-register.** Write the gate definition and pass bars before running anything. No thresholds read off the results.
2. **One shared regime definition for all strategies.** No per-strategy tuning; that is a hidden free parameter.
3. **Decide at close t, act at open t+1.** Same-bar execution was the look-ahead that created Glabadanidis's result.
4. **Only real-time information.** No full-sample percentiles, no smoothed HMM probabilities. Thresholds must use trailing windows only.
5. **Count regime transitions, not days.** India since 2005 has had roughly 6–8 real regime shifts: 2008, 2011, 2015–16, 2018 small caps, 2020, 2024–25. That supports **1–2 parameters at most**.
6. **Parameter neighbourhoods.** Report the median across, for example, 150/200/250-DMA. If only one value works, it is luck.
7. **Multiple-testing hurdle.** Aim for t > 3 (Harvey-Liu-Zhu), or use the deflated Sharpe ratio / probability of backtest overfitting (Bailey et al.). Log every variant tried.
8. **Separate long and short gates.** Longs die in bear trends; shorts die in panic rebounds. These are different mechanisms.
9. **Show COVID separately.** The 2020 V-shape dominates any Indian regime backtest.
10. **Judge by the removed trades.** Report the average R of the trades the gate **removes** vs those it **keeps**, plus the winners lost.
11. **Survivorship:** our daily store holds only currently listed stocks. For index-level tests, the IIMA momentum factor library is survivorship-corrected and free to use as a cross-check.

---

## 6. Shortlist for the next step (proposals — NOT built)

Four gates, each a standard textbook form with 1–2 parameters and a published evidence base:

| Gate | For | Proposed rule (standard, not fitted) | Evidence | What it should do |
|---|---|---|---|---|
| **G1 Trend** | Long breakouts | Smallcap 250 (and Nifty 500 as a cross-check) close > 0.98 × 200-DMA; alternative: 12-month return > 0 | Faber, Clenow, Bensdorp, Cooper [I] | Cut drawdowns in bear trends; frequency falls |
| **G2 Washout / thrust** | Bottom re-entry, bounces | % of stocks above 40-DMA < 20 (washout); FTD as confirmation | Bonde [A], QE [I], repo [R] | Get back in earlier than G1 after crashes |
| **G3 Panic-state** | **Shorts** (lone-loser) | No new shorts when the index is below its 2-year level **and** 20-day realised volatility is in its top trailing quintile | Daniel & Moskowitz [I] | Avoid squeeze rebounds, the known drawdown driver |
| **G4 Own-trades** | All | Pause or halve size after N consecutive stop-outs (or a stop-out cluster) | Minervini/Qullamaggie [A], repo [R] | Catch setup-level failure that market gauges miss |

**Proposed test design** (for approval before building anything):
- Re-derive each gate from this spec in fresh code. Do not reuse existing filter code.
- Apply the gates to **Ryan/Minervini** (longs) and **lone-loser** (short).
- Report a **gate × era grid**:
  - era A 2015–19
  - COVID 2020–22, reported separately
  - era B 2023–26
  - the 2024–26 sub-era
- Include a random-entry control and removed-vs-kept trade stats.

---

## 7. Open decisions for the user

1. **Which index defines the regime:** Nifty 50, Nifty 500, or Smallcap 250? The literature says match the index to the universe, which argues for Smallcap 250 for small/mid-cap breakouts.
2. **Hard gate vs size scaling:** switch trading off, or scale size down (e.g. full / half / zero)? The literature's drawdown benefit applies to both. Scaling is gentler on whipsaw.
3. **Horizon:** accept that a gate may add *nothing* to return and only cut drawdown? If yes, the pass bar is "same CAGR, smaller drawdown". If not, most gates will fail.

---

## References

**Academic**
- Faber 2007/2013 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461
- Moskowitz, Ooi & Pedersen 2012 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
- Hurst, Ooi & Pedersen 2017 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
- Huang, Li, Wang & Zhou 2020 — https://ideas.repec.org/a/eee/jfinec/v135y2020i3p774-794.html
- Kim, Tse & Wald 2016 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2786955
- Zakamulin 2014 — https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html · 2018 — https://ideas.repec.org/a/bla/irvfin/v18y2018i2p317-327.html
- Cooper, Gutierrez & Hameed 2004 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=299927
- Asem & Tian 2010 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1009318
- Daniel & Moskowitz 2016 — https://www.nber.org/papers/w20439
- Barroso & Santa-Clara 2015 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429
- Moreira & Muir 2017 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2659431
- Cederburg et al. 2020 — https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:1:p:95-117
- Ang & Bekaert 2002 — https://academic.oup.com/rfs/article-abstract/15/4/1137/1568247
- Kritzman, Page & Turkington 2012 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2066848
- Shu, Yu & Mulvey 2024 (jump models) — https://arxiv.org/abs/2402.05272
- Han, Yang & Zhou 2013 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1656460
- Zaremba et al. 2021 (breadth) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3444882
- Sullivan, Timmermann & White 1999 — https://ideas.repec.org/a/bla/jfinan/v54y1999i5p1647-1691.html
- Harvey, Liu & Zhu 2016 — https://academic.oup.com/rfs/article/29/1/5/1843824
- Bailey et al., Probability of Backtest Overfitting — https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- IIMA Indian Fama-French-Momentum library — https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/
- Raju (India momentum) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3510433
- India VIX information content — https://link.springer.com/article/10.1007/s40196-013-0025-4

**Practitioner**
- IBD FTD rules — https://finance.yahoo.com/news/day-tells-time-buy-stocks-215900253.html
- Quantifiable Edges, FTD tests — https://quantifiableedges.com/follow-through-days-quantified/
- Bulkowski, distribution days — https://www.thepatternsite.com/DistributionDay.html · stages — https://www.thepatternsite.com/Stages.html
- CrystalBull, Market Pulse test — https://www.crystalbull.com/IBD-market-pulse-review/
- Stockbee Market Monitor — https://stockbee.blogspot.com/p/mm.html · breadth posts — https://stockbee.blogspot.com/2011/08/how-to-use-market-breadth-to-avoid.html
- Qullamaggie, Chat With Traders transcript — https://tradingresourcehub.substack.com/p/qullamaggie-chat-with-traders-reimagined-transcript
- Clenow (TuringTrader replication) — https://www.turingtrader.com/portfolios/clenow-stocks-on-the-move/
- Bensdorp (TuringTrader code) — https://github.com/fbertram/TuringTrader/blob/master/BooksAndPubs/Bensdorp_30MinStockTrader.cs
- setup4alpha, 20 trend filters — https://setup4alpha.substack.com/p/i-tested-20-trend-based-regime-filters
- Financial Hacker, regime filter — https://financial-hacker.com/the-market-regime-filter/
- Quantinuous, Nifty dual momentum — https://quantinuous.substack.com/p/dual-momentum-the-strategy-that-sidestepped

**Unverified at the primary source** (seen only in search snippets):
- Radge's 75-DMA and ASX 3%/30% figures
- GEM's drawdown numbers
- IBD's current exposure bands
- The EM 0.29%/−0.02% momentum figure
- The Roskill (2026) Weinstein numbers
- Minervini using a Trend-Template count as a breadth gauge
