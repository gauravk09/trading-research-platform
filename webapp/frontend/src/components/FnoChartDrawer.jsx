import { useEffect, useMemo, useState } from 'react'
import { fmt, prefetchJson, useFetch } from '../api.js'
import LwChart from './LwChart.jsx'
import { SMA_COLORS, SMA_WIDTH } from './ChartDrawer.jsx'

const TIMEFRAMES = [
  { key: 'daily', label: 'Daily · 3Y', days: 756 },
  { key: 'weekly', label: 'Weekly', days: 756 },
  { key: '5m', label: '5 min · 21D', days: 21 },
]

export default function FnoChartDrawer({ stock, initialTimeframe = 'daily', onClose }) {
  const [timeframe, setTimeframe] = useState(initialTimeframe)
  const config = TIMEFRAMES.find((item) => item.key === timeframe)
  const urlFor = (item) => `/api/fno/chart/${stock.symbol}?timeframe=${item.key}&days=${item.days}`
  const { data, error } = useFetch(urlFor(config))

  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const series = useMemo(() => {
    if (!data?.candles) return null
    const layers = [
      {
        type: 'bars',
        data: data.candles.map((d) => ({
          time: d.time, open: d.open, high: d.high, low: d.low, close: d.close,
        })),
        options: {
          upColor: '#38d996', downColor: '#f05f6f',
          openVisible: true, thinBars: true,
        },
        scaleMargins: { top: 0.06, bottom: 0.22 },
      },
      {
        type: 'histogram',
        data: data.candles.map((d) => ({
          time: d.time,
          value: d.volume,
          color: d.close >= d.open ? 'rgba(56,217,150,.24)' : 'rgba(240,95,111,.24)',
        })),
        options: {
          priceScaleId: 'volume', priceFormat: { type: 'volume' },
          lastValueVisible: false, priceLineVisible: false,
        },
        scaleMargins: { top: 0.82, bottom: 0 },
      },
    ]
    for (const window of data.dma_windows ?? []) {
      const key = `dma${window}`
      layers.push({
        type: 'line',
        data: data.candles.filter((d) => d[key] != null).map((d) => ({ time: d.time, value: d[key] })),
        options: {
          color: SMA_COLORS[`sma${window}`] ?? '#8b93a7',
          lineWidth: SMA_WIDTH[`sma${window}`] ?? 1,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        },
      })
    }
    return layers
  }, [data])

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <section className="drawer fno-drawer" aria-label={`${stock.symbol} chart`}>
        <div className="drawer-head">
          <div>
            <div className="fno-eyebrow">F&O · ENTRY CHART</div>
            <h2>{stock.symbol}</h2>
          </div>
          <span className="fno-chart-price">{fmt.rupee(stock.close)}</span>
          <span className="chip">LOT {fmt.num(stock.lot_size)}</span>
          <button className="close-btn" onClick={onClose}>Close ✕</button>
        </div>
        <div className="company-line">{stock.name} · {stock.sector ?? 'Unclassified'}</div>

        <div className="fno-chart-toolbar">
          <div className="segmented" role="group" aria-label="Chart timeframe">
            {TIMEFRAMES.map((item) => (
              <button
                key={item.key}
                className={timeframe === item.key ? 'active' : ''}
                onPointerEnter={() => prefetchJson(urlFor(item))}
                onFocus={() => prefetchJson(urlFor(item))}
                onClick={() => setTimeframe(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="fno-chart-meta">
            {timeframe === '5m' ? 'Entry view · 21 sessions · projected DMA' : `${config.days} trading days`}
          </div>
        </div>

        <div className="fno-dma-legend" aria-label={timeframe === '5m' ? 'Projected daily moving averages' : 'Daily moving averages'}>
          {(data?.dma_windows ?? [10, 20, 50, 200]).map((window) => (
            <span key={window} style={{ color: SMA_COLORS[`sma${window}`] ?? '#8b93a7' }}>— {window} DMA</span>
          ))}
        </div>
        {error && <div className="empty">Could not load this chart: {error.message}</div>}
        {!data && !error && <div className="loading fno-chart-loading">Loading {timeframe} candles…</div>}
        {series && <LwChart series={series} height={500} />}
        {data && <div className="fno-chart-foot">
          {data.source === 'kite_live' ? '● LIVE KITE' : data.source === 'local_intraday_cache' ? 'Cached intraday fallback' : 'EOD'} · through {String(data.as_of).slice(0, 19)}
        </div>}
      </section>
    </>
  )
}
