import { fmt, pctClass } from '../api.js'

// Renders a live-scanner table generically from the server's own column spec.
// The live server ships {columns: [{key, label}], rows: [...]} — we only add
// colouring for the well-known numeric keys.
const PCT_KEYS = new Set(['chg_pct', 'since_pct', 'gap_pct'])
const HOT_KEYS = new Set(['rvol'])

function LiveCell({ col, value }) {
  if (value == null) return <td className="num dim">—</td>
  if (PCT_KEYS.has(col.key)) {
    return <td className={`num ${pctClass(value)}`}>{fmt.pct(value, 2)}</td>
  }
  if (HOT_KEYS.has(col.key)) {
    const hot = value >= 3 ? 'up' : value >= 2 ? '' : 'dim'
    return <td className={`num ${hot}`}>{value.toFixed(2)}×</td>
  }
  if (col.key === 'symbol') return <td className="left sym">{value}</td>
  if (col.key === 'signal') {
    const cls = value === 'TAKE' ? 'up' : value === 'SKIP' ? 'down' : 'dim'
    return <td className={`left ${cls}`} style={{ fontWeight: 700 }}>{value}</td>
  }
  if (typeof value === 'number') return <td className="num">{fmt.num(value, 2)}</td>
  return <td className="left dim">{String(value)}</td>
}

export default function LiveTable({ data, onRowClick }) {
  if (!data?.rows?.length || !Array.isArray(data.columns)) {
    return <div className="empty">Nothing matching right now.</div>
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {data.columns.map((c) => (
              <th key={c.key} className={c.key === 'symbol' || c.key === 'signal' ? 'left' : ''}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={row.symbol ?? i} onClick={() => onRowClick?.(row)}>
              {data.columns.map((c) => <LiveCell key={c.key} col={c} value={row[c.key]} />)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
