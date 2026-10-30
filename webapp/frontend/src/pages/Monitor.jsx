import { useMemo, useState } from 'react'
import { useFetch } from '../api.js'
import LwChart from '../components/LwChart.jsx'

const RANGES = [
  { label: '1Y', days: 252 },
  { label: '3Y', days: 756 },
  { label: '10Y', days: 2600 },
]

const GREEN = 'rgba(46,230,168,0.6)'
const RED = 'rgba(255,93,115,0.6)'

export default function Monitor() {
  const [days, setDays] = useState(252)
  const { data: breadth } = useFetch(`/api/breadth?n_days=${days}`)
  const { data: rhythm } = useFetch('/api/rhythm')
  const { data: risk } = useFetch(`/api/risk_regime?n_days=${days}`)

  const rhythmCharts = useMemo(() => {
    if (!rhythm) return null
    return {
      spread: [{ type: 'line', data: rhythm.spread.map((d) => ({ time: d.date, value: d.leader_spread })), options: { color: '#ffc14d', lineWidth: 2 } }],
      shares: [
        { type: 'line', data: rhythm.shares.map((d) => ({ time: d.date, value: d.w_breakout })), options: { color: '#2ee6a8', lineWidth: 2 } },
        { type: 'line', data: rhythm.shares.map((d) => ({ time: d.date, value: d.w_reversal })), options: { color: '#6d8dff', lineWidth: 2 } },
        { type: 'line', data: rhythm.shares.map((d) => ({ time: d.date, value: d.w_bounce })), options: { color: '#ff5d73', lineWidth: 2 } },
      ],
    }
  }, [rhythm])

  const charts = useMemo(() => {
    if (!breadth) return null
    const line = (key, color, width = 2) => [{
      type: 'line',
      data: breadth.filter((d) => d[key] != null).map((d) => ({ time: d.date, value: d[key] })),
      options: { color, lineWidth: width },
    }]
    const upDown = (upKey, dnKey) => [
      {
        type: 'histogram',
        data: breadth.map((d) => ({ time: d.date, value: d[upKey], color: GREEN })),
      },
      {
        type: 'histogram',
        data: breadth.map((d) => ({ time: d.date, value: -d[dnKey], color: RED })),
      },
    ]
    return [
      { title: '% stocks above 40-DMA (T2108)', sub: 'sub-20 = washout zone · 60+ = strong tape', series: line('pct40ma', '#6d8dff') },
      { title: '10-day 4% ratio', sub: 'breakouts ÷ breakdowns · above 2 bullish, below 0.5 bearish', series: line('ratio10', '#ffc14d') },
      { title: '4% breakouts vs breakdowns', sub: 'daily counts, volume-confirmed', series: upDown('up4', 'dn4') },
      { title: '25% in a quarter — up vs down', sub: 'longer-horizon momentum breadth', series: upDown('up25q', 'dn25q') },
      { title: 'Nifty 500 TI65', sub: '7-DMA ÷ 65-DMA of the index · above 1.00 = uptrend', series: line('ti65_nifty500', '#2ee6a8') },
    ]
  }, [breadth])

  const riskSeries = useMemo(() => risk && [
    { type: 'line', data: risk.map((d) => ({ time: d.date, value: d.p_drop_20d * 100 })), options: { color: '#ff5d73', lineWidth: 2 } },
    { type: 'line', data: risk.map((d) => ({ time: d.date, value: d.baseline_p_drop_20d * 100 })), options: { color: '#8a8f98', lineWidth: 1, lineStyle: 2 } },
  ], [risk])

  return (
    <>
      <div className="page-head">
        <h1>Market Monitor</h1>
        <p>Breadth history — the tape's health, measured six ways</p>
      </div>

      <div className="toolbar">
        {RANGES.map((r) => (
          <button key={r.days} className={days === r.days ? 'active' : ''} onClick={() => setDays(r.days)}>
            {r.label}
          </button>
        ))}
      </div>

      {riskSeries && (
        <div className="card panel" style={{ marginBottom: 16 }}>
          <h3>Crash-risk dial (HMM)</h3>
          <div className="panel-sub">
            chance of a ≥5% Nifty 500 drop within 20 sessions (red) vs its historical average (dashed) · above the line = ELEVATED, half size
          </div>
          <LwChart series={riskSeries} height={230} />
        </div>
      )}

      {!charts ? (
        <div className="loading">Loading breadth history…</div>
      ) : (
        <div className="chart-grid">
          {charts.map((c) => (
            <div key={c.title} className="card panel">
              <h3>{c.title}</h3>
              <div className="panel-sub">{c.sub}</div>
              <LwChart series={c.series} height={230} />
            </div>
          ))}
        </div>
      )}

      {rhythm && (
        <>
          <div className="page-head" style={{ margin: '28px 0 16px' }}>
            <h1 style={{ fontSize: 20 }}>Market Rhythm</h1>
            <p>
              Leader spread 21d avg <b className={rhythm.spread_21d < -1.5 ? 'down' : rhythm.spread_21d > 0 ? 'up' : ''}>{rhythm.spread_21d}%</b>
              {' '}· {rhythm.winners_21d} winners/day — where the 10%-in-5-days moves are coming from
            </p>
          </div>
          <div className="chart-grid">
            <div className="card panel">
              <h3>Leader spread</h3>
              <div className="panel-sub">RS&gt;90 basket 5d return minus universe median · below −1.5 = leaders breaking down</div>
              <LwChart series={rhythmCharts.spread} height={220} />
            </div>
            <div className="card panel">
              <h3>Winner mix (21d share)</h3>
              <div className="panel-sub">breakout green · reversal blue · bounce red — breakout-led tapes are the healthy ones</div>
              <LwChart series={rhythmCharts.shares} height={220} />
            </div>
          </div>
        </>
      )}
    </>
  )
}
