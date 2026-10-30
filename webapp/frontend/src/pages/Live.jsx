import { useEffect, useState } from 'react'
import LiveTable from '../components/LiveTable.jsx'

const TABS = [
  { key: 'movers', label: 'Live Movers', url: '/api/live/data' },
  { key: 'user_picks', label: 'My Picks', url: '/api/live/scan?name=user_picks' },
  { key: 'four_pct', label: '4% Breakout', url: '/api/live/scan?name=four_pct' },
  { key: 'breakdown', label: '4% Breakdown', url: '/api/live/scan?name=breakdown' },
  { key: 'anticipation', label: 'Anticipation + Vol', url: '/api/live/scan?name=anticipation' },
  { key: 'reversal', label: 'Reversal Up', url: '/api/live/scan?name=reversal' },
  { key: 'reversal_down', label: 'Reversal Down', url: '/api/live/scan?name=reversal_down' },
  { key: 'four_pct_up_7d', label: '4% Up · 7d', url: '/api/live/scan?name=four_pct_up_7d' },
  { key: 'four_pct_down_7d', label: '4% Down · 7d', url: '/api/live/scan?name=four_pct_down_7d' },
]

const POLL_MS = 5000

export default function Live({ onOpenChart }) {
  const [tab, setTab] = useState('movers')
  const [data, setData] = useState(null)

  useEffect(() => {
    let alive = true
    setData(null)
    const url = TABS.find((t) => t.key === tab).url
    const poll = () =>
      fetch(url)
        .then((r) => r.json())
        .then((d) => alive && setData(d))
        .catch(() => alive && setData({ offline: true }))
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [tab])

  const offline = data?.offline

  return (
    <>
      <div className="page-head">
        <h1>Live</h1>
        <p>Intraday scans over streaming Kite quotes — refreshes every {POLL_MS / 1000}s</p>
      </div>

      <div className="toolbar">
        {TABS.map((t) => (
          <button key={t.key} className={t.key === tab ? 'active' : ''} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {offline ? (
        <div className="card panel">
          <h3>Live scanner is offline</h3>
          <div className="panel-sub" style={{ marginTop: 8, lineHeight: 1.7 }}>
            Start it in a terminal (needs a fresh Kite token, market hours for ticks):
            <pre style={{ background: 'var(--bg-raise)', padding: '10px 14px', borderRadius: 10 }}>
              python src/live_anticipation.py
            </pre>
            This page picks it up automatically once it's running.
          </div>
        </div>
      ) : !data ? (
        <div className="loading">Connecting to live scanner…</div>
      ) : (
        <div className="card panel">
          <div className="panel-sub">
            {data.generated && <>as of {data.generated} IST</>}
            {data.streamed != null && <> · {data.streamed} symbols streaming</>}
            {data.watchlist != null && <> · watchlist of {data.watchlist}</>}
            {data.count != null && <> · {data.count} matches</>}
            {data.market && (
              <> · net4 {data.market.net4 > 0 ? '+' : ''}{data.market.net4} · T2108 {data.market.pct40ma?.toFixed?.(1)}</>
            )}
          </div>
          <LiveTable data={data} onRowClick={(r) => onOpenChart(r.symbol)} />
        </div>
      )}
    </>
  )
}
