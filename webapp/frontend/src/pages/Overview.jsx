import { useEffect, useMemo, useState } from 'react'
import { fetchJson, fmt, pctClass } from '../api.js'
import LwChart from '../components/LwChart.jsx'
import DataTable from '../components/DataTable.jsx'

const MOVER_COLS = [
  { key: 'symbol', label: 'Symbol', kind: 'sym' },
  { key: 'sector', label: 'Sector', kind: 'text' },
  { key: 'close', label: 'Close', kind: 'rupee' },
  { key: 'chg_pct', label: '1D', kind: 'pct', digits: 2 },
  { key: 'volume_ratio', label: 'Vol ×', kind: 'num', digits: 1 },
  { key: 'rs_rank', label: 'RS', kind: 'num', digits: 0 },
]

function LiveStrip({ onOpenChart }) {
  const [live, setLive] = useState(null)

  useEffect(() => {
    let alive = true
    const poll = () =>
      fetch('/api/live/data')
        .then((r) => r.json())
        .then((d) => alive && setLive(d))
        .catch(() => alive && setLive({ offline: true }))
    poll()
    const id = setInterval(poll, 10000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  if (!live || live.offline || !Array.isArray(live.rows)) return null
  return (
    <div className="card panel" style={{ borderColor: 'rgba(46,230,168,0.35)' }}>
      <h3>
        <span className="up">● Live</span> — watchlist movers beyond ±{live.threshold}%
      </h3>
      <div className="panel-sub">as of {live.generated} IST · watching {live.watchlist} names · click to chart</div>
      <div className="chip-row" style={{ marginBottom: 0 }}>
        {live.rows.length === 0 && <span className="dim">Nothing moving beyond the threshold yet.</span>}
        {live.rows.slice(0, 14).map((r) => (
          <button key={r.symbol} className="stat-chip" onClick={() => onOpenChart(r.symbol)}>
            <span className="sym">{r.symbol}</span>{' '}
            <span className={pctClass(r.chg_pct)}>{fmt.pct(r.chg_pct, 1)}</span>
            {r.rvol >= 2 && <span className="dim"> {r.rvol.toFixed(1)}×</span>}
          </button>
        ))}
      </div>
    </div>
  )
}

const ZONE_COLOR = { CALM: 'rgba(46,230,168,0.10)', ELEVATED: 'rgba(255,193,77,0.28)' }
const DIAL_PANE_HEIGHT = [130]
const RISK_RANGES = [
  { label: '1Y', days: 252 },
  { label: '3Y', days: 756 },
  { label: 'All', days: 8000 },
]

export default function Overview({ onOpenChart }) {
  const [meta, setMeta] = useState(null)
  const [breadth, setBreadth] = useState(null)
  const [universe, setUniverse] = useState(null)
  const [riskDays, setRiskDays] = useState(756)
  const [risk, setRisk] = useState(null)
  const [fnoOnly, setFnoOnly] = useState(false)

  useEffect(() => {
    fetchJson('/api/meta').then(setMeta)
    fetchJson('/api/breadth?n_days=126').then(setBreadth)
    fetchJson('/api/universe').then(setUniverse)
  }, [])

  useEffect(() => {
    fetchJson(`/api/risk_regime?n_days=${riskDays}`).then(setRisk)
  }, [riskDays])

  // Zone shading = a full-height histogram on its own hidden scale, drawn behind the price line.
  const zoneSeries = useMemo(() => {
    if (!risk) return null
    return [
      {
        type: 'histogram',
        data: risk.map((d) => ({ time: d.date, value: 1, color: ZONE_COLOR[d.tier] })),
        options: { priceScaleId: 'zones', priceLineVisible: false, lastValueVisible: false },
        scaleMargins: { top: 0, bottom: 0 },
      },
      {
        type: 'line',
        data: risk.map((d) => ({ time: d.date, value: d.close })),
        options: { color: '#e6e9f2', lineWidth: 2 },
      },
      {
        type: 'line',
        data: risk.filter((d) => d.sma200 != null).map((d) => ({ time: d.date, value: d.sma200 })),
        options: { color: '#ff3b3b', lineWidth: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false },
      },
    ]
  }, [risk])

  // Price + zones in pane 0, crash-risk dial + zones in pane 1 — one shared time axis.
  const stackedSeries = useMemo(() => {
    if (!risk) return null
    return [
      ...zoneSeries,
      { ...zoneSeries[0], pane: 1 },
      {
        pane: 1,
        type: 'line',
        data: risk.map((d) => ({ time: d.date, value: d.baseline_p_drop_20d * 100 })),
        options: { color: '#8b93a7', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false },
      },
      {
        pane: 1,
        type: 'line',
        data: risk.map((d) => ({ time: d.date, value: d.p_drop_20d * 100 })),
        options: { color: '#ff5d73', lineWidth: 2, priceLineVisible: false },
      },
    ]
  }, [risk, zoneSeries])

  const net4Series = useMemo(() => {
    if (!breadth) return null
    return [{
      type: 'histogram',
      data: breadth.map((d) => ({
        time: d.date,
        value: d.net4,
        color: d.net4 >= 0 ? 'rgba(46,230,168,0.6)' : 'rgba(255,93,115,0.6)',
      })),
    }]
  }, [breadth])

  const t2108Series = useMemo(() => {
    if (!breadth) return null
    return [{
      type: 'line',
      data: breadth.map((d) => ({ time: d.date, value: d.pct40ma })),
      options: { color: '#6d8dff', lineWidth: 2 },
    }]
  }, [breadth])

  const liquid = useMemo(
    () => (universe ?? []).filter(
      (r) => r.avg_turnover_cr >= 1 && r.chg_pct != null && (!fnoOnly || r.is_fo),
    ),
    [universe, fnoOnly],
  )
  const moverScope = fnoOnly ? 'F&O stocks' : 'liquid names (T/O ≥ ₹1 Cr)'
  const gainers = useMemo(
    () => [...liquid].sort((a, b) => b.chg_pct - a.chg_pct).slice(0, 8),
    [liquid],
  )
  const losers = useMemo(
    () => [...liquid].sort((a, b) => a.chg_pct - b.chg_pct).slice(0, 8),
    [liquid],
  )

  if (!meta) return <div className="loading">Loading market state…</div>

  return (
    <>
      <div className="page-head">
        <h1>Market Overview</h1>
        <p>NSE end-of-day · as of {meta.as_of} · {fmt.num(meta.n_stocks)} stocks tracked</p>
      </div>

      <LiveStrip onOpenChart={onOpenChart} />

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="label">Risk regime</div>
          <div className="value">
            <span className={`tier-badge tier-${meta.regime_tier}`}>{meta.regime_tier ?? '—'}</span>
          </div>
          <div className="sub">
            crash risk {fmt.prob(meta.p_drop_20d)} vs avg {fmt.prob(meta.baseline_p_drop_20d)}
          </div>
        </div>
        <div className="card stat-card">
          <div className="label">4% Movers Today</div>
          <div className="value num">
            <span className="up">{meta.up4}</span>
            <span className="dim" style={{ fontSize: 18 }}> / </span>
            <span className="down">{meta.dn4}</span>
          </div>
          <div className="sub">net {meta.net4 > 0 ? '+' : ''}{meta.net4} · volume-confirmed</div>
        </div>
        <div className="card stat-card">
          <div className="label">Above 40-DMA</div>
          <div className="value num">{meta.pct40ma}%</div>
          <div className="sub">T2108 breadth — 60+ strong, sub-20 washout</div>
        </div>
        <div className="card stat-card">
          <div className="label">Nifty 500 Trend</div>
          <div className="value num">{meta.ti65_nifty500}</div>
          <div className="sub">TI65 — above 1.00 = uptrend</div>
        </div>
      </div>

      <div className="card panel" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <h3>Nifty 500 · risk zones</h3>
          <div className="toolbar" style={{ margin: 0 }}>
            {RISK_RANGES.map((r) => (
              <button key={r.days} className={riskDays === r.days ? 'active' : ''} onClick={() => setRiskDays(r.days)}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-sub">
          <span className="tier-badge tier-CALM">CALM</span> full size ·{' '}
          <span className="tier-badge tier-ELEVATED">ELEVATED</span> half size — HMM crash-risk dial above its
          historical average. Shading shows risk, not direction. Red line = 200-day SMA.
        </div>
        <div className="panel-sub">
          Lower pane: crash-risk dial — chance of a ≥5% drop within 20 sessions (red, %) vs its historical
          average (dashed). Red above dashed = ELEVATED.
        </div>
        {stackedSeries && <LwChart series={stackedSeries} height={440} paneHeights={DIAL_PANE_HEIGHT} />}
      </div>

      <div className="chart-grid">
        <div className="card panel">
          <h3>Net 4% breakouts − breakdowns</h3>
          <div className="panel-sub">daily, last 6 months</div>
          {net4Series && <LwChart series={net4Series} height={220} />}
        </div>
        <div className="card panel">
          <h3>% stocks above 40-DMA</h3>
          <div className="panel-sub">T2108 — the market's oxygen level</div>
          {t2108Series && <LwChart series={t2108Series} height={220} />}
        </div>
      </div>

      <div className="toolbar" style={{ marginBottom: 12 }}>
        <button className={fnoOnly ? '' : 'active'} onClick={() => setFnoOnly(false)}>All liquid</button>
        <button className={fnoOnly ? 'active' : ''} onClick={() => setFnoOnly(true)}>F&amp;O only</button>
      </div>
      <div className="chart-grid">
        <div className="card panel">
          <h3>Top gainers</h3>
          <div className="panel-sub">{moverScope} · click for chart</div>
          <DataTable rows={gainers} columns={MOVER_COLS} onRowClick={(r) => onOpenChart(r.symbol)} />
        </div>
        <div className="card panel">
          <h3>Top losers</h3>
          <div className="panel-sub">{moverScope} · click for chart</div>
          <DataTable rows={losers} columns={MOVER_COLS} onRowClick={(r) => onOpenChart(r.symbol)} />
        </div>
      </div>
    </>
  )
}
