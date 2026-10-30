import { useEffect, useState } from 'react'
import { fetchJson } from '../api.js'
import DataTable from '../components/DataTable.jsx'

const SETUPS = [
  ['breakout_setup', 'Breakout Setup'],
  ['ep9m', 'EP9M'],
  ['dep', 'DEP Watchlist'],
  ['ep_checklist', 'EP Checklist'],
  ['anticipation', 'Anticipation'],
  ['reversal_bullish', 'Bullish Reversal'],
  ['bottom_bounce', 'Bottom Bounce'],
  ['four_pct', '4% Breakout'],
  ['four_pct_down', '4% Breakdown'],
  ['ti65', 'TI65'],
  ['weak_structure', 'Weak Structure'],
]

const BASE = [
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'close', label: 'Close', kind: 'rupee' },
  { key: 'chg_pct', label: '1D', kind: 'pct', digits: 2 },
  { key: 'volume_ratio', label: 'Vol ×', kind: 'num', digits: 1 },
  { key: 'adr_pct', label: 'ADR', kind: 'num', digits: 1 },
  { key: 'rs_rank', label: 'RS', kind: 'num', digits: 0 },
  { key: 'r3mo_pct', label: '3M', kind: 'pct' },
]

const EXTRA = {
  breakout_setup: [
    { key: 'entry_price', label: 'Entry', kind: 'rupee' },
    { key: 'stop_price', label: 'Stop', kind: 'rupee' },
    { key: 'risk_pct', label: 'Risk %', kind: 'num', digits: 1 },
    { key: 'reason', label: 'Why', kind: 'text' },
  ],
  ep9m: [
    { key: 'vol_rank', label: 'Vol Rank', kind: 'num', digits: 0 },
    { key: 'catalyst', label: 'Catalyst', kind: 'text' },
  ],
  dep: [{ key: 'range_pct_5d', label: '5d Range', kind: 'num', digits: 1 }],
  ep_checklist: [{ key: 'catalyst', label: 'Catalyst', kind: 'text' }],
  anticipation: [
    { key: 'range_pct_5d', label: '5d Range', kind: 'num', digits: 1 },
    { key: 'vol_contraction', label: 'Vol Contr.', kind: 'num', digits: 2 },
  ],
}

function flagCol() {
  return {
    key: 'flags',
    label: 'Flags',
    kind: 'text',
  }
}

export default function Setups({ onOpenChart }) {
  const [state, setState] = useState(null)
  const [active, setActive] = useState('breakout_setup')

  useEffect(() => {
    fetchJson('/api/state').then(setState)
  }, [])

  if (!state) return <div className="loading">Loading tonight's setups…</div>

  const scan = state.scans[active] ?? { candidates: [], total_matches: 0 }
  const rows = scan.candidates.map((c) => ({
    ...c,
    flags: (c.flags ?? []).join(', ') || '✓ clean',
  }))
  const cols = [...BASE, ...(EXTRA[active] ?? []), flagCol()]

  return (
    <>
      <div className="page-head">
        <h1>Setups</h1>
        <p>Tonight's candidates from the EOD state file · data date {state.meta.data_date}</p>
      </div>

      <div className="toolbar">
        {SETUPS.filter(([k]) => state.scans[k]).map(([k, label]) => (
          <button key={k} className={k === active ? 'active' : ''} onClick={() => setActive(k)}>
            {label}
            <span className="dim" style={{ marginLeft: 6, fontSize: 11 }}>
              {state.scans[k].total_matches}
            </span>
          </button>
        ))}
      </div>

      <div className="card panel">
        <div className="panel-sub">
          {scan.total_matches} matches · showing top {rows.length} · click a row for the chart
        </div>
        {rows.length === 0 ? (
          <div className="empty">None tonight.</div>
        ) : (
          <DataTable key={active} rows={rows} columns={cols} onRowClick={(r) => onOpenChart(r.symbol)} />
        )}
      </div>
    </>
  )
}
