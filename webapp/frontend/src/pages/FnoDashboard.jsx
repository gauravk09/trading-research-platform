import { useEffect, useMemo, useState } from 'react'
import { fmt, pctClass, prefetchJson, useFetch, usePollingFetch } from '../api.js'
import FnoChartDrawer from '../components/FnoChartDrawer.jsx'

const COLUMNS = [
  { key: 'symbol', label: 'Stock', align: 'left' }, { key: 'sector', label: 'Sector', align: 'left' },
  { key: 'lot_size', label: 'Lot' }, { key: 'close', label: 'LTP' },
  { key: 'day_move_pct', label: 'Day', help: 'Live move from previous close; latest EOD move outside market hours' },
  { key: 'from_low_pct', label: 'From Low', help: 'Live move from today’s intraday low' },
  { key: 'rs_all', label: 'RS · All' }, { key: 'rs_fo', label: 'RS · F&O' },
  { key: 'rs_index', label: 'Index RS' }, { key: 'rs_sector', label: 'Sector RS' },
  { key: 'adr_pct', label: 'ADR' }, { key: 'atm_iv', label: 'ATM IV' },
  { key: 'implied_day_pct', label: 'Implied Move' },
  { key: 'r5d_pct', label: '5D', chart: 'daily' }, { key: 'r10d_pct', label: '10D', chart: 'daily' },
  { key: 'r50d_pct', label: '50D', chart: 'daily' }, { key: 'r200d_pct', label: '200D', chart: 'weekly' },
]

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
const average = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
const expectedMove = (row) => row.implied_day_pct || row.adr_pct || null
const moveRatio = (row) => expectedMove(row) ? row.day_move_pct / expectedMove(row) : 0
const requestedView = typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('mode')
const INITIAL_VIEW = ['cockpit', 'movers', 'bases', 'table'].includes(requestedView) ? requestedView : 'cockpit'

function RsPill({ value }) {
  const band = value >= 80 ? 'elite' : value >= 60 ? 'strong' : value < 40 ? 'weak' : 'neutral'
  return <span className={`rs-pill ${band}`}>{fmt.num(value, 0)}</span>
}

function setupFor(row) {
  const ratio = moveRatio(row)
  if (row.rs_fo >= 60 && ratio >= .25) return { label: 'Leader expanding', tone: 'positive', short: 'LEADER' }
  if (row.rs_fo >= 60 && ratio <= -.2) return { label: 'Leader pulling back', tone: 'pullback', short: 'PULLBACK' }
  if (row.rs_fo <= 40 && ratio <= -.25) return { label: 'Laggard breaking', tone: 'negative', short: 'LAGGARD' }
  if (row.rs_fo <= 40 && ratio >= .2) return { label: 'Weak-name bounce', tone: 'bounce', short: 'BOUNCE' }
  return { label: Math.abs(ratio) >= 1 ? 'Range expansion' : 'No edge yet', tone: 'neutral', short: Math.abs(ratio) >= 1 ? 'EXPANSION' : 'NEUTRAL' }
}

function focusScore(row) {
  const rsEdge = Math.abs((row.rs_fo ?? 50) - 50) / 50
  const aligned = Math.sign(row.day_move_pct ?? 0) === Math.sign((row.rs_fo ?? 50) - 50)
  return Math.abs(moveRatio(row)) * 55 + rsEdge * 30 + (aligned ? 15 : 6)
}

function MarketRead({ meta, rows }) {
  const priced = rows.filter((row) => row.day_move_pct != null)
  const advancing = priced.filter((row) => row.day_move_pct > 0).length
  const breadth = priced.length ? advancing / priced.length * 100 : null
  const expansion = priced.filter((row) => Math.abs(moveRatio(row)) >= 1).length
  const leaders = priced.filter((row) => row.rs_fo >= 70 && row.day_move_pct > 0).length
  const laggards = priced.filter((row) => row.rs_fo <= 30 && row.day_move_pct < 0).length
  const participation = breadth >= 58 && (meta?.pct40ma ?? 50) >= 50 ? 'Broad risk-on' : breadth <= 42 && (meta?.pct40ma ?? 50) < 50 ? 'Broad risk-off' : 'Selective / two-way'
  const tone = participation === 'Broad risk-on' ? 'positive' : participation === 'Broad risk-off' ? 'negative' : 'mixed'
  const sentence = participation === 'Broad risk-on'
    ? `${fmt.num(breadth, 0)}% of F&O names are advancing; leadership is participating. Prefer strength that holds above its expected range.`
    : participation === 'Broad risk-off'
      ? `Only ${fmt.num(breadth, 0)}% of F&O names are advancing; weakness is broad. Treat bounces in low-RS names as suspect.`
      : `Participation is split at ${fmt.num(breadth, 0)}% advancing. Follow sector rotation and demand stock-specific expansion.`
  return <section className={`fno-market-read ${tone}`}>
    <div className="fno-thesis"><span>DESK READ</span><strong>{participation}</strong><p>{sentence}</p></div>
    <div className="fno-pulse-metrics">
      <div><small>MARKET RISK</small><strong>{meta?.regime_tier ?? '—'}</strong><span>{meta?.p_drop_20d == null ? 'model unavailable' : `${fmt.prob(meta.p_drop_20d)} 20D drop risk`}</span></div>
      <div><small>F&O BREADTH</small><strong>{fmt.num(breadth, 0)}%</strong><span>{advancing} up / {priced.length - advancing} not up</span></div>
      <div><small>RANGE EXPANSION</small><strong>{expansion}</strong><span>outside 1× implied / ADR</span></div>
      <div><small>CONFIRMATION</small><strong>{leaders} / {laggards}</strong><span>leaders up / laggards down</span></div>
    </div>
  </section>
}

function ConfluenceMap({ rows, selectedSymbol, onSelect }) {
  const [hoveredSymbol, setHoveredSymbol] = useState(null)
  const width = 780, height = 390, left = 52, right = 20, top = 24, bottom = 42
  const plotWidth = width - left - right, plotHeight = height - top - bottom
  const points = rows.filter((row) => row.rs_fo != null && row.day_move_pct != null).map((row) => ({
    ...row, ratio: moveRatio(row), x: left + clamp(row.rs_fo, 0, 100) / 100 * plotWidth,
    y: top + (2 - clamp(moveRatio(row), -2, 2)) / 4 * plotHeight,
  }))
  const labelled = new Set([...points].sort((a, b) => focusScore(b) - focusScore(a)).slice(0, 10).map((row) => row.symbol))
  const hovered = points.find((row) => row.symbol === hoveredSymbol)
  return <article className="fno-panel fno-map-panel">
    <header><div><span className="fno-panel-kicker">MARKET MAP</span><h2>Strength × move surprise</h2></div><p>Day move ÷ ATM-implied 1D move <span>· ADR fallback</span></p></header>
    <div className="fno-map-wrap"><svg className="fno-confluence-map" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="F&O relative strength versus move surprise map">
      <rect x={left} y={top} width={plotWidth / 2} height={plotHeight / 2} className="map-zone bounce" /><rect x={left + plotWidth / 2} y={top} width={plotWidth / 2} height={plotHeight / 2} className="map-zone leader" />
      <rect x={left} y={top + plotHeight / 2} width={plotWidth / 2} height={plotHeight / 2} className="map-zone laggard" /><rect x={left + plotWidth / 2} y={top + plotHeight / 2} width={plotWidth / 2} height={plotHeight / 2} className="map-zone pullback" />
      {[0, .5, 1].map((value) => <line key={`x${value}`} x1={left + value * plotWidth} x2={left + value * plotWidth} y1={top} y2={height - bottom} className={value === .5 ? 'map-axis strong' : 'map-axis'} />)}
      {[0, .25, .5, .75, 1].map((value) => <line key={`y${value}`} x1={left} x2={width - right} y1={top + value * plotHeight} y2={top + value * plotHeight} className={value === .5 ? 'map-axis strong' : 'map-axis'} />)}
      <text x={left + 10} y={top + 18} className="map-quadrant">WEAK-NAME BOUNCE</text><text x={width - right - 10} y={top + 18} textAnchor="end" className="map-quadrant good">LEADERS EXPANDING</text>
      <text x={left + 10} y={height - bottom - 10} className="map-quadrant bad">LAGGARDS BREAKING</text><text x={width - right - 10} y={height - bottom - 10} textAnchor="end" className="map-quadrant watch">LEADER PULLBACKS</text>
      {[-2, -1, 0, 1, 2].map((value) => <text key={value} x={left - 9} y={top + (2 - value) / 4 * plotHeight + 3} textAnchor="end" className="map-tick">{value > 0 ? `+${value}×` : `${value}×`}</text>)}
      {[0, 25, 50, 75, 100].map((value) => <text key={value} x={left + value / 100 * plotWidth} y={height - 17} textAnchor="middle" className="map-tick">{value}</text>)}
      <text x={left + plotWidth / 2} y={height - 2} textAnchor="middle" className="map-axis-label">F&O RELATIVE STRENGTH →</text><text transform={`translate(12 ${top + plotHeight / 2}) rotate(-90)`} textAnchor="middle" className="map-axis-label">MOVE VS EXPECTED →</text>
      {points.map((row) => { const setup = setupFor(row), selected = row.symbol === selectedSymbol, showLabel = selected || labelled.has(row.symbol); return <g key={row.symbol} className={`map-point ${setup.tone} ${selected ? 'selected' : ''}`} tabIndex="0" role="button" onMouseEnter={() => setHoveredSymbol(row.symbol)} onMouseLeave={() => setHoveredSymbol(null)} onFocus={() => setHoveredSymbol(row.symbol)} onBlur={() => setHoveredSymbol(null)} onClick={() => onSelect(row.symbol)} onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && onSelect(row.symbol)}><title>{row.symbol} · RS {fmt.num(row.rs_fo, 0)} · {fmt.pct(row.day_move_pct, 2)} · {fmt.num(row.ratio, 1)}× {row.implied_day_pct ? 'implied' : 'ADR'}</title>{selected && <circle cx={row.x} cy={row.y} r="11" className="point-halo" />}<circle cx={row.x} cy={row.y} r={selected ? 5.5 : 3.5} className="point-dot" />{showLabel && <text x={row.x + 7} y={row.y - 7} className="point-label">{row.symbol}</text>}</g> })}
      {hovered && <g className="map-hover-tip" transform={`translate(${hovered.x > width - 190 ? hovered.x - 164 : hovered.x + 10} ${hovered.y < 70 ? hovered.y + 12 : hovered.y - 56})`}>
        <rect width="154" height="46" rx="6" />
        <text x="9" y="15" className="tip-symbol">{hovered.symbol}<tspan x="145" textAnchor="end">RS {fmt.num(hovered.rs_fo, 0)}</tspan></text>
        <text x="9" y="32" className={`tip-move ${hovered.day_move_pct < 0 ? 'negative' : 'positive'}`}>{hovered.day_move_pct < 0 ? 'DROP TODAY' : 'UP TODAY'} {fmt.num(Math.abs(hovered.day_move_pct), 2)}%</text>
        <text x="145" y="32" textAnchor="end" className="tip-ratio">{fmt.num(Math.abs(hovered.ratio), 2)}× expected</text>
      </g>}
    </svg></div>
    <footer><span><i className="legend-dot leader" /> continuation</span><span><i className="legend-dot pullback" /> pullback</span><span><i className="legend-dot laggard" /> weakness</span><b>{points.length} names mapped</b></footer>
  </article>
}

function FocusQueue({ rows, selectedSymbol, onSelect }) {
  const focused = [...rows].filter((row) => row.day_move_pct != null).sort((a, b) => focusScore(b) - focusScore(a)).slice(0, 9)
  return <article className="fno-panel fno-focus-queue"><header><div><span className="fno-panel-kicker">ATTENTION QUEUE</span><h2>Where price is saying something</h2></div><p>Surprise + RS edge + alignment</p></header><div className="focus-list">{focused.map((row, index) => { const setup = setupFor(row); return <button key={row.symbol} className={`${setup.tone} ${row.symbol === selectedSymbol ? 'active' : ''}`} onClick={() => onSelect(row.symbol)}><span className="focus-rank">{String(index + 1).padStart(2, '0')}</span><span className="focus-symbol"><strong>{row.symbol}</strong><small>{setup.label}</small></span><span className="focus-move"><strong className={pctClass(row.day_move_pct)}>{fmt.pct(row.day_move_pct, 2)}</strong><small>{fmt.num(moveRatio(row), 1)}× {row.implied_day_pct ? 'IV' : 'ADR'}</small></span></button> })}</div></article>
}

function SectorRotation({ rows, activeSector, onSelect }) {
  const sectors = useMemo(() => { const buckets = new Map(); rows.forEach((row) => { const key = row.sector || 'Unclassified', bucket = buckets.get(key) || []; bucket.push(row); buckets.set(key, bucket) }); return [...buckets.entries()].map(([name, members]) => ({ name, count: members.length, move: average(members.map((row) => row.day_move_pct).filter((value) => value != null)), breadth: members.filter((row) => row.day_move_pct > 0).length / members.length * 100, rs: average(members.map((row) => row.rs_fo).filter((value) => value != null)) })).sort((a, b) => (b.move ?? -99) - (a.move ?? -99)) }, [rows])
  const scale = Math.max(1, ...sectors.map((item) => Math.abs(item.move ?? 0)))
  return <article className="fno-panel fno-sector-panel"><header><div><span className="fno-panel-kicker">ROTATION</span><h2>Sector participation</h2></div><button className={activeSector === 'All sectors' ? 'active' : ''} onClick={() => onSelect('All sectors')}>Clear filter</button></header><div className="sector-rotation-list">{sectors.map((item) => <button key={item.name} className={`${item.move >= 0 ? 'positive' : 'negative'} ${activeSector === item.name ? 'active' : ''}`} onClick={() => onSelect(activeSector === item.name ? 'All sectors' : item.name)}><span className="sector-name"><strong>{item.name}</strong><small>{item.count} names · RS {fmt.num(item.rs, 0)}</small></span><span className="sector-track"><i style={{ width: `${Math.abs(item.move ?? 0) / scale * 50}%` }} /></span><span className="sector-values"><strong>{fmt.pct(item.move, 2)}</strong><small>{fmt.num(item.breadth, 0)}% up</small></span></button>)}</div></article>
}

function InstrumentPanel({ row, openChart, chartUrl }) {
  if (!row) return <article className="fno-panel fno-instrument"><div className="empty">Select a stock on the map.</div></article>
  const setup = setupFor(row), ratio = moveRatio(row), implied = row.implied_day_pct != null
  return <article className={`fno-panel fno-instrument ${setup.tone}`}><header><div><span className="fno-panel-kicker">INSTRUMENT READ</span><h2>{row.symbol}</h2><p>{row.name} · {row.sector}</p></div><span className="instrument-setup">{setup.short}</span></header><div className="instrument-source-links"><a href={`https://www.screener.in/company/${encodeURIComponent(row.symbol)}/consolidated/`} target="_blank" rel="noreferrer">Screener.in ↗</a><a href={`https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(row.symbol)}`} target="_blank" rel="noreferrer">NSE quote ↗</a></div><div className="instrument-price"><strong>{fmt.rupee(row.close)}</strong><span className={pctClass(row.day_move_pct)}>{fmt.pct(row.day_move_pct, 2)}</span><small>{row.is_live ? 'LIVE' : `EOD · ${row.price_date ?? ''}`}</small></div><div className="instrument-grid"><div><small>F&O RS</small><strong>{fmt.num(row.rs_fo, 0)}</strong><span>All {fmt.num(row.rs_all, 0)} · Sector {fmt.num(row.rs_sector, 0)}</span></div><div><small>MOVE / EXPECTED</small><strong>{fmt.num(ratio, 2)}×</strong><span>{implied ? `IV implies ±${fmt.num(row.implied_day_pct, 2)}%` : `ADR ±${fmt.num(row.adr_pct, 2)}%`}</span></div><div><small>FROM LOW</small><strong>{row.from_low_pct == null ? '—' : `+${fmt.num(row.from_low_pct, 2)}%`}</strong><span>{row.live_meta?.day_low ? `low ${fmt.rupee(row.live_meta.day_low)}` : 'intraday feed required'}</span></div><div><small>ATM IV</small><strong>{row.atm_iv == null ? '—' : `${fmt.num(row.atm_iv, 1)}%`}</strong><span>{row.implied_expiry_pct == null ? 'options feed required' : `expiry ±${fmt.num(row.implied_expiry_pct, 1)}%`}</span></div></div><div className="instrument-trend"><span>5D <b className={pctClass(row.r5d_pct)}>{fmt.pct(row.r5d_pct, 1)}</b></span><span>10D <b className={pctClass(row.r10d_pct)}>{fmt.pct(row.r10d_pct, 1)}</b></span><span>50D <b className={pctClass(row.r50d_pct)}>{fmt.pct(row.r50d_pct, 1)}</b></span><span>200D <b className={pctClass(row.r200d_pct)}>{fmt.pct(row.r200d_pct, 1)}</b></span></div><div className="instrument-actions"><button onPointerEnter={() => prefetchJson(chartUrl(row, '5m'))} onClick={() => openChart(row, '5m')}>5 minute entry chart</button><button onPointerEnter={() => prefetchJson(chartUrl(row, 'daily'))} onClick={() => openChart(row, 'daily')}>3 year daily chart</button><button onPointerEnter={() => prefetchJson(chartUrl(row, 'weekly'))} onClick={() => openChart(row, 'weekly')}>Weekly</button></div></article>
}

function MoverCard({ row, cue, openChart, chartUrl }) {
  return <div className="mover-card">
    <button className="mover-main" onClick={() => openChart(row, '5m')} onPointerEnter={() => prefetchJson(chartUrl(row, '5m'))}>
      <span><strong>{row.symbol}</strong><small>{row.sector}</small></span>
      <span className="mover-change"><strong className={pctClass(row.day_move_pct)}>{fmt.pct(row.day_move_pct, 2)}</strong><small>{fmt.num(moveRatio(row), 2)}× expected</small></span>
    </button>
    <div className="mover-evidence"><span>RS <b>{fmt.num(row.rs_fo, 0)}</b></span><span>From low <b>{row.from_low_pct == null ? '—' : `+${fmt.num(row.from_low_pct, 1)}%`}</b></span><span>{cue}</span></div>
    <div className="mover-actions"><button onClick={() => openChart(row, '5m')}>5m</button><button onClick={() => openChart(row, 'daily')}>Daily</button></div>
  </div>
}

function IntradayMovers({ rows, threshold, onThreshold, openChart, chartUrl, live }) {
  const eligible = rows.filter((row) => row.day_move_pct != null && expectedMove(row))
  const upside = [...eligible].filter((row) => moveRatio(row) >= threshold).sort((a, b) => moveRatio(b) - moveRatio(a)).slice(0, 10)
  const downside = [...eligible].filter((row) => moveRatio(row) <= -threshold).sort((a, b) => moveRatio(a) - moveRatio(b)).slice(0, 10)
  const recoveries = [...eligible].filter((row) => row.from_low_pct != null && row.from_low_pct >= 1 && moveRatio(row) < threshold).sort((a, b) => b.from_low_pct - a.from_low_pct).slice(0, 10)
  return <>
    <section className="fno-scan-head"><div><span className="fno-panel-kicker">INTRADAY TAPE</span><h2>Move with context, not percentage alone</h2><p>Expansion is normalized by ATM IV; recovery measures distance from today’s low.</p></div><div className="scan-controls"><span>Minimum surprise</span>{[.5, 1, 1.5].map((value) => <button key={value} className={threshold === value ? 'active' : ''} onClick={() => onThreshold(value)}>{value}×</button>)}</div></section>
    {!live && <div className="fno-data-note"><b>Intraday tape is offline.</b> Expansion uses the latest EOD move; recovery-from-low candidates appear when the live scanner is running.</div>}
    <section className="mover-grid">
      <article className="fno-panel mover-lane positive"><header><div><span className="fno-panel-kicker">UPSIDE EXPANSION</span><h2>Demand exceeding expectation</h2></div><strong>{upside.length}</strong></header><div>{upside.map((row) => <MoverCard key={row.symbol} row={row} cue={row.rs_fo >= 60 ? 'RS confirms' : 'Low-RS squeeze'} openChart={openChart} chartUrl={chartUrl} />)}{!upside.length && <p className="scan-empty">No stocks above this threshold.</p>}</div></article>
      <article className="fno-panel mover-lane recovery"><header><div><span className="fno-panel-kicker">RECOVERY</span><h2>Stocks lifting from the low</h2></div><strong>{recoveries.length}</strong></header><div>{recoveries.map((row) => <MoverCard key={row.symbol} row={row} cue={row.day_move_pct >= 0 ? 'Back above prev close' : 'Still below prev close'} openChart={openChart} chartUrl={chartUrl} />)}{!recoveries.length && <p className="scan-empty">Waiting for live intraday lows.</p>}</div></article>
      <article className="fno-panel mover-lane negative"><header><div><span className="fno-panel-kicker">DOWNSIDE PRESSURE</span><h2>Supply exceeding expectation</h2></div><strong>{downside.length}</strong></header><div>{downside.map((row) => <MoverCard key={row.symbol} row={row} cue={row.rs_fo <= 40 ? 'RS confirms' : 'Leader under pressure'} openChart={openChart} chartUrl={chartUrl} />)}{!downside.length && <p className="scan-empty">No stocks below this threshold.</p>}</div></article>
    </section>
    <p className="fno-method">Use expansion to locate urgency, then use the 5-minute chart for structure and risk. A 1× reading means the stock has already travelled its option-implied one-day move.</p>
  </>
}

function BaseCard({ row, openChart, chartUrl }) {
  const dry = row.consol_vol_ratio != null && row.consol_vol_ratio < .85
  return <article className="base-card">
    <header><div><strong>{row.symbol}</strong><small>{row.sector}</small></div><RsPill value={row.rs_fo} /></header>
    <div className="base-primary"><div><small>BASE</small><strong>{row.consol_days}D</strong></div><div><small>RANGE</small><strong>{fmt.num(row.consol_range_pct, 1)}%</strong></div><div><small>PRIOR MOVE</small><strong className={pctClass(row.prior_burst_pct)}>{fmt.pct(row.prior_burst_pct, 1)}</strong></div></div>
    <div className="base-tags"><span className={dry ? 'good' : ''}>{dry ? 'Volume dry-up' : `Vol ${fmt.num(row.consol_vol_ratio, 2)}×`}</span>{row.prior_day_quiet && <span className="good">Quiet prior day</span>}{row.nr7 && <span className="good">NR7</span>}{row.inside_days > 0 && <span>{row.inside_days} inside</span>}</div>
    <div className="base-context"><span>Trend quality <b>{fmt.num(row.trend_quality, 0)}</b></span><span>50D <b className={pctClass(row.r50d_pct)}>{fmt.pct(row.r50d_pct, 1)}</b></span><span>Today <b className={pctClass(row.day_move_pct)}>{fmt.pct(row.day_move_pct, 1)}</b></span></div>
    <div className="base-actions"><button onPointerEnter={() => prefetchJson(chartUrl(row, 'daily'))} onClick={() => openChart(row, 'daily')}>Inspect base</button><button onPointerEnter={() => prefetchJson(chartUrl(row, '5m'))} onClick={() => openChart(row, '5m')}>5m entry</button></div>
  </article>
}

function TightBases({ rows, maxRange, minDays, minPriorMove, setMaxRange, setMinDays, setMinPriorMove, openChart, chartUrl }) {
  const candidates = [...rows].filter((row) => row.consol_range_pct != null && row.consol_range_pct <= maxRange && row.consol_days >= minDays && row.prior_burst_pct >= minPriorMove)
    .sort((a, b) => ((b.rs_fo ?? 0) + (b.trend_quality ?? 0) + (b.consol_vol_ratio < .85 ? 15 : 0)) - ((a.rs_fo ?? 0) + (a.trend_quality ?? 0) + (a.consol_vol_ratio < .85 ? 15 : 0)))
  return <>
    <section className="fno-scan-head base-scan-head"><div><span className="fno-panel-kicker">POST-MOVE CONSOLIDATION</span><h2>Strength going quiet</h2><p>High–low compression after a volatility-adjusted upside burst. Today is excluded from the measured base.</p></div><strong>{candidates.length}<small> candidates</small></strong></section>
    <section className="base-filter-bar"><label>Maximum base range <select value={maxRange} onChange={(event) => setMaxRange(Number(event.target.value))}><option value="3">3%</option><option value="5">5%</option><option value="8">8%</option><option value="12">12%</option></select></label><label>Minimum duration <select value={minDays} onChange={(event) => setMinDays(Number(event.target.value))}><option value="3">3 days</option><option value="5">5 days</option><option value="10">10 days</option><option value="15">15 days</option></select></label><label>Prior upmove <select value={minPriorMove} onChange={(event) => setMinPriorMove(Number(event.target.value))}><option value="2">+2%</option><option value="3">+3%</option><option value="5">+5%</option><option value="8">+8%</option></select></label><div className="base-filter-explain"><b>{maxRange}%</b> total high–low range · <b>{minDays}+</b> sessions · preceded by <b>+{minPriorMove}%</b> burst</div></section>
    {candidates.length ? <section className="base-card-grid">{candidates.map((row) => <BaseCard key={row.symbol} row={row} openChart={openChart} chartUrl={chartUrl} />)}</section> : <div className="empty base-empty">No F&O stock meets all three conditions. Widen the range or shorten the duration—don’t loosen every filter at once.</div>}
    <p className="fno-method">Best candidates usually combine high RS, orderly trend quality and volume contraction below 0.85×. This is a preparation list; the base can still fail, so use the chart for the actual trigger and invalidation.</p>
  </>
}

function FullTable({ rows, sort, toggleSort, chartUrl, openChart }) {
  return <div className="table-wrap fno-table-wrap"><table className="data fno-table"><thead><tr>{COLUMNS.map((column) => <th key={column.key} className={column.align === 'left' ? 'left' : ''} onClick={() => toggleSort(column.key)} title={column.help}>{column.label}{column.help && <sup>?</sup>}{sort.key === column.key && <span className="arrow">{sort.dir === 1 ? ' ↑' : ' ↓'}</span>}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.symbol}><td className="left fno-symbol-cell"><button onPointerEnter={() => prefetchJson(chartUrl(row, 'daily'))} onClick={() => openChart(row, 'daily')}><span>{row.symbol}</span><small>{row.name}</small></button></td><td className="left"><span className="fno-sector">{row.sector ?? 'Unclassified'}</span></td><td className="num dim">{fmt.num(row.lot_size)}</td><td className="num">{fmt.rupee(row.close)}</td><td className={`num ${pctClass(row.day_move_pct)}`}>{fmt.pct(row.day_move_pct, 2)}</td><td className="num up">{row.from_low_pct == null ? '—' : `+${fmt.num(row.from_low_pct, 2)}%`}</td><td><RsPill value={row.rs_all} /></td><td><RsPill value={row.rs_fo} /></td><td><RsPill value={row.rs_index} /></td><td><RsPill value={row.rs_sector} /></td><td className="num">{fmt.num(row.adr_pct, 2)}%</td><td className="num">{row.atm_iv == null ? '—' : `${fmt.num(row.atm_iv, 2)}%`}</td><td className="num implied-move-cell">{row.implied_day_pct == null ? '—' : <><strong>1D ±{fmt.num(row.implied_day_pct, 2)}%</strong><small>EXP ±{fmt.num(row.implied_expiry_pct, 2)}%</small></>}</td>{COLUMNS.filter((column) => column.chart).map((column) => <td key={column.key} className="num"><button className={`return-link ${pctClass(row[column.key])}`} onPointerEnter={() => prefetchJson(chartUrl(row, column.chart))} onClick={() => openChart(row, column.chart)}>{fmt.pct(row[column.key], 1)} <span>↗</span></button></td>)}</tr>)}</tbody></table></div>
}

export default function FnoDashboard() {
  const { data, error } = useFetch('/api/fno'), { data: meta } = useFetch('/api/meta')
  const { data: ivData } = usePollingFetch('/api/fno/iv', 15_000), { data: liveData } = usePollingFetch('/api/live/fno', 5_000)
  const [query, setQuery] = useState(''), [sector, setSector] = useState('All sectors'), [view, setView] = useState(INITIAL_VIEW)
  const [sort, setSort] = useState({ key: 'rs_fo', dir: -1 }), [selectedSymbol, setSelectedSymbol] = useState(null), [chart, setChart] = useState(null)
  const [moverThreshold, setMoverThreshold] = useState(1)
  const [baseRange, setBaseRange] = useState(5), [baseDays, setBaseDays] = useState(5), [basePriorMove, setBasePriorMove] = useState(3)
  const chartUrl = (stock, timeframe) => `/api/fno/chart/${stock.symbol}?timeframe=${timeframe}&days=${timeframe === '5m' ? 21 : 756}`
  const baseRows = useMemo(() => { if (!data) return []; const ivBySymbol = new Map((ivData?.rows ?? []).map((row) => [row.symbol, row])), liveBySymbol = new Map((liveData?.rows ?? []).map((row) => [row.symbol, row])); return data.rows.map((row) => { const iv = ivBySymbol.get(row.symbol), live = liveBySymbol.get(row.symbol); return { ...row, close: live?.last ?? row.close, day_move_pct: live?.day_move_pct ?? row.chg_pct ?? null, from_low_pct: live?.from_low_pct ?? null, is_live: live?.day_move_pct != null, price_date: data.as_of, live_meta: live ?? null, atm_iv: iv?.iv ?? null, implied_day_pct: iv?.implied_day_pct ?? null, implied_expiry_pct: iv?.implied_expiry_pct ?? null, iv_meta: iv ?? null } }) }, [data, ivData, liveData])
  const filteredRows = useMemo(() => { const needle = query.trim().toLowerCase(); return baseRows.filter((row) => (!needle || row.symbol.toLowerCase().includes(needle) || row.name?.toLowerCase().includes(needle)) && (sector === 'All sectors' || row.sector === sector)) }, [baseRows, query, sector])
  const rows = useMemo(() => [...filteredRows].sort((a, b) => { const av = a[sort.key], bv = b[sort.key]; if (av == null) return 1; if (bv == null) return -1; return (typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))) * sort.dir }), [filteredRows, sort])
  const defaultRow = useMemo(() => [...filteredRows].sort((a, b) => focusScore(b) - focusScore(a))[0], [filteredRows])
  const selected = filteredRows.find((row) => row.symbol === selectedSymbol) || defaultRow
  const sectors = useMemo(() => [...new Set(baseRows.map((row) => row.sector).filter(Boolean))].sort(), [baseRows])
  useEffect(() => {
    if (!selected) return
    prefetchJson(chartUrl(selected, 'daily'))
    prefetchJson(chartUrl(selected, '5m'))
  }, [selected?.symbol])
  const toggleSort = (key) => setSort((current) => current.key === key ? { key, dir: -current.dir } : { key, dir: key === 'symbol' || key === 'sector' ? 1 : -1 })
  const openChart = (stock, timeframe = 'daily') => setChart({ stock, timeframe })
  let content = null
  if (view === 'cockpit') content = <>
    <MarketRead meta={meta} rows={baseRows} />
    <section className="fno-cockpit-grid"><ConfluenceMap rows={filteredRows} selectedSymbol={selected?.symbol} onSelect={setSelectedSymbol} /><InstrumentPanel row={selected} openChart={openChart} chartUrl={chartUrl} /></section>
    <section className="fno-context-grid"><SectorRotation rows={baseRows} activeSector={sector} onSelect={setSector} /><FocusQueue rows={filteredRows} selectedSymbol={selected?.symbol} onSelect={setSelectedSymbol} /></section>
    <p className="fno-method">Move surprise compares the current day move with ATM IV’s one-day expected move; ADR is used when live options data is unavailable. It ranks attention, not trade quality or direction.</p>
  </>
  if (view === 'movers') content = <IntradayMovers rows={filteredRows} threshold={moverThreshold} onThreshold={setMoverThreshold} openChart={openChart} chartUrl={chartUrl} live={liveData?.status === 'live'} />
  if (view === 'bases') content = <TightBases rows={filteredRows} maxRange={baseRange} minDays={baseDays} minPriorMove={basePriorMove} setMaxRange={setBaseRange} setMinDays={setBaseDays} setMinPriorMove={setBasePriorMove} openChart={openChart} chartUrl={chartUrl} />
  if (view === 'table') content = <section className="fno-table-card"><FullTable rows={rows} sort={sort} toggleSort={toggleSort} chartUrl={chartUrl} openChart={openChart} /></section>

  return <div className="fno-page">
    <header className="fno-head fno-head-compact"><div><div className="fno-eyebrow">F&O CONFLUENCE COCKPIT</div><h1>See the market before the stock</h1><p>Regime, participation, rotation and price-vs-options expectation in one decision surface.</p></div><div className="fno-feed-strip"><span className={liveData?.status === 'live' ? 'live' : ''}><b>● TAPE</b>{liveData?.status === 'live' ? `${liveData.count} LIVE` : 'EOD FALLBACK'}</span><span className={ivData?.status === 'live' ? 'live' : ''}><b>● OPTIONS</b>{ivData?.status === 'live' ? `${ivData.count} LIVE` : (ivData?.status ?? 'OFFLINE').toUpperCase()}</span><span><b>PRICE DATE</b>{data?.as_of ?? '—'}</span></div></header>
    {error && <div className="empty">Could not load the F&O cockpit: {error.message}</div>}
    {!data && !error && <div className="loading">Building the F&O market map…</div>}
    {data && <><section className="fno-command-bar"><div className="segmented fno-view-switch"><button className={view === 'cockpit' ? 'active' : ''} onClick={() => setView('cockpit')}>Cockpit</button><button className={view === 'movers' ? 'active' : ''} onClick={() => setView('movers')}>Intraday Movers</button><button className={view === 'bases' ? 'active' : ''} onClick={() => setView('bases')}>Tight Bases</button><button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>Universe</button></div><div className="fno-search-wrap"><span>⌕</span><input aria-label="Search F&O stocks" placeholder="Search symbol or company" value={query} onChange={(event) => setQuery(event.target.value)} /></div><select value={sector} onChange={(event) => setSector(event.target.value)} aria-label="Filter by sector"><option>All sectors</option>{sectors.map((item) => <option key={item}>{item}</option>)}</select><span className="fno-row-count">{filteredRows.length} / {baseRows.length}</span>{sector !== 'All sectors' && <button className="fno-clear-filter" onClick={() => setSector('All sectors')}>× {sector}</button>}</section>{content}</>}
    {chart && <FnoChartDrawer stock={chart.stock} initialTimeframe={chart.timeframe} onClose={() => setChart(null)} />}
  </div>
}
