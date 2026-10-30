import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../api.js'
import './FundStudy.css'

const pct = (value, digits = 2) => value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
const weight = (value) => value == null ? '—' : `${(value * 100).toFixed(2)}%`
const num = (value, digits = 0) => value == null ? '—' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: digits })
const monthLabel = (value) => new Date(value).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })

function LinePlot({ rows, field, color = '#9df5c7', fill = true, format = num }) {
  if (!rows?.length) return <div className="fs-empty">No observations</div>
  const values = rows.map((row) => Number(row[field]) || 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values.map((value, index) => {
    const x = 8 + (index / Math.max(1, values.length - 1)) * 584
    const y = 146 - ((value - min) / span) * 126
    return [x, y]
  })
  const line = points.map(([x, y]) => `${x},${y}`).join(' ')
  const area = `8,154 ${line} 592,154`
  return (
    <div className="fs-line-wrap">
      <svg className="fs-line" viewBox="0 0 600 160" role="img" aria-label={`${field} over time`}>
        {[28, 70, 112, 154].map((y) => <line key={y} x1="8" x2="592" y1={y} y2={y} className="fs-grid" />)}
        {fill && <polygon points={area} fill={color} opacity="0.08" />}
        <polyline points={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />
        {points.map(([x, y], index) => (
          <circle key={index} cx={x} cy={y} r="3" fill={color}>
            <title>{monthLabel(rows[index].month)} · {format(values[index])}</title>
          </circle>
        ))}
      </svg>
      <div className="fs-chart-scale"><span>{monthLabel(rows[0].month)}</span><span>{monthLabel(rows.at(-1).month)}</span></div>
    </div>
  )
}

function Metric({ label, value, note, tone = '' }) {
  return <div className={`fs-metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>
}

function CompanyDetail({ symbol, years, onClose }) {
  const [state, setState] = useState({ data: null, error: null })
  useEffect(() => {
    let alive = true
    setState({ data: null, error: null })
    fetchJson(`/api/fund-study/company/${symbol}?years=${years}`, { force: true })
      .then((data) => alive && setState({ data, error: null }))
      .catch((error) => alive && setState({ data: null, error }))
    return () => { alive = false }
  }, [symbol, years])
  const data = state.data
  return (
    <div className="fs-detail-shade" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="fs-detail">
        <button className="fs-close" onClick={onClose} aria-label="Close">×</button>
        <div className="fs-eyebrow">Company history</div>
        <h2>{symbol}</h2>
        {state.error && <div className="fs-error">Could not load company history.</div>}
        {!data && !state.error && <div className="fs-loading">Loading history…</div>}
        {data && <>
          <div className="fs-detail-statline">
            <span>{data.history.length} disclosed months</span>
            <span>{data.events.length} material changes</span>
          </div>
          <h3>Portfolio weight</h3>
          <LinePlot rows={data.history} field="weight" color="#f7ca75" format={weight} />
          <h3>Material disclosure events</h3>
          <div className="fs-event-list">
            {data.events.length === 0 && <div className="fs-empty">No ≥10 bps changes in this window.</div>}
            {data.events.slice().reverse().map((event, index) => (
              <div className="fs-event" key={`${event.month}-${index}`}>
                <span className={`fs-kind ${event.delta_weight > 0 ? 'up' : 'down'}`}>{event.change_kind}</span>
                <div><strong>{monthLabel(event.month)}</strong><small>{pct(event.delta_weight)} weight change</small></div>
                <div className="fs-event-return"><strong>{pct(event.abnormal_20d)}</strong><small>20d abnormal</small></div>
              </div>
            ))}
          </div>
        </>}
      </aside>
    </div>
  )
}

export default function FundStudy() {
  const [years, setYears] = useState(3)
  const [tab, setTab] = useState('behavior')
  const [state, setState] = useState({ data: null, error: null })
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    let alive = true
    setState({ data: null, error: null })
    fetchJson(`/api/fund-study/overview?years=${years}`, { force: true, ttlMs: 0 })
      .then((data) => alive && setState({ data, error: null }))
      .catch((error) => alive && setState({ data: null, error }))
    return () => { alive = false }
  }, [years])

  const data = state.data
  const activeCompanies = useMemo(() => {
    if (!data) return []
    const query = search.trim().toUpperCase()
    return data.companies.filter((company) => company.latest_weight > 0 && (!query || company.symbol.includes(query)))
  }, [data, search])

  return (
    <div className="fs-page">
      <header className="fs-header">
        <a className="fs-back" href="/">← Trading desk</a>
        <div className="fs-brand"><span className="fs-brand-mark">F</span><span>Fund Behaviour Lab</span></div>
        <div className="fs-header-note">Independent research view</div>
      </header>

      <main className="fs-content">
        <section className="fs-hero">
          <div>
            <div className="fs-eyebrow">Longitudinal fund study · Monthly disclosures</div>
            <h1>SBI Contra Fund</h1>
            <p>How the fund reallocates capital across companies—and what prices do after those changes become public.</p>
          </div>
          <div className="fs-years" aria-label="Study window">
            <span>Study window</span>
            {[1, 2, 3, 5].map((option) => <button key={option} className={years === option ? 'active' : ''} onClick={() => setYears(option)}>{option}Y</button>)}
          </div>
        </section>

        {state.error && <div className="fs-error">The study API is unavailable. Start the local dashboard server and retry.</div>}
        {!data && !state.error && <div className="fs-loading fs-loading-page"><span />Rebuilding the {years}-year study…</div>}

        {data && <>
          <div className="fs-coverage">
            <span className="fs-live-dot" /> {data.coverage.months} monthly portfolios · {monthLabel(data.coverage.start)} to {monthLabel(data.coverage.end)}
            <span>Snapshot changes ≠ exact trade dates</span>
          </div>

          <section className="fs-metrics">
            <Metric label="Latest equity book" value={`₹${num(data.headline.equity_value_cr)} Cr`} note="Disclosed listed-equity value" />
            <Metric label="Companies held" value={num(data.headline.stock_count)} note="Latest monthly portfolio" />
            <Metric label="Median live tenure" value={`${num(data.headline.median_current_tenure_months)} mo`} note="Consecutive observed months" />
            <Metric label="Monthly change proxy" value={weight(data.headline.latest_turnover_proxy)} note="½ × absolute weight changes" />
          </section>

          <nav className="fs-tabs">
            {[['behavior', 'Investment behaviour'], ['impact', 'Price effect'], ['companies', 'Company explorer'], ['method', 'Method']].map(([key, label]) => (
              <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>
            ))}
          </nav>

          {tab === 'behavior' && <section className="fs-grid-layout">
            <article className="fs-card fs-wide">
              <div className="fs-card-head"><div><span>Portfolio evolution</span><h2>Equity book value</h2></div><strong>₹ Cr</strong></div>
              <LinePlot rows={data.monthly} field="equity_value_cr" />
            </article>
            <article className="fs-card">
              <div className="fs-card-head"><div><span>Breadth</span><h2>Number of companies</h2></div><strong>{data.headline.stock_count}</strong></div>
              <LinePlot rows={data.monthly} field="stock_count" color="#7eb9ff" fill={false} />
            </article>
            <article className="fs-card">
              <div className="fs-card-head"><div><span>Latest month</span><h2>Allocation changes</h2></div></div>
              <div className="fs-flow-row"><div><b>{data.monthly.at(-1).positions_added}</b><span>weights raised</span></div><div><b>{data.monthly.at(-1).positions_trimmed}</b><span>weights cut</span></div><div><b>{data.monthly.at(-1).entries}</b><span>entries</span></div><div><b>{data.monthly.at(-1).exits}</b><span>exits</span></div></div>
            </article>
            <article className="fs-card fs-wide">
              <div className="fs-card-head"><div><span>Latest disclosure</span><h2>Largest weight changes</h2></div><small>Click a company for its full history</small></div>
              <div className="fs-movers">
                <div><h3>Added</h3>{data.latest_additions.slice(0, 6).map((item) => <button key={item.symbol} onClick={() => setSelected(item.symbol)}><span>{item.symbol}</span><b className="up">{pct(item.delta_weight)}</b></button>)}</div>
                <div><h3>Trimmed</h3>{data.latest_trims.slice(0, 6).map((item) => <button key={item.symbol} onClick={() => setSelected(item.symbol)}><span>{item.symbol}</span><b className="down">{pct(item.delta_weight)}</b></button>)}</div>
              </div>
            </article>
          </section>}

          {tab === 'impact' && <section className="fs-impact-layout">
            <article className="fs-card fs-impact-intro">
              <div className="fs-eyebrow">Event study</div>
              <h2>Does disclosed buying move prices?</h2>
              <p>Each event is a portfolio-weight change of at least 10 basis points. Returns begin after the disclosure becomes available and are measured against Nifty 500.</p>
              <div className="fs-formula">signed effect = direction × (stock return − benchmark return)</div>
            </article>
            <div className="fs-effect-grid">
              {data.effects.map((effect) => <article className="fs-effect" key={effect.horizon}>
                <span>{effect.horizon} trading day{effect.horizon > 1 ? 's' : ''}</span>
                <strong className={effect.mean >= 0 ? 'up' : 'down'}>{pct(effect.mean)}</strong>
                <div className="fs-effect-track"><i style={{ width: `${Math.min(100, Math.abs(effect.mean || 0) * 2500)}%` }} /></div>
                <dl><div><dt>Events</dt><dd>{effect.n}</dd></div><div><dt>Aligned</dt><dd>{effect.positive_rate == null ? '—' : `${(effect.positive_rate * 100).toFixed(0)}%`}</dd></div><div><dt>t-stat</dt><dd>{effect.t_stat?.toFixed(2) ?? '—'}</dd></div></dl>
              </article>)}
            </div>
            <article className="fs-card fs-wide">
              <div className="fs-card-head"><div><span>Interpretation</span><h2>Evidence, not a causal claim</h2></div></div>
              <div className="fs-findings">
                <p><b>Positive signed return</b> means additions outperformed—or trims underperformed—the benchmark after disclosure.</p>
                <p><b>Statistical confidence</b> is weak when |t-stat| is below 2, even if the average effect looks large.</p>
                <p><b>Disclosure timing</b> avoids look-ahead bias, but cannot prove the fund caused the move.</p>
              </div>
            </article>
          </section>}

          {tab === 'companies' && <section className="fs-card fs-company-card">
            <div className="fs-company-head"><div><span>Current portfolio</span><h2>Company explorer</h2></div><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search symbol…" /></div>
            <div className="fs-table-wrap"><table className="fs-table"><thead><tr><th>Company</th><th>Weight</th><th>Latest Δ</th><th>Tenure</th><th>Add / trim months</th><th>20d signed effect</th></tr></thead><tbody>
              {activeCompanies.map((company) => <tr key={company.symbol} onClick={() => setSelected(company.symbol)} tabIndex="0" onKeyDown={(event) => event.key === 'Enter' && setSelected(company.symbol)}><td><b>{company.symbol}</b><small>{num(company.event_count)} material events</small></td><td>{weight(company.latest_weight)}</td><td className={company.delta_weight >= 0 ? 'up' : 'down'}>{pct(company.delta_weight)}</td><td>{company.current_tenure_months} mo</td><td>{company.adds} / {company.trims}</td><td className={company.mean_signed_20d >= 0 ? 'up' : 'down'}>{pct(company.mean_signed_20d)}</td></tr>)}
            </tbody></table></div>
          </section>}

          {tab === 'method' && <section className="fs-method-grid">
            <article className="fs-card"><span>01</span><h2>Observe</h2><p>Use SBI’s complete month-end scheme portfolio, mapped to NSE symbols by ISIN.</p></article>
            <article className="fs-card"><span>02</span><h2>Compare</h2><p>Calculate company weights and changes between consecutive available monthly snapshots.</p></article>
            <article className="fs-card"><span>03</span><h2>Gate</h2><p>Assume the portfolio becomes usable ten calendar days after month-end. Missing source months remain gaps.</p></article>
            <article className="fs-card"><span>04</span><h2>Measure</h2><p>Compare post-disclosure stock returns with Nifty 500 over 1, 5, 20 and 60 sessions.</p></article>
            <article className="fs-card fs-method-note"><h2>Limits</h2><p>{data.method.note} Weight changes also contain market-price movement and fund subscriptions/redemptions. Treat the results as observational evidence, not execution reconstruction or investment advice.</p></article>
          </section>}
        </>}
      </main>
      {selected && <CompanyDetail symbol={selected} years={years} onClose={() => setSelected(null)} />}
    </div>
  )
}
