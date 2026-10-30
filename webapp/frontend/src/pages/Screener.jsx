import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../api.js'
import DataTable from '../components/DataTable.jsx'

const COLS = [
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'sector', label: 'Sector', kind: 'text' },
  { key: 'mcap_cr', label: 'Mcap', kind: 'compact' },
  { key: 'close', label: 'Close', kind: 'rupee' },
  { key: 'chg_pct', label: '1D', kind: 'pct', digits: 2 },
  { key: 'r1mo_pct', label: '1M', kind: 'pct' },
  { key: 'r3mo_pct', label: '3M', kind: 'pct' },
  { key: 'r6mo_pct', label: '6M', kind: 'pct' },
  { key: 'adr_pct', label: 'ADR', kind: 'num', digits: 2 },
  { key: 'avg_turnover_cr', label: 'T/O Cr', kind: 'num', digits: 1 },
  { key: 'rs_rank', label: 'RS', kind: 'num', digits: 0 },
]

export default function Screener({ onOpenChart }) {
  const [universe, setUniverse] = useState(null)
  const [query, setQuery] = useState('')
  // Empty string = filter off. Only T/O defaults to a real floor (the page is
  // about liquid names); ADR/3M/RS start off so the default view is the whole
  // liquid universe — otherwise a "3M ≥ 0" default silently hides every stock
  // down over 3 months, including large caps like RELIANCE.
  const [minAdr, setMinAdr] = useState('')
  const [minTurnover, setMinTurnover] = useState(1)
  const [minR3mo, setMinR3mo] = useState('')
  const [minRs, setMinRs] = useState('')
  const [foOnly, setFoOnly] = useState(false)

  useEffect(() => {
    fetchJson('/api/universe').then(setUniverse)
  }, [])

  const rows = useMemo(() => {
    if (!universe) return []
    const terms = query.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean)
    if (terms.length) {
      // symbol search bypasses the filters, same as the old desk
      return universe.filter((r) => terms.some((t) => r.symbol.includes(t)))
    }
    const gte = (v, min) => min === '' || (v ?? -Infinity) >= Number(min)
    return universe.filter(
      (r) =>
        gte(r.adr_pct, minAdr) &&
        gte(r.avg_turnover_cr, minTurnover) &&
        gte(r.r3mo_pct, minR3mo) &&
        gte(r.rs_rank, minRs) &&
        (!foOnly || r.is_fo),
    )
  }, [universe, query, minAdr, minTurnover, minR3mo, minRs, foOnly])

  return (
    <>
      <div className="page-head">
        <h1>Universe Screener</h1>
        <p>Every NSE stock, ranked and filterable — click a row to open its chart</p>
      </div>

      <div className="toolbar">
        <input
          style={{ minWidth: 320 }}
          placeholder="Jump to a stock — e.g. GOLDIAM, MUTHOOT (bypasses filters)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="spacer" />
        <label>ADR ≥ <input type="number" style={{ width: 64 }} placeholder="any" value={minAdr} min={0} step={0.5} onChange={(e) => setMinAdr(e.target.value)} /></label>
        <label>T/O ≥ <input type="number" style={{ width: 64 }} placeholder="any" value={minTurnover} min={0} step={0.5} onChange={(e) => setMinTurnover(e.target.value)} /></label>
        <label>3M% ≥ <input type="number" style={{ width: 64 }} placeholder="any" value={minR3mo} step={5} onChange={(e) => setMinR3mo(e.target.value)} /></label>
        <label>RS ≥ <input type="number" style={{ width: 64 }} placeholder="any" value={minRs} min={0} max={100} step={5} onChange={(e) => setMinRs(e.target.value)} /></label>
        <button className={foOnly ? 'active' : ''} onClick={() => setFoOnly(!foOnly)}>F&O</button>
      </div>

      <div className="card panel">
        <div className="panel-sub">{rows.length.toLocaleString()} stocks match</div>
        {!universe ? (
          <div className="loading">Loading universe…</div>
        ) : rows.length === 0 ? (
          <div className="empty">No stocks match the current filters.</div>
        ) : (
          <DataTable rows={rows} columns={COLS} onRowClick={(r) => onOpenChart(r.symbol)} />
        )}
      </div>
    </>
  )
}
