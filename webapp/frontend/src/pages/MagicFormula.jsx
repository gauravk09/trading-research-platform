import { useEffect, useMemo, useState } from 'react'
import { fetchJson, fmt } from '../api.js'
import DataTable from '../components/DataTable.jsx'

const COLUMNS = [
  { key: 'candidate_rank', label: '#', kind: 'num', digits: 0 },
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'industry', label: 'Industry', kind: 'text' },
  { key: 'blend_score', label: 'Blend', kind: 'num', digits: 1 },
  { key: 'magic_score', label: 'Magic', kind: 'num', digits: 1 },
  { key: 'value_score', label: 'Value', kind: 'num', digits: 1 },
  { key: 'quality_score', label: 'Quality', kind: 'num', digits: 1 },
  { key: 'momentum_12_1_pct', label: '12–1M', kind: 'pct', digits: 1 },
  { key: 'ev_ebit', label: 'EV/EBIT', kind: 'num', digits: 1 },
  { key: 'roce', label: 'ROCE', kind: 'pct', digits: 1 },
  { key: 'close', label: 'Close', kind: 'rupee' },
]

const STATE_LABELS = {
  CONFIRMED: 'Trend confirmed',
  WAITING_FOR_TREND: 'Waiting for trend',
  INSUFFICIENT_HISTORY: 'Insufficient history',
  NO_PRICE_DATA: 'No price data',
}

function ScoreBar({ value, tone = 'blue' }) {
  return (
    <div className="mf-scorebar" aria-label={`Score ${value ?? 0} out of 100`}>
      <span className={tone} style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} />
    </div>
  )
}

export default function MagicFormula({ onOpenChart }) {
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [state, setState] = useState('CANDIDATES')
  const [sector, setSector] = useState('')
  const [minScore, setMinScore] = useState(0)

  useEffect(() => {
    fetchJson('/api/magic-formula', { force: true })
      .then(setPayload)
      .catch(setError)
  }, [])

  const sectors = useMemo(
    () => [...new Set((payload?.rows ?? []).map((row) => row.industry).filter(Boolean))].sort(),
    [payload],
  )

  const rows = useMemo(() => {
    const term = query.trim().toUpperCase()
    return (payload?.rows ?? []).filter((row) => {
      if (term && !`${row.symbol} ${row.name ?? ''}`.toUpperCase().includes(term)) return false
      if (sector && row.industry !== sector) return false
      if ((row.blend_score ?? -Infinity) < minScore) return false
      if (state === 'CANDIDATES' && !row.is_candidate) return false
      if (state !== 'ALL' && state !== 'CANDIDATES' && row.technical_state !== state) return false
      return true
    })
  }, [payload, query, state, sector, minScore])

  if (error) return <div className="empty">Could not load the Magic Formula board: {error.message}</div>
  if (!payload) return <div className="loading">Building the quality · value · momentum view…</div>

  if (!payload.ready) {
    return (
      <>
        <div className="page-head">
          <h1>Magic Formula Lab</h1>
          <p>Fundamental selection from Screener, technical confirmation from our price database</p>
        </div>
        <div className="card mf-empty-state">
          <div className="mf-empty-icon">MF</div>
          <h2>Import the first fundamental snapshot</h2>
          <p>{payload.message}</p>
          <code>{payload.setup_command}</code>
          <p className="dim">The imported CSV is retained by date; future technical refreshes reuse it without pretending it existed historically.</p>
        </div>
      </>
    )
  }

  const { summary, meta } = payload
  const confirmationRate = summary.universe ? (summary.candidates / summary.universe) * 100 : 0

  return (
    <>
      <div className="page-head mf-title-row">
        <div>
          <div className="mf-eyebrow">QUALITY · VALUE · MOMENTUM</div>
          <h1>Magic Formula Lab</h1>
          <p>Screener fundamentals dated {meta.fundamentals_as_of} · local technicals through {meta.technicals_as_of}</p>
        </div>
        <div className="mf-live-pill"><span /> Forward-test ready</div>
      </div>

      <div className="stat-grid mf-stats">
        <div className="card stat-card">
          <div className="label">Eligible universe</div>
          <div className="value">{fmt.num(summary.universe)}</div>
          <div className="sub">After size and industry exclusions</div>
        </div>
        <div className="card stat-card mf-accent-card">
          <div className="label">Trade candidates</div>
          <div className="value up">{fmt.num(summary.candidates)}</div>
          <div className="sub">Trend + liquidity confirmed</div>
        </div>
        <div className="card stat-card">
          <div className="label">Confirmation rate</div>
          <div className="value">{confirmationRate.toFixed(0)}%</div>
          <ScoreBar value={confirmationRate} tone="green" />
        </div>
        <div className="card stat-card">
          <div className="label">Median 12–1M return</div>
          <div className="value">{fmt.pct(summary.median_momentum_pct)}</div>
          <div className="sub">Cross-sectional momentum input</div>
        </div>
      </div>

      <div className="mf-flow card">
        <div className="mf-flow-node">
          <span>01</span><strong>Screener snapshot</strong><small>{summary.universe} eligible businesses</small>
        </div>
        <i>→</i>
        <div className="mf-flow-node">
          <span>02</span><strong>Magic rank</strong><small>EV/EBIT + ROCE</small>
        </div>
        <i>→</i>
        <div className="mf-flow-node">
          <span>03</span><strong>Technical gate</strong><small>Close &gt; 200 DMA · 50 &gt; 200</small>
        </div>
        <i>→</i>
        <div className="mf-flow-node active">
          <span>04</span><strong>Blended board</strong><small>60% fundamental · 40% momentum</small>
        </div>
      </div>

      <div className="toolbar mf-toolbar">
        <input placeholder="Search symbol or company" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select value={state} onChange={(event) => setState(event.target.value)}>
          <option value="CANDIDATES">Trade candidates</option>
          <option value="CONFIRMED">All trend confirmed</option>
          <option value="WAITING_FOR_TREND">Waiting for trend</option>
          <option value="INSUFFICIENT_HISTORY">Insufficient history</option>
          <option value="ALL">All eligible stocks</option>
        </select>
        <select value={sector} onChange={(event) => setSector(event.target.value)}>
          <option value="">All industries</option>
          {sectors.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <label>Blend ≥ <input type="number" min="0" max="100" value={minScore} onChange={(event) => setMinScore(Number(event.target.value))} /></label>
        <span className="spacer" />
        <span className="mf-count">{rows.length} names</span>
      </div>

      <div className="card panel mf-board">
        <div className="mf-board-head">
          <div>
            <h3>Ranked opportunity board</h3>
            <div className="panel-sub">Click a row for the price chart. Scores run from 0 to 100; higher is better.</div>
          </div>
          <div className="mf-legend"><span className="green" /> Confirmed <span className="amber" /> Waiting</div>
        </div>
        {rows.length ? (
          <DataTable rows={rows} columns={COLUMNS} onRowClick={(row) => onOpenChart(row.symbol)} />
        ) : (
          <div className="empty">No companies match these filters.</div>
        )}
      </div>

      <div className="mf-footer-note">
        <strong>Point-in-time discipline:</strong> this board only uses prices available on the technical cutoff date.
        The Screener snapshot remains dated {meta.fundamentals_as_of}; it is not backfilled into earlier periods.
        States: {Object.entries(STATE_LABELS).map(([key, label]) => `${label} (${payload.rows.filter((row) => row.technical_state === key).length})`).join(' · ')}.
      </div>
    </>
  )
}
