# Alternative Data for Indian Equities — Factor-Mining Field Guide

> Research reference for the *next* Alpha Forge phase (alt-data factor class).
> Not yet built. Data track in progress is intraday 5-min OHLCV; this is the
> parked plan for bolting free alt-data sources into the daily miner.

**Scope:** How quant/discretionary funds use alt-data, narrowed to sources that
are publicly and freely available for NSE/BSE, with an eye to turning each into a
cross-sectional (XS) or time-series (TS) factor. Evidence is flagged honestly —
several widely-believed signals are weakly evidenced or contested.

---

## 1. Taxonomy of alt-data classes

Roughly 65% of hedge funds use some alternative data; web-scraped data appears in
over half of usage surveys.

| Class | Signal funds extract | Horizon | Decay / crowding |
|---|---|---|---|
| **Flow** (FII/DII, bulk/block, participant F&O) | "Smart money" positioning, directional pressure | Days–weeks | Crowded in India; FII flow is return-*chasing*, lags |
| **Positioning / derivatives** (OI, PCR, skew, max-pain) | Sentiment extremes, dealer hedging | Intraday–2wk | PCR degraded by retail; weak for index vs single-name |
| **Sentiment** (news, social, Google Trends) | Attention spikes, retail crowding | Days–weeks | Fast decay; reverses when attention fades |
| **Fundamental-adjacent** (earnings surprise, revisions, insider/promoter, shareholding & pledge Δ) | Information asymmetry, drift | Weeks–quarters | Slowest decay (best class); disclosure lag, small per-stock samples |
| **Macro / cross-asset** (commodity, USDINR, rates, VIX) | Regime, sector tilts | Weeks–months | Not stock-specific → timing only; regime-dependent |
| **Web / satellite / card** | Company demand nowcast | Weeks–quarters | Almost all **paid**; India coverage thin; ROI often overstated |

**Fund-world lesson:** durable edge is in *fundamental-adjacent* data (spending,
revisions, insider behavior) fed as a normalized factor input; satellite/exotic
sources rarely pay for themselves outside a dedicated sector desk.

---

## 2. India-specific free sources

Community Python wrappers already parse most of these: `jugaad-data`,
`nsepython`, `nsefin`, `pynse`.

- **FII/DII daily cash flows** — NSE/BSE daily; net buy/sell ₹cr, FII vs DII.
  **Market-level only → TS, not per-stock.** Excellent free access.
- **Participant-wise OI (F&O)** — NSE daily report; long/short OI for Client, Pro,
  FII, DII across index/stock futures & options. EOD CSV, archived. Mostly TS;
  stock-futures long/short can be pushed toward XS.
- **Bulk & block deals** — NSE/BSE, SEBI-mandated (>0.5% of shares). Date, symbol,
  client name, buy/sell, qty, avg price. **Per-stock and named → XS.** Daily CSV.
- **Insider trading (SEBI PIT) & SAST** — NSE/BSE corporate filings via depository
  System Driven Disclosures. Insider/promoter buy/sell/pledge, qty, value,
  transaction & disclosure dates. XBRL/CSV. **XS, slow decay — highest-signal filing.**
- **Shareholding pattern & promoter pledge Δ** — quarterly Reg 31 + SAST pledge.
  Promoter %, FII/DII/MF %, **% pledged**. XBRL. The *change* is the factor. XS.
- **Delivery %** — NSE security-wise delivery (bhavcopy family). Per-stock delivered
  qty / traded qty. Daily, long history, cheapest daily XS input.
- **Options OI / PCR (index + single-stock)** — NSE option chain + F&O bhavcopy.
  Strike-level call/put OI, PCR, max-pain, OI change. Index PCR = TS; **stock-level
  PCR/OI = XS**.
- **Corporate announcements** — NSE/BSE, largely XBRL-structured. Category-tagged
  filings + timestamp + attachment text. Event-study / NLP input, per-stock.

**Gap:** no free, clean, machine-readable *consensus analyst estimate* feed for
India — the paid moat of Refinitiv/Bloomberg/Trendlyne. Earnings surprise must be
proxied (vs YoY or a simple time-series model).

---

## 3. Evidence base (honest reading of India-specific research)

- **FII/DII flows — contested.** Consensus: FIIs are momentum (return-chasing),
  DIIs contrarian. Positive *contemporaneous* correlation with Nifty, but flows
  *follow* price → weak forward-predictive value, reversal-prone. Post-2021 DII bid
  further weakened old relationships. *Believed, weakly evidenced as a forward signal.*
- **Bulk/block deals & insider trades — strongest India evidence.** Abnormal returns
  *before* bulk deals (buys > sells); insider *purchases* followed by significant
  positive abnormal returns (2015–2024 NSE/BSE). *Genuine XS signal; buys informative,
  sells noisy.*
- **Promoter pledge / shareholding Δ — robust as a risk factor.** Heavy pledging →
  higher vol, lower firm value, worse long-term performance. *Predicts downside/vol —
  best as short-side or exclusion, not long alpha.*
- **Delivery % — practitioner-strong, academically thin.** Accumulation/distribution
  proxy, but sources are trading guides not peer-reviewed. *Validate before trusting.*
- **PCR / options OI — real but limited.** Nifty volume-PCR predictive ~2.5 days,
  OI-PCR ~12 days; but weaker than media claims and worse for index than single-name.
  *Modest, fast-decaying, better on single stocks.*
- **Google Trends / attention — short-horizon, reversing.** Higher search volume →
  positive returns over the following 1–2 weeks in India (high retail share).
  *Short edge, high decay, noisy.*
- **PEAD / earnings surprise — present in India.** Significant 2002–2017, survives
  size/value/illiquidity/idiosyncratic-vol controls. *Strong anomaly, but clean
  version needs estimates you can't get free — use a proxy surprise.*

---

## 4. Factor-ready shortlist

Ranked by (a) evidence, (b) free access for India, (c) factor suitability.
**XS = rankable across stocks; TS = market-timing single series.**

| # | Source | Evidence | Free access | Type | Notes |
|---|---|---|---|---|---|
| 1 | Insider / promoter **purchases** | Strong | Good (XBRL) | XS | Best evidence + slow decay. Buys only; pool into rolling signal. |
| 2 | Promoter pledge Δ / shareholding Δ | Strong (risk/short) | Good (quarterly) | XS | Δpledge↑, ΔFII/MF%↓ as negative/exclusion. Low turnover. |
| 3 | Bulk/block deals | Moderate–strong | Good (daily CSV) | XS | Named institutional buys; front-running/lag risk. Event overlay. |
| 4 | Delivery % | Weak-pub / strong-practitioner | Excellent | XS | Cheapest daily XS input. Δdelivery × price direction. Validate. |
| 5 | Earnings surprise proxy + announcements | Strong anomaly | Moderate (build it) | XS | PEAD real; free surprise = YoY or model-based. |
| 6 | Stock options OI / PCR / skew | Modest, fast-decay | Good | XS | Single-name beats index. Short horizon. |
| 7 | Google Trends attention | Short-horizon | Good (rate-limited) | XS | 1–2wk edge, reverses; name collisions in India. |
| 8 | Participant-wise F&O OI | Weak/contested | Good | TS | Regime, not stock-picking. |
| 9 | FII/DII daily cash flows | Contested | Excellent | TS | Market-timing/regime gate only — don't expect forward alpha. |
| 10 | Macro (USDINR, crude, rates, VIX) | Regime-only | Excellent | TS→sector | Sector tilts (IT↔USDINR, OMC↔crude). |
| — | Satellite / card / web-scrape | Case-by-case | **Paid / thin** | XS | Out of scope for a free-data engine. |

### Build order for a free-data XS engine
1. **Daily, per-stock, cheap first:** delivery %, stock-options OI change, bulk-deal
   events, corporate-announcement events → dense XS coverage to rank the universe daily.
2. **Layer slow, high-signal filings:** insider *buys*, pledge/shareholding deltas as
   rolling factors + *exclusion* screens.
3. **Flow/macro only as regime gates** (FII/DII, participant OI, USDINR/crude/VIX) —
   never stock-selection; the evidence says they chase, not lead.
4. **Every "believed" signal (delivery %, PCR, Trends) must clear the holdout/placebo
   bar** before it earns capital — fits the existing z-fitness + placebo-floor protocol.

### Honesty caveats for construction
- NSE historical ASM/GSM / surveillance status isn't freely archived point-in-time →
  filings signals can carry survivorship/look-ahead traps.
- Disclosure *filing* dates lag *transaction* dates for insider/pledge data — align to
  the **public disclosure timestamp**, not trade date, or you inject look-ahead bias.
- FII/DII and participant-OI are aggregate — any "per-stock FII flow" marketed is an
  estimate, not disclosed data.

*Compiled 2026-08-29 via web research. Sources linked in the session transcript.*
