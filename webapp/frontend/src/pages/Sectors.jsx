import { Fragment, useEffect, useMemo, useState } from 'react'
import { fmt, useFetch } from '../api.js'
import DataTable from '../components/DataTable.jsx'

const HORIZONS = ['1D', '1W', '1M', '3M', '6M', '1Y']

// diverging green/red heat — intensity scales with |return| against the horizon's spread
function heatStyle(v, scale) {
  if (v == null) return {}
  const t = Math.min(Math.abs(v) / scale, 1)
  const alpha = 0.08 + t * 0.5
  return {
    background: v >= 0 ? `rgba(46, 230, 168, ${alpha})` : `rgba(255, 93, 115, ${alpha})`,
    color: t > 0.55 ? '#0a0c10' : 'inherit',
  }
}

const SCALE = { '1D': 2.5, '1W': 5, '1M': 10, '3M': 20, '6M': 30, '1Y': 50 }

const MEMBER_COLS = [
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'industry', label: 'Industry', kind: 'text' },
  { key: 'mcap_cr', label: 'Mcap', kind: 'compact' },
  { key: 'close', label: 'Close', kind: 'rupee' },
  { key: 'chg_pct', label: '1D', kind: 'pct', digits: 2 },
  { key: 'r1w_pct', label: '1W', kind: 'pct' },
  { key: 'r1mo_pct', label: '1M', kind: 'pct' },
  { key: 'r3mo_pct', label: '3M', kind: 'pct' },
  { key: 'r6mo_pct', label: '6M', kind: 'pct' },
  { key: 'pct_from_52w_high', label: 'vs 52wH', kind: 'pct' },
  { key: 'rs_rank', label: 'RS', kind: 'num', digits: 0 },
]

function Members({ group, level, onOpenChart }) {
  const { data: rows } = useFetch(`/api/sectors/members?group=${encodeURIComponent(group)}&level=${level}`)

  if (!rows) return <div className="loading" style={{ padding: '20px 0' }}>Loading {group}…</div>
  return (
    <div style={{ padding: '4px 0 12px' }}>
      <DataTable rows={rows} columns={MEMBER_COLS} onRowClick={(r) => onOpenChart(r.symbol)} maxRows={60} />
    </div>
  )
}

const SORT_KEYS = ['group', 'stocks', 'adv_pct', 'vs_52wh', ...HORIZONS]
const SORT_LABELS = { group: 'Group', stocks: 'Stocks', adv_pct: 'Adv %', vs_52wh: 'vs 52wH' }

export default function Sectors({ onOpenChart }) {
  const [level, setLevel] = useState('sector')
  const [weighting, setWeighting] = useState('cap')
  const [sort, setSort] = useState({ key: '1D', dir: -1 })
  const [open, setOpen] = useState(null)
  const { data: rows } = useFetch(`/api/sectors?level=${level}&weighting=${weighting}`)

  useEffect(() => {
    setOpen(null)
  }, [level, weighting])

  const sorted = useMemo(() => {
    if (!rows) return null
    const { key, dir } = sort
    return [...rows].sort((a, b) => {
      const av = a[key], bv = b[key]
      if (av == null) return 1
      if (bv == null) return -1
      return (av < bv ? -1 : av > bv ? 1 : 0) * dir
    })
  }, [rows, sort])

  const toggleSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'group' ? 1 : -1 }))

  return (
    <>
      <div className="page-head">
        <h1>Sectors</h1>
        <p>Where the money is rotating — click a group to see its stocks, click headers to sort</p>
      </div>

      <div className="toolbar">
        <button className={level === 'sector' ? 'active' : ''} onClick={() => setLevel('sector')}>Sectors</button>
        <button className={level === 'industry' ? 'active' : ''} onClick={() => setLevel('industry')}>Industries</button>
        <span className="spacer" />
        <button className={weighting === 'cap' ? 'active' : ''} onClick={() => setWeighting('cap')}>Cap-weighted</button>
        <button className={weighting === 'equal' ? 'active' : ''} onClick={() => setWeighting('equal')}>Equal-weighted</button>
      </div>

      <div className="card panel">
        {!sorted ? (
          <div className="loading">Computing group returns…</div>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  {SORT_KEYS.map((k) => (
                    <th key={k} className={k === 'group' ? 'left' : ''} onClick={() => toggleSort(k)}>
                      {SORT_LABELS[k] ?? k}
                      {sort.key === k && <span className="arrow">{sort.dir === 1 ? ' ↑' : ' ↓'}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <Fragment key={r.group}>
                    <tr onClick={() => setOpen(open === r.group ? null : r.group)}>
                      <td className="left sym">
                        <span className="dim" style={{ marginRight: 6 }}>{open === r.group ? '▾' : '▸'}</span>
                        {r.group}
                      </td>
                      <td className="num dim">{r.stocks}</td>
                      <td className="num">{fmt.num(r.adv_pct, 0)}%</td>
                      <td className="num dim">{fmt.pct(r.vs_52wh)}</td>
                      {HORIZONS.map((h) => (
                        <td key={h} className="num">
                          <span className="heat" style={heatStyle(r[h], SCALE[h])}>{fmt.pct(r[h])}</span>
                        </td>
                      ))}
                    </tr>
                    {open === r.group && (
                      <tr>
                        <td colSpan={SORT_KEYS.length} style={{ padding: '0 12px' }}>
                          <Members group={r.group} level={level} onOpenChart={onOpenChart} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
