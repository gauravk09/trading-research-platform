import { useEffect, useState } from 'react'
import { fetchJson, fmt } from '../api.js'

function GateLight({ g }) {
  const color = g.ok == null ? 'var(--text-faint)' : g.ok ? 'var(--up)' : 'var(--down)'
  return (
    <span className="stat-chip" style={{ borderColor: `${color}44` }}>
      <span style={{ color }}>{g.ok == null ? '○' : g.ok ? '●' : '●'}</span>{' '}
      <span className="k">{g.label}</span>
      <span className="num">{g.value ?? '—'}</span>
    </span>
  )
}

const STATUS_COLOR = {
  PRODUCTION_CANDIDATE: 'var(--up)',
  CONDITIONAL_RESEARCH: 'var(--warn)',
  REJECTED: 'var(--down)',
  RESEARCH_ONLY: 'var(--text-dim)',
}

export default function Strategies() {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetchJson('/api/strategies').then(setData)
  }, [])

  if (!data) return <div className="loading">Loading strategy book…</div>
  const m = data.market ?? {}

  return (
    <>
      <div className="page-head">
        <h1>Strategy Book</h1>
        <p>
          Tape: net4 {m.net4 != null ? `${m.net4 > 0 ? '+' : ''}${m.net4}` : '—'} ·
          T2108 {fmt.num(m.pct40ma, 1)} · Nifty TI65 {fmt.num(m.ti65_nifty, 3)}
          {m.date ? ` · ${String(m.date).slice(0, 10)}` : ''}
        </p>
      </div>

      {data.strategies.map((s) => (
        <div key={s.id} className="card panel">
          <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <h3 style={{ fontSize: 16 }}>{s.name}</h3>
            <span className="chip" style={{ color: s.direction === 'SHORT' ? 'var(--down)' : 'var(--up)' }}>
              {s.direction}
            </span>
            <span className="chip" style={{ color: STATUS_COLOR[s.status] ?? 'var(--text-dim)' }}>{s.status}</span>
            <span className="chip" style={{ color: s.actionable ? 'var(--up)' : 'var(--warn)' }}>
              {s.actionable ? 'ACTIONABLE' : 'NOT TRADEABLE'}
            </span>
            <span className="spacer" style={{ flex: 1 }} />
            {s.doc_url && <a href={s.doc_url} target="_blank" rel="noreferrer" style={{ fontSize: 12.5 }}>Playbook ↗</a>}
          </div>
          <div className="panel-sub" style={{ marginTop: 4 }}>{s.universe}</div>
          <div style={{ fontSize: 13.5, margin: '8px 0' }}>{s.rule}</div>
          <div className="dim" style={{ fontSize: 12.5, marginBottom: 10 }}>{s.stats}</div>
          {s.gates.length > 0 && (
            <div className="chip-row" style={{ marginBottom: 8 }}>
              {s.gates.map((g) => <GateLight key={g.key} g={g} />)}
            </div>
          )}
          {s.caveats.length > 0 && (
            <div className="dim" style={{ fontSize: 12 }}>
              {s.caveats.map((c, i) => <div key={i}>⚠ {c}</div>)}
            </div>
          )}
        </div>
      ))}
    </>
  )
}
