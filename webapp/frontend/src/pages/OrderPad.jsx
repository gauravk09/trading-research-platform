import { useEffect, useState } from 'react'
import { fmt, useFetch } from '../api.js'

const SESSION_HELP = {
  weekend: "Weekend — AMOs for Monday's open can be punched now.",
  'pre-open': "Pre-open — D+1-open orders are still valid for today's open.",
  open: "Market open — D+1-open tickets are for TOMORROW; do not chase them intraday. Same-day setups fire at 15:58.",
  'closing-window': 'Closing window (15:20–15:30) — same-day setups are live RIGHT NOW.',
  'after-close': "After close — punch AMOs for the next session's open.",
}

function Ticket({ t, onOpenChart }) {
  const sideColor = t.side === 'SELL' ? 'var(--down)' : 'var(--up)'
  return (
    <div className="card panel" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="sym" style={{ fontSize: 16 }}>{t.symbol}</span>
        <span style={{ color: sideColor, fontWeight: 700 }}>{t.side} {fmt.num(t.qty)}</span>
        <span className="dim" style={{ fontSize: 12.5 }}>· {t.playbook}</span>
        <button style={{ padding: '3px 10px', fontSize: 12 }} onClick={() => onOpenChart(t.symbol)}>
          📈 Chart
        </button>
        <span className="spacer" style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: t.actionable ? 'var(--up)' : 'var(--warn)', fontWeight: 600 }}>
          {t.window}
        </span>
      </div>
      <div style={{ margin: '6px 0', fontSize: 13.5 }}>
        ref {fmt.rupee(t.entry_ref)} · value {fmt.rupee(t.value)} ·{' '}
        <span className="down">stop {fmt.rupee(t.stop)}</span> ({t.stop_pct}% away, risk {fmt.rupee(t.risk_inr)})
      </div>
      <div className="dim" style={{ fontSize: 12 }}>
        stop rule: {t.stop_rule} · exit: {t.exit_rule}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--warn)', marginTop: 4 }}>⚠ {t.note}</div>
      <details style={{ marginTop: 8 }}>
        <summary className="dim" style={{ cursor: 'pointer', fontSize: 12 }}>Punch-in card</summary>
        <pre style={{ background: 'var(--bg-raise)', padding: '10px 14px', borderRadius: 10, fontSize: 12, overflowX: 'auto' }}>
          {t.card}
        </pre>
      </details>
    </div>
  )
}

export default function OrderPad({ onOpenChart }) {
  const [equity, setEquity] = useState(() => Number(localStorage.getItem('equity')) || 1000000)
  const [risk, setRisk] = useState(null) // null until the server's regime knob arrives
  const { data } = useFetch(
    `/api/orderpad?equity=${equity}${risk != null ? `&risk_pct=${risk}` : ''}`,
  )

  useEffect(() => {
    if (risk == null && data) setRisk(data.regime_risk_pct)
  }, [data, risk])

  if (!data) return <div className="loading">Building tonight's tickets…</div>

  return (
    <>
      <div className="page-head">
        <h1>Order Pad</h1>
        <p>
          Tonight's EOD tickets, data date {data.data_date} — this pad <b>prepares</b> orders,
          it never places them. You punch them into Kite yourself.
        </p>
      </div>

      <div className="toolbar">
        <span className="chip">{data.session}</span>
        <span className="dim" style={{ fontSize: 12.5 }}>{SESSION_HELP[data.session]}</span>
        <span className="spacer" />
        <label>Equity ₹ <input type="number" style={{ width: 110 }} value={equity} step={100000} onChange={(e) => setEquity(+e.target.value)} /></label>
        <label>Risk % <input type="number" style={{ width: 64 }} value={risk ?? ''} step={0.1} min={0.1} max={2}
          onChange={(e) => setRisk(e.target.value === '' ? null : Math.max(0.1, +e.target.value))} /></label>
        <span className="dim" style={{ fontSize: 12 }}>regime knob: {data.regime_risk_pct}%</span>
      </div>

      <h3 style={{ margin: '18px 0 10px' }}>🔻 Lone-loser short — the one live-grade book</h3>
      {(data.shorts ?? []).length > 0 ? (
        data.shorts.map((t) => <Ticket key={t.symbol} t={t} onOpenChart={onOpenChart} />)
      ) : (data.shorts_gates_blocked ?? []).length > 0 ? (
        <div className="dim" style={{ fontSize: 13 }}>
          Gates closed — no short tickets tonight. Blocked by: {data.shorts_gates_blocked.join(', ')}
        </div>
      ) : (
        <div className="dim" style={{ fontSize: 13 }}>No 4%-down large caps tonight — nothing to punch.</div>
      )}

      <h3 style={{ margin: '22px 0 10px' }}>🚀 Breakout setup — clean candidates</h3>
      {(data.breakouts ?? []).length > 0 ? (
        data.breakouts.map((t) => <Ticket key={t.symbol} t={t} onOpenChart={onOpenChart} />)
      ) : (
        <div className="dim" style={{ fontSize: 13 }}>No clean breakout candidates in tonight's state file.</div>
      )}

      <div className="dim" style={{ fontSize: 12, marginTop: 16 }}>
        Entry timing comes from each playbook: D+1-open books are punched as AMOs tonight;
        same-day setups must be entered in the 15:20–15:30 window.
      </div>
    </>
  )
}
