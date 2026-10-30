import { useMemo, useState } from 'react'
import { fmt, pctClass } from '../api.js'

// Column spec: { key, label, kind: 'sym'|'text'|'pct'|'num'|'rupee'|'compact', digits }
export default function DataTable({ rows, columns, onRowClick, maxRows = 300 }) {
  const [sort, setSort] = useState(null) // { key, dir }

  const sorted = useMemo(() => {
    if (!sort) return rows
    const { key, dir } = sort
    return [...rows].sort((a, b) => {
      const av = a[key], bv = b[key]
      if (av == null) return 1
      if (bv == null) return -1
      // Compare numerically when both sides are numbers (or numeric strings),
      // else fall back to locale string compare — a lexicographic sort would
      // otherwise order "12000" before "9000".
      const an = typeof av === 'number' ? av : Number(av)
      const bn = typeof bv === 'number' ? bv : Number(bv)
      const cmp =
        !Number.isNaN(an) && !Number.isNaN(bn)
          ? an - bn
          : String(av).localeCompare(String(bv))
      return cmp * dir
    })
  }, [rows, sort])

  const toggleSort = (key) =>
    setSort((s) => (s?.key === key ? { key, dir: -s.dir } : { key, dir: -1 }))

  const cell = (row, col) => {
    const v = row[col.key]
    switch (col.kind) {
      case 'sym':
        return (
          <td key={col.key} className="left">
            <span className="sym">{v}</span>
            {row.name && <div className="sym-sub">{row.name}</div>}
          </td>
        )
      case 'text':
        return <td key={col.key} className="left dim">{v ?? '—'}</td>
      case 'pct':
        return <td key={col.key} className={`num ${pctClass(v)}`}>{fmt.pct(v, col.digits ?? 1)}</td>
      case 'rupee':
        return <td key={col.key} className="num">{fmt.rupee(v)}</td>
      case 'compact':
        return <td key={col.key} className="num dim">{fmt.compact(v)}</td>
      default:
        return <td key={col.key} className="num">{fmt.num(v, col.digits ?? 1)}</td>
    }
  }

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.kind === 'sym' || c.kind === 'text' ? 'left' : ''}
                onClick={() => toggleSort(c.key)}
              >
                {c.label}
                {sort?.key === c.key && (
                  <span className="arrow">{sort.dir === 1 ? ' ↑' : ' ↓'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, maxRows).map((row, i) => (
            <tr key={row.symbol ?? i} onClick={() => onRowClick?.(row)}>
              {columns.map((c) => cell(row, c))}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > maxRows && (
        <div className="empty">Showing first {maxRows} of {sorted.length} — sort or filter to narrow.</div>
      )}
    </div>
  )
}
