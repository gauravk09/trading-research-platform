import { useEffect, useState } from 'react'
import { fetchJson } from './api.js'
import Live from './pages/Live.jsx'
import Overview from './pages/Overview.jsx'
import Brief from './pages/Brief.jsx'
import Setups from './pages/Setups.jsx'
import Screener from './pages/Screener.jsx'
import Scans from './pages/Scans.jsx'
import Monitor from './pages/Monitor.jsx'
import Sectors from './pages/Sectors.jsx'
import Strategies from './pages/Strategies.jsx'
import OrderPad from './pages/OrderPad.jsx'
import Docs from './pages/Docs.jsx'
import TradeBank from './pages/TradeBank.jsx'
import FnoDashboard from './pages/FnoDashboard.jsx'
import MagicFormula from './pages/MagicFormula.jsx'
import FundStudy from './pages/FundStudy.jsx'
import ChartDrawer from './components/ChartDrawer.jsx'

const PAGES = [
  { key: 'overview', icon: '◉', label: 'Overview', el: Overview },
  { key: 'live', icon: '●', label: 'Live', el: Live },
  { key: 'brief', icon: '☀', label: 'Daily Brief', el: Brief },
  { key: 'setups', icon: '🎯', label: 'Setups', el: Setups },
  { key: 'screener', icon: '⌕', label: 'Screener', el: Screener },
  { key: 'magic-formula', icon: '◆', label: 'Magic Formula', el: MagicFormula },
  { key: 'fno', icon: '↗', label: 'F&O Board', el: FnoDashboard },
  { key: 'scans', icon: '⚡', label: 'Scans', el: Scans },
  { key: 'monitor', icon: '〰', label: 'Market Monitor', el: Monitor },
  { key: 'sectors', icon: '▦', label: 'Sectors', el: Sectors },
  { key: 'strategies', icon: '⚔', label: 'Strategies', el: Strategies },
  { key: 'tradebank', icon: '🗂', label: 'Trade Bank', el: TradeBank },
  { key: 'orderpad', icon: '🧾', label: 'Order Pad', el: OrderPad },
  { key: 'docs', icon: '📖', label: 'How Scans Work', el: Docs },
]

export default function App() {
  return window.location.pathname === '/fund-study' ? <FundStudy /> : <TradingDesk />
}

function TradingDesk() {
  const requestedPage = new URLSearchParams(window.location.search).get('page')
  const initialPage = PAGES.some((candidate) => candidate.key === requestedPage) ? requestedPage : 'overview'
  const [page, setPage] = useState(initialPage)
  const [chartSymbol, setChartSymbol] = useState(null)
  const [freshness, setFreshness] = useState(null)
  useEffect(() => { fetchJson('/api/meta').then((m) => setFreshness(m.freshness)).catch(() => {}) }, [])
  const Page = PAGES.find((p) => p.key === page).el

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          Trading<span>Desk</span>
        </div>
        {PAGES.map((p) => (
          <button
            key={p.key}
            className={`nav-item ${page === p.key ? 'active' : ''}`}
            onClick={() => setPage(p.key)}
          >
            <span className="icon">{p.icon}</span>
            {p.label}
          </button>
        ))}
        <a className="nav-item" href="/fund-study">
          <span className="icon">◌</span>
          Fund Study
        </a>
        <div className="sidebar-foot">
          NSE · 2,100+ stocks
          <br />
          EOD data, updated nightly
        </div>
      </aside>
      <main className="main">
        {freshness?.stale && <div className="stale-banner">⛔ STALE TRADING STATE — data is {freshness.data_date || 'missing'} ({freshness.trading_days_old ?? 'unknown'} trading days old). Setups, strategies, and order tickets are disabled until the EOD update succeeds.</div>}
        <Page onOpenChart={setChartSymbol} />
      </main>
      {chartSymbol && (
        <ChartDrawer symbol={chartSymbol} onClose={() => setChartSymbol(null)} />
      )}
    </div>
  )
}
