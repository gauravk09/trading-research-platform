import { useEffect, useState } from 'react'
import { fetchJson, useFetch } from '../api.js'
import DataTable from '../components/DataTable.jsx'

const BASE_COLS = [
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'sector', label: 'Sector', kind: 'text' },
  { key: 'mcap_cr', label: 'Mcap', kind: 'compact' },
  { key: 'close', label: 'Close', kind: 'rupee' },
  { key: 'chg_pct', label: '1D', kind: 'pct', digits: 2 },
  { key: 'volume_ratio', label: 'Vol ×', kind: 'num', digits: 1 },
  { key: 'r1mo_pct', label: '1M', kind: 'pct' },
  { key: 'r3mo_pct', label: '3M', kind: 'pct' },
  { key: 'adr_pct', label: 'ADR', kind: 'num', digits: 2 },
  { key: 'rs_rank', label: 'RS', kind: 'num', digits: 0 },
]

// scans that need a column swapped in after Close
const EXTRA_COL = {
  four_pct_up_7d: { key: 'max_up_7d', label: 'Max 7d', kind: 'pct' },
  four_pct_down_7d: { key: 'max_down_7d', label: 'Max 7d', kind: 'pct' },
  ti65: { key: 'ti65', label: 'TI65', kind: 'num', digits: 3 },
}

export default function Scans({ onOpenChart }) {
  const [scans, setScans] = useState([])
  const [active, setActive] = useState('four_pct')
  const [minTurnover, setMinTurnover] = useState(1)
  const [foOnly, setFoOnly] = useState(false)
  const [exclSurv, setExclSurv] = useState(true)

  useEffect(() => {
    fetchJson('/api/scans').then(setScans)
  }, [])

  const params = new URLSearchParams({
    min_turnover_cr: minTurnover,
    fo_only: foOnly,
    excl_surv: exclSurv,
  })
  const { data: result } = useFetch(`/api/scans/${active}?${params}`)

  const activeScan = scans.find((s) => s.key === active)
  const cols = EXTRA_COL[active]
    ? [...BASE_COLS.slice(0, 4), EXTRA_COL[active], ...BASE_COLS.slice(4)]
    : BASE_COLS

  return (
    <>
      <div className="page-head">
        <h1>Scans</h1>
        <p>Stockbee-style momentum scans over today's universe</p>
      </div>

      <div className="toolbar">
        {scans.map((s) => (
          <button key={s.key} className={s.key === active ? 'active' : ''} onClick={() => setActive(s.key)}>
            {s.label}
          </button>
        ))}
      </div>

      <div className="toolbar">
        <label>T/O ≥ <input type="number" style={{ width: 64 }} value={minTurnover} min={0} step={0.5} onChange={(e) => setMinTurnover(+e.target.value)} /> Cr</label>
        <button className={foOnly ? 'active' : ''} onClick={() => setFoOnly(!foOnly)}>F&O only</button>
        <button className={exclSurv ? 'active' : ''} onClick={() => setExclSurv(!exclSurv)}>Exclude ASM/GSM</button>
      </div>

      <div className="card panel">
        <h3>{activeScan?.label ?? active}</h3>
        <div className="panel-sub">
          {activeScan?.desc} · {result ? `${result.count} matches` : 'running…'}
        </div>
        {!result ? (
          <div className="loading">Scanning…</div>
        ) : result.count === 0 ? (
          <div className="empty">No matches today.</div>
        ) : (
          <DataTable key={active} rows={result.rows} columns={cols} onRowClick={(r) => onOpenChart(r.symbol)} />
        )}
      </div>
    </>
  )
}
