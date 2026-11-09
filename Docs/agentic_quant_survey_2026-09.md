# Agentic Quant Trading Survey (arXiv:2608.31041) → what it means for our system

Date: 2026-09-03. Sources: the survey + 22 cited papers read in full (notes_factor_mining.md, notes_reliability.md, notes_risk_coordination.md in this folder).

## Plain-language verdict
The survey's three findings describe our system almost exactly, and in two of three we are already on the right side:
1. "Signal discovery dominates, full workflow is rare" — same here. evolve.py / research factory are strong; portfolio construction is additive sleeves with fixed knobs; execution is manual by design (Rejected: auto-orders). Fine.
2. "Aggregation dominates, gating/selection rare" — we are gate-heavy (S0-S8 cascade, /brief PASS/BLOCK). That is the direction the survey recommends. Multi-agent debate is Rejected in ROADMAP, and the cited evidence backs that (AMA: architecture explains more than backbone; gates never raised returns in any paper, only cut drawdown by trading smaller).
3. "Evaluation setting changes what results mean" — our harness audit found this the hard way (no random-entry control ⇒ beta counted as edge). The cited papers give a stronger tool: full market/style/selection decomposition.

Marginal value from MORE gates is plausibly negative. The transferable value is in scoring rules, search memory, and contracts.

## Do now (ranked)
| # | Change | Paper | Where | Est. |
|---|--------|-------|-------|------|
| 1 | Barra-style decomposition on every scoreboard row: Common (market) + Style + Selection α. Daily cross-sectional regression r_it = f0 + Σ x_ik,t-1 λ_kt + ε; α = Σ w_i,t-1 ε_it. Nine OHLCV factors (MOM_12_1, RV_60, ILLIQ, REV_ON, MOM_ID, SKEW, CORR_PV, HIGH_52W, CV_VOL). Promote on Selection α; still print raw excess (MOM/HIGH_52W absorb Qullamaggie by construction). | KTD-Fin 2605.28359 | src/backtest/bookrunner.py next to random_control()/same_date_control() | ~1 day |
| 2 | Two cheap fitness gates in evolve.py: (a) PFS = min(Spearman(rank, rank_noisy)) over Gaussian(σ=index vol) and t(3) noise, require ≥0.9; (b) coverage charge d_drop = share of panel the spec silently NaNs out, weight it heaviest (Hubble uses 3.0). Kills knife-edge thresholds and survivor-only specs; uses no future data. | AlphaEval 2508.13174, Hubble 2604.09601 | research/machine/evolve.py fitness | ~½ day |
| 3 | MAP-Elites archive replacing the elite list: cells keyed on behaviour (family multi-hot, trades/yr, hold days, avg ADR, maxDD), ~16 bins/dim, one genome per cell, parents 50/50 archive vs population. QuantEvolve ablation reproduces our "budget spent on noise" curve (SR 1.24→1.06 with coarse bins, →1.52 with 16). Plus a residual motif ledger across runs: key (parent bucket, AST-diff motif), store δ = z(child) − E[z|parent], confidence c=[n/(n+κ)]·min(1,|μ|/(σ+ε)); hard-veto only, with yearly decay. | QuantEvolve 2510.18569, AlphaMemo 2606.20625 | evolve.py + evolve_runs/ | 1–2 days |
| 4 | Typed daily-plan contract: candidate JSON {symbol, setup, entry, stop, qty, risk_pct, turnover_cr, gate_results{regime, exposure, participation, circuit_breaker, concentration, earnings, leakage_checked}, reject_reason} validated in Python BEFORE any prose; /trade refuses a plan without it. Risk layer may pass/fail, never modify. Add FalseBlock = share of gate-killed candidates that graded positive (from grade_decisions.py). | AgenticAITA 2605.12532, Orchestration 2512.02227, SAE 2603.10092 | daily state JSON, .claude/skills/brief, src/execution/orders/plans.py | ~½ day |
| 5 | Protocol header on every study/LEDGER row: split, cost model, execution semantics, survivorship handling, seed/snapshot, R-tier; require R2 (fresh session re-runs from committed config + snapshot, same numbers) before promotion. Check research/experiment_manifest.template.json first — may already cover most of it. | Xia 2605.19337 | research/factory/LEDGER.md, manifest template | ~1 hr |

## Later / test the premise first
- Trailing-performance strategy weights with zero floor (ContestTrade 2508.00554: w = max(0,û)/Σmax(0,û)). Only if trailing-20d expectancy predicts next-20d on OUR journal. Journal has ~6 decision dates → not testable yet.
- Drawdown ladder (cut 20/30/50% at rising DD, hard flatten) replacing binary circuit-breaker. Current breaker is validated (−0.5R after clusters); only swap after a refit on swing magnitudes.
- Anonymised hypothesis replay (KTD-Fin): Claude proposes hypotheses knowing NSE 2015–26 outcomes. Holdout + placebo already guard scoring, not hypothesis SELECTION. Cheap partial: era-B names/dates never shown to the proposer (llm_evolve.py file bridge already hides data; extend to study design).
- Thompson-sampling scheduler over search directions (R&D-Agent-Quant) beat letting the LLM choose (+41% ARR). Candidate for llm_evolve.py if the LLM operator loses its A/B.
- Decorrelation cap at plan level (AgenticAITA CBD, AlphaCrafter θ_sim=0.8): three sleeves firing on one sector breakout = one bet.

## Do NOT adopt (Rejected list or evidence)
- Multi-agent debate / personality agents (ROADMAP Rejected; survey: aggregation ≠ edge).
- LLM-defined regime (Rejected; deterministic src/preprocessing/breadth.py stays).
- Autonomous order placement (Rejected; every live benchmark says risk control, not analysis, decided outcomes).
- More return-seeking gates: every paper's gates only cut DD by trading smaller; SAE's cooldown component made it slightly worse.

## Skepticism on the literature
Windows 5 days–2 years, single markets, no multiple-testing correction, no random baseline in most. Our placebo floor + era-B holdout is stricter than any protocol in these 22 papers. Copy designs and ablations, never headline numbers; refit every threshold.

## What landed (2026-09-03)
All five "do now" items are built; see ROADMAP.md "Agentic-quant survey adoption"
for files, calibration numbers and the first real-data attribution read.
