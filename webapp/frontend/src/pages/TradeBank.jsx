import { useEffect, useMemo, useState } from 'react'
import { fmt, pctClass, useFetch } from '../api.js'
import ReplayChart from '../components/ReplayChart.jsx'
import { SMA_COLORS, SMA_WIDTH } from '../components/ChartDrawer.jsx'

const UP = '#2ee6a8'
const DOWN = '#ff5d73'
const STEP_MS = 1000 // replay speed: one trading day per second
const BAR_OPTS = {
  upColor: UP, downColor: DOWN, openVisible: true, thinBars: true,
  lastValueVisible: false, priceLineVisible: false, // last price means nothing on a historical chart
}
const INTRADAY_OPTS = {
  timeScale: { borderColor: 'rgba(148,163,196,0.15)', timeVisible: true, secondsVisible: false },
}
const OUTCOMES = { all: () => true, win: (t) => t.result > 0, loss: (t) => t.result <= 0 }
const ENTRY_TEXT = { close: 'signal-day close', open: 'next-day open', trigger: 'buy-stop hit on signal day' }

const dayOf = (unixIst) => new Date(unixIst * 1000).toISOString().slice(0, 10)
const endOfDay = (day) => Date.parse(`${day}T23:59:59Z`) / 1000 // intraday times are IST-shifted "UTC"
const entryArrow = (time) => [{ time, position: 'belowBar', shape: 'arrowUp', color: UP, size: 1.2 }]
const fmtResult = (v, unit) => (v == null ? '—' : `${v > 0 ? '+' : ''}${unit === 'R' ? v.toFixed(2) + 'R' : v.toFixed(1) + '%'}`)

function dailyLayers(t) {
  const c = t.candles
  const layers = [
    {
      type: 'bars',
      data: c.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
      options: BAR_OPTS,
      scaleMargins: { top: 0.06, bottom: 0.22 },
    },
    {
      type: 'histogram',
      data: c.map((d) => ({
        time: d.time,
        value: d.volume,
        color: d.time === t.signal_day ? 'rgba(46,230,168,0.9)'
          : d.close >= d.open ? 'rgba(46,230,168,0.30)' : 'rgba(255,93,115,0.30)',
      })),
      options: { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false },
      scaleMargins: { top: 0.82, bottom: 0 },
    },
  ]
  for (const key of Object.keys(SMA_COLORS)) {
    layers.push({
      type: 'line',
      data: c.filter((d) => d[key] != null).map((d) => ({ time: d.time, value: d[key] })),
      options: { color: SMA_COLORS[key], lineWidth: SMA_WIDTH[key] ?? 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false },
    })
  }
  return layers
}

// The entry bar on the 5-min chart: last bar for a close entry, first bar for an
// open entry, first bar trading through the buy-stop for a trigger entry.
function intradayEntryBar(t) {
  const day = t.intraday.filter((b) => dayOf(b.time) === t.entry_day)
  if (!day.length) return null
  if (t.entry_at === 'close') return day[day.length - 1]
  if (t.entry_at === 'trigger') return day.find((b) => b.high >= t.entry) ?? day[0]
  return day[0]
}

// Signal-day facts computed only from bars up to the signal (nothing from the future).
function signalFacts(t, sig) {
  const bar = t.candles[sig]
  const prior = t.candles.slice(Math.max(sig - 50, 0), sig)
  const avgVol = prior.reduce((s, d) => s + d.volume, 0) / (prior.length || 1)
  const vsMa = (key) => (bar[key] ? (bar.close / bar[key] - 1) * 100 : null)
  const yearHigh = Math.max(...t.candles.slice(0, sig + 1).map((d) => d.high))
  return {
    close: bar.close, volRatio: bar.volume / avgVol,
    vs50: vsMa('sma50'), vs200: vsMa('sma200'), fromHigh: (bar.close / yearHigh - 1) * 100,
  }
}

function Row({ k, children }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '3px 0', fontSize: 13 }}>
      <span className="dim">{k}</span>
      <span className="num">{children}</span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div className="dim" style={{ fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  )
}

const Yoy = ({ v }) => (v == null ? <span className="dim"> —</span> : <span className={pctClass(v)}> {v > 0 ? '+' : ''}{v}%</span>)

function ResultsTable({ rows }) {
  if (!rows.length) return <div className="dim" style={{ fontSize: 13 }}>none in data</div>
  return (
    <table style={{ width: '100%', fontSize: 12.5, borderCollapse: 'collapse' }}>
      <thead>
        <tr className="dim" style={{ textAlign: 'right' }}>
          <th style={{ textAlign: 'left', fontWeight: 400 }}>Qtr</th>
          <th style={{ fontWeight: 400 }}>Revenue ₹Cr (YoY)</th>
          <th style={{ fontWeight: 400 }}>Profit ₹Cr (YoY)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.quarter} className="num" style={{ textAlign: 'right' }} title={`filed ${r.filed} · ${r.consolidated ? 'consolidated' : 'standalone'}`}>
            <td style={{ textAlign: 'left', padding: '2px 0' }}>{r.quarter}</td>
            <td>{fmt.num(r.revenue_cr)}<Yoy v={r.revenue_yoy} /></td>
            <td>{fmt.num(r.pat_cr)}<Yoy v={r.pat_yoy} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Sidebar({ t, setup, sig, pos, done, playing, onPlay, onShowAll }) {
  const f = signalFacts(t, sig)
  const today = t.candles[pos]
  const cutoff = today.time + ' 15:30' // anything filed after today's close isn't known yet
  const results = t.results.filter((r) => r.filed <= cutoff).reverse().slice(0, 4)
  const filings = t.filings.filter((x) => x.when <= cutoff).reverse().slice(0, 6)
  const inTrade = today.time >= t.entry_day
  const held = pos - t.candles.findIndex((d) => d.time === t.entry_day)
  const pnl = inTrade ? Math.round((today.close / t.entry - 1) * 1000) / 10 || 0 : null // || 0 turns -0 into 0

  return (
    <div className="card panel" style={{ position: 'sticky', top: 12, alignSelf: 'start' }}>
      <h2 style={{ margin: 0 }}>{t.symbol}</h2>
      <div className="dim" style={{ fontSize: 13 }}>{setup?.label} · signal {t.signal_day}</div>

      <Section title="Signal day">
        <Row k="Change"><span className={pctClass(t.signal_chg_pct)}>{fmt.pct(t.signal_chg_pct)}</span></Row>
        <Row k="Close">{fmt.rupee(f.close)}</Row>
        <Row k="Volume">{fmt.num(t.signal_volume / 1e6, 1)}M · {f.volRatio.toFixed(1)}× 50d avg</Row>
        <Row k="vs 50 SMA"><span className={pctClass(f.vs50)}>{fmt.pct(f.vs50)}</span></Row>
        <Row k="vs 200 SMA"><span className={pctClass(f.vs200)}>{fmt.pct(f.vs200)}</span></Row>
        <Row k="from 1-yr high"><span className={pctClass(f.fromHigh)}>{fmt.pct(f.fromHigh)}</span></Row>
      </Section>

      <Section title={`Quarterly results (known by ${today.time})`}>
        <ResultsTable rows={results} />
      </Section>

      <Section title="Other filings">
        {filings.length === 0 && <div className="dim" style={{ fontSize: 13 }}>none</div>}
        {filings.map((x) => (
          <div key={x.when + x.text} title={x.text} style={{ fontSize: 12, padding: '3px 0', lineHeight: 1.35 }}>
            <span style={{ color: x.color }}>●</span> <span className="dim">{x.when.slice(0, 10)}</span>{' '}
            {x.text.length > 110 ? x.text.slice(0, 110) + '…' : x.text}
          </div>
        ))}
      </Section>

      <Section title="Trade">
        <Row k="Entry rule">{ENTRY_TEXT[t.entry_at]}</Row>
        {inTrade && <Row k="Entry">{fmt.rupee(t.entry)} · {t.entry_day}</Row>}
        {inTrade && <Row k={`Day ${held} · ${today.time}`}><span className={pctClass(pnl)}>{fmt.pct(pnl)} from entry</span></Row>}
        {t.cat && <Row k="Catalyst">{t.cat}</Row>}
      </Section>

      <div style={{ marginTop: 18 }}>
        {done ? (
          <div style={{
            textAlign: 'center', fontWeight: 700, fontSize: 18, padding: '10px 0', borderRadius: 10,
            color: t.result > 0 ? UP : DOWN, background: t.result > 0 ? 'rgba(46,230,168,0.12)' : 'rgba(255,93,115,0.12)',
          }}>
            {t.result > 0 ? 'WIN' : 'LOSS'} {fmtResult(t.result, setup?.unit)}
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onPlay} style={{ flex: 1, padding: '10px 0', fontSize: 15, fontWeight: 700 }}>
              {playing ? '❚❚ Pause' : pos === sig ? '▶ Replay' : '▶ Resume'} <span className="dim">(space)</span>
            </button>
            <button onClick={onShowAll} style={{ padding: '10px 12px' }}>Show all ⏭</button>
          </div>
        )}
        {done && setup && <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>{setup.meaning}</div>}
      </div>
    </div>
  )
}

export default function TradeBank() {
  const { data: setups } = useFetch('/api/tradebank/setups')
  const [slug, setSlug] = useState('ep9m')
  const [year, setYear] = useState(null) // null -> server picks the latest year
  const [outcome, setOutcome] = useState('all')
  const [idx, setIdx] = useState(0)
  const [step, setStep] = useState(0) // trading days replayed past the signal day
  const [playing, setPlaying] = useState(false)

  const setup = setups?.find((s) => s.slug === slug)
  const { data: listing } = useFetch(`/api/tradebank/${slug}/trades${year ? `?year=${year}` : ''}`)
  const list = useMemo(() => (listing?.trades ?? []).filter(OUTCOMES[outcome]), [listing, outcome])
  const current = list[Math.min(idx, list.length - 1)]
  const { data: trade, error } = useFetch(current ? `/api/tradebank/${slug}/trades/${current.i}` : null)

  const sig = trade ? trade.candles.findIndex((d) => d.time === trade.signal_day) : 0
  const maxStep = trade ? trade.candles.length - 1 - sig : 0
  const pos = sig + Math.min(step, maxStep)
  const done = trade != null && step >= maxStep
  const until = trade?.candles[pos].time

  useEffect(() => setIdx(0), [slug, year, outcome])
  useEffect(() => { setStep(0); setPlaying(false) }, [trade])
  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => setStep((s) => s + 1), STEP_MS)
    return () => clearInterval(id)
  }, [playing])
  useEffect(() => { if (done) setPlaying(false) }, [done])
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'SELECT') return
      if (e.key === 'ArrowRight') setIdx((p) => Math.min(p + 1, list.length - 1))
      if (e.key === 'ArrowLeft') setIdx((p) => Math.max(p - 1, 0))
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [list.length])

  const daily = useMemo(() => (trade ? dailyLayers(trade) : null), [trade])
  const intraday = useMemo(
    () => (trade?.intraday.length ? [{ type: 'bars', data: trade.intraday, options: BAR_OPTS }] : null), [trade])
  const inTrade = until != null && until >= trade.entry_day
  const dailyMarks = useMemo(() => (inTrade ? entryArrow(trade.entry_day) : []), [inTrade, trade])
  const intradayMarks = useMemo(() => {
    const bar = inTrade && trade.intraday.length && intradayEntryBar(trade)
    return bar ? entryArrow(bar.time) : []
  }, [inTrade, trade])
  const pick = (setter) => (e) => { setter(e.target.value); e.target.blur() } // blur so keys drive the replay

  return (
    <div>
      <div className="page-head">
        <h1>Trade Bank</h1>
        <p>Each trade opens at the signal day. Judge it, then Space to replay one day per second (Space again pauses). ← / → to flip.</p>
      </div>

      <div className="toolbar">
        <label>Setup</label>
        <select value={slug} onChange={pick((v) => { setSlug(v); setYear(null) })}>
          {(setups ?? []).map((s) => <option key={s.slug} value={s.slug}>{s.label}</option>)}
        </select>
        <label>Year</label>
        <select value={listing?.year ?? ''} onChange={pick(setYear)}>
          {(listing?.years ?? []).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <label>Outcome</label>
        <select value={outcome} onChange={pick(setOutcome)}>
          <option value="all">All</option>
          <option value="win">Wins</option>
          <option value="loss">Losses</option>
        </select>
        <span className="spacer" />
        <button onClick={() => setIdx((p) => Math.max(p - 1, 0))} disabled={idx === 0}>◀ Prev</button>
        <span className="num" style={{ minWidth: 90, textAlign: 'center' }}>
          {list.length ? idx + 1 : 0} / {list.length}
        </span>
        <button onClick={() => setIdx((p) => Math.min(p + 1, list.length - 1))} disabled={idx >= list.length - 1}>Next ▶</button>
      </div>

      {error && <div className="empty">Could not load trade: {String(error.message ?? error)}</div>}
      {current && !trade && !error && <div className="loading">Loading…</div>}
      {listing && !list.length && <div className="empty">No trades for this filter.</div>}
      {trade && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 16 }}>
          <div>
            <div className="card panel">
              <div className="panel-sub">
                Daily · {until} ·{' '}
                <span style={{ color: SMA_COLORS.sma10 }}>— 10</span>{' '}
                <span style={{ color: SMA_COLORS.sma20 }}>— 20</span>{' '}
                <span style={{ color: SMA_COLORS.sma50 }}>— 50</span>{' '}
                <span style={{ color: SMA_COLORS.sma200 }}>— 200 SMA</span>
              </div>
              <ReplayChart layers={daily} until={until} markers={dailyMarks} height={460} />
            </div>
            <div className="card panel">
              <div className="panel-sub">5-min · 2 sessions before → 2 after the entry day</div>
              {intraday
                ? <ReplayChart layers={intraday} until={endOfDay(until)} markers={intradayMarks} height={230} options={INTRADAY_OPTS} />
                : <div className="dim" style={{ padding: 20 }}>No 5-min data for this trade (intraday store starts 29 Aug 2024).</div>}
            </div>
          </div>
          <Sidebar
            t={trade} setup={setup} sig={sig} pos={pos} done={done} playing={playing}
            onPlay={() => setPlaying((p) => !p)} onShowAll={() => { setPlaying(false); setStep(maxStep) }}
          />
        </div>
      )}
    </div>
  )
}
