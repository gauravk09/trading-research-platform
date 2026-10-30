import { useEffect, useState } from 'react'
import { fetchJson, fmt, pctClass } from '../api.js'

// Setups worth a card on the brief, in reading order
const CARD_SCANS = [
  ['breakout_setup', 'Breakout Setup'],
  ['ep9m', 'EP9M'],
  ['dep', 'DEP Watchlist'],
  ['reversal_bullish', 'Bullish Reversal'],
]

function CandidateCard({ c, riskInr, onOpenChart }) {
  const hasLevels = c.entry_price && c.stop_price
  return (
    <div
      className="card panel"
      style={{ marginBottom: 10, cursor: 'pointer' }}
      onClick={() => onOpenChart(c.symbol)}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="sym" style={{ fontSize: 16 }}>{c.symbol}</span>
        <span className={`num ${pctClass(c.chg_pct)}`}>{fmt.pct(c.chg_pct, 2)}</span>
        {c.catalyst && <span className="chip">{c.catalyst}</span>}
        {c.is_fo && <span className="chip">F&O</span>}
        <span className="spacer" style={{ flex: 1 }} />
        <span className="dim" style={{ fontSize: 12 }}>
          ADR {fmt.num(c.adr_pct, 1)}% · RS {fmt.num(c.rs_rank, 0)} · T/O ₹{fmt.num(c.avg_turnover_cr, 0)} Cr
        </span>
      </div>
      <div style={{ margin: '6px 0', fontSize: 13.5 }}>
        {hasLevels ? (
          <>
            Entry {fmt.rupee(c.entry_price)} → <span className="down">stop {fmt.rupee(c.stop_price)}</span>
            {' '}({fmt.num(c.risk_pct, 1)}% level risk · ticket budget {fmt.rupee(riskInr)} · size in Order Pad)
          </>
        ) : (
          <span className="dim">watch — no entry until the burst day</span>
        )}
      </div>
      {c.reason && <div className="dim" style={{ fontSize: 12.5 }}>{c.reason}</div>}
      {c.catalyst_subject && <div className="dim" style={{ fontSize: 12.5 }}>{c.catalyst_subject}</div>}
      <div style={{ marginTop: 6 }}>
        {(c.flags ?? []).length === 0 ? (
          <span className="up" style={{ fontSize: 12 }}>✓ clean — no quality flags</span>
        ) : (
          c.flags.map((f) => (
            <span key={f} className="chip" style={{ background: 'var(--down-soft)', color: 'var(--down)', marginRight: 4 }}>
              ✕ {f}
            </span>
          ))
        )}
      </div>
    </div>
  )
}

export default function Brief({ onOpenChart }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState(null)
  const [equity, setEquity] = useState(() => Number(localStorage.getItem('equity')) || 1000000)

  useEffect(() => {
    fetchJson('/api/state').then(setState).catch(setError)
  }, [])

  useEffect(() => {
    localStorage.setItem('equity', equity)
  }, [equity])

  if (error) return <div className="empty">No state file — run the EOD update first.</div>
  if (!state) return <div className="loading">Loading tonight's brief…</div>

  const { regime, fii_dii, participation, news, scans } = state
  const knobs = regime.knobs ?? {}
  const riskInr = (equity * (knobs.risk_per_trade_pct ?? 0.5)) / 100

  return (
    <>
      <div className="page-head">
        <h1>Daily Brief</h1>
        <p>Data date {state.meta.data_date} · generated {state.meta.generated_at?.slice(11, 16)} IST</p>
      </div>

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="label">Risk regime</div>
          <div className="value"><span className={`tier-badge tier-${regime.tier}`}>{regime.tier}</span></div>
          <div className="sub">
            crash risk {fmt.prob(regime.p_drop_20d)} vs avg {fmt.prob(regime.baseline_p_drop_20d)} · risk {knobs.risk_per_trade_pct}% · max {knobs.max_open_positions} positions
          </div>
        </div>
        <div className="card stat-card">
          <div className="label">FII / DII (₹ Cr)</div>
          <div className="value num" style={{ fontSize: 20 }}>
            <span className={pctClass(fii_dii?.FII_net_cr)}>{fmt.num(fii_dii?.FII_net_cr, 0)}</span>
            <span className="dim"> / </span>
            <span className={pctClass(fii_dii?.DII_net_cr)}>{fmt.num(fii_dii?.DII_net_cr, 0)}</span>
          </div>
          <div className="sub">{fii_dii?.date}</div>
        </div>
        <div className="card stat-card">
          <div className="label">Participation</div>
          <div className="value num" style={{ fontSize: 20 }}>{fmt.num(participation?.ratio_20d, 2)}×</div>
          <div className="sub">₹{fmt.num(participation?.turnover_cr, 0)} Cr vs 20d avg · below 0.7× = circuit-breaker zone</div>
        </div>
        <div className="card stat-card">
          <div className="label">Sizing</div>
          <div className="value num" style={{ fontSize: 20 }}>{fmt.rupee(riskInr)}</div>
          <div className="sub">
            risk/ticket on ₹
            <input
              type="number"
              style={{ width: 110, padding: '2px 6px', fontSize: 12 }}
              value={equity}
              step={100000}
              onChange={(e) => setEquity(+e.target.value)}
            /> equity
          </div>
        </div>
      </div>

      <div className="card panel">
        <h3>How the risk regime works</h3>
        <div className="panel-sub" style={{ marginTop: 8 }}>
          A hidden Markov model reads Nifty 500's 20-day return and volatility and estimates the chance of a
          ≥5% drop within 20 sessions. Above its historical average → ELEVATED, sizing halves. It forecasts
          risk, not direction — validated 2000–2024 and on sealed 2025–26 data. State: {regime.state}; model
          trained through {regime.trained_through}.
        </div>
      </div>

      <div className="chart-grid">
        <div>
          {CARD_SCANS.map(([key, label]) => {
            const scan = scans[key]
            if (!scan) return null
            return (
              <div key={key} style={{ marginBottom: 18 }}>
                <h3 style={{ margin: '0 0 8px' }}>
                  {label} <span className="dim" style={{ fontWeight: 400, fontSize: 13 }}>· {scan.total_matches} match{scan.total_matches === 1 ? '' : 'es'}</span>
                </h3>
                {scan.candidates.length === 0 && <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>None tonight.</div>}
                {scan.candidates.slice(0, 5).map((c) => (
                  <CandidateCard key={c.symbol} c={c} riskInr={riskInr} onOpenChart={onOpenChart} />
                ))}
              </div>
            )
          })}
        </div>
        <div className="card panel" style={{ alignSelf: 'start' }}>
          <h3>Overnight news</h3>
          <div className="panel-sub">catalyst-grade headlines since the close</div>
          {(news ?? []).map((n, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
              <a href={n.url} target="_blank" rel="noreferrer">{n.headline}</a>
              <div className="dim" style={{ fontSize: 11.5 }}>{n.source} · {n.published?.slice(11, 16)}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
