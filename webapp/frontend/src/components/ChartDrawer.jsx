import { useEffect, useMemo, useState } from 'react'
import { fmt, pctClass, useFetch } from '../api.js'
import LwChart from './LwChart.jsx'

const RANGES = [
  { label: '3M', days: 63 },
  { label: '6M', days: 126 },
  { label: '1Y', days: 252 },
  { label: '2Y', days: 504 },
]

export const SMA_COLORS = { sma10: '#22c55e', sma20: '#3b82f6', sma50: '#facc15', sma200: '#ef4444' }
export const SMA_WIDTH = { sma200: 3 } // Long-term trend line; others use width 1.

export default function ChartDrawer({ symbol, onClose }) {
  const [days, setDays] = useState(252)
  const { data: detail, error } = useFetch(`/api/stock/${symbol}?n_days=${days}`)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const series = useMemo(() => {
    if (!detail) return null
    const c = detail.candles
    const out = [
      {
        type: 'bars',
        data: c.map((d) => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close })),
        options: {
          upColor: '#2ee6a8', downColor: '#ff5d73',
          openVisible: true, thinBars: true,
        },
        scaleMargins: { top: 0.05, bottom: 0.22 },
      },
      {
        type: 'histogram',
        data: c.map((d) => ({
          time: d.date,
          value: d.volume,
          color: d.close >= d.open ? 'rgba(46,230,168,0.30)' : 'rgba(255,93,115,0.30)',
        })),
        options: { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false },
        scaleMargins: { top: 0.82, bottom: 0 },
      },
    ]
    for (const key of Object.keys(SMA_COLORS)) {
      out.push({
        type: 'line',
        data: c.filter((d) => d[key] != null).map((d) => ({ time: d.date, value: d[key] })),
        options: { color: SMA_COLORS[key], lineWidth: SMA_WIDTH[key] ?? 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false },
      })
    }
    return out
  }, [detail])

  const p = detail?.profile ?? {}

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-head">
          <h2>{symbol}</h2>
          {p.close != null && <span className="num" style={{ fontSize: 20 }}>{fmt.rupee(p.close)}</span>}
          {p.chg_pct != null && (
            <span className={`num ${pctClass(p.chg_pct)}`} style={{ fontSize: 16, fontWeight: 600 }}>
              {fmt.pct(p.chg_pct, 2)}
            </span>
          )}
          {p.is_fo && <span className="chip">F&O</span>}
          {detail?.live && <span className="chip" style={{ color: 'var(--up)' }}>● LIVE</span>}
          <button className="close-btn" onClick={onClose}>Close ✕</button>
        </div>
        {p.name && (
          <div className="company-line">
            {p.name} · {p.sector ?? '—'} · Mcap {fmt.compact(p.mcap_cr)}
          </div>
        )}
        <div className="chip-row">
          <span className="stat-chip"><span className="k">ADR</span>{fmt.num(p.adr_pct, 2)}%</span>
          <span className="stat-chip"><span className="k">T/O</span>₹{fmt.num(p.avg_turnover_cr, 1)} Cr</span>
          <span className="stat-chip"><span className="k">RS</span>{fmt.num(p.rs_rank, 0)}</span>
          <span className="stat-chip"><span className="k">1M</span><span className={pctClass(p.r1mo_pct)}>{fmt.pct(p.r1mo_pct)}</span></span>
          <span className="stat-chip"><span className="k">3M</span><span className={pctClass(p.r3mo_pct)}>{fmt.pct(p.r3mo_pct)}</span></span>
          <span className="stat-chip"><span className="k">6M</span><span className={pctClass(p.r6mo_pct)}>{fmt.pct(p.r6mo_pct)}</span></span>
          <span className="stat-chip"><span className="k">52wH</span><span className={pctClass(p.pct_from_52w_high)}>{fmt.pct(p.pct_from_52w_high)}</span></span>
          <span className="stat-chip"><span className="k">TI65</span>{fmt.num(p.ti65, 3)}</span>
        </div>
        <div className="toolbar">
          {RANGES.map((r) => (
            <button key={r.days} className={days === r.days ? 'active' : ''} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
          <span className="spacer" />
          <span className="dim" style={{ fontSize: 12 }}>
            <span style={{ color: SMA_COLORS.sma10 }}>— 10</span>{' '}
            <span style={{ color: SMA_COLORS.sma20 }}>— 20</span>{' '}
            <span style={{ color: SMA_COLORS.sma50 }}>— 50</span>{' '}
            <span style={{ color: SMA_COLORS.sma200 }}>— 200 SMA</span>
          </span>
        </div>
        {error && <div className="empty">Could not load {symbol}: {String(error.message ?? error)}</div>}
        {!detail && !error && <div className="loading">Loading {symbol}…</div>}
        {series && <LwChart series={series} height={460} />}
      </div>
    </>
  )
}
