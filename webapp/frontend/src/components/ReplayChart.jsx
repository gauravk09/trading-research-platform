import { useEffect, useRef } from 'react'
import { createChart, createSeriesMarkers, LineSeries, HistogramSeries, BarSeries } from 'lightweight-charts'
import { BASE_OPTS } from './LwChart.jsx'

const SERIES_TYPES = { line: LineSeries, histogram: HistogramSeries, bars: BarSeries }

// A chart that plays forward: every layer shows only points with time <= `until`.
// Moving `until` forward appends bars with series.update() (no redraw, no zoom
// reset), so a one-bar-per-second replay stays smooth. The view is pinned to the
// full width of layers[0] up front, so the future shows as empty space filling in.
// layers: [{ type, data (full, time-sorted), options?, scaleMargins? }] — layers[0] carries `markers`.
export default function ReplayChart({ layers, until, markers, height, options }) {
  const ref = useRef(null)
  const state = useRef(null)

  useEffect(() => {
    const chart = createChart(ref.current, {
      ...BASE_OPTS, ...options, height, autoSize: true,
      timeScale: { ...BASE_OPTS.timeScale, ...options?.timeScale, shiftVisibleRangeOnNewBar: false },
    })
    const series = layers.map((l) => {
      const s = chart.addSeries(SERIES_TYPES[l.type], l.options ?? {})
      if (l.scaleMargins) s.priceScale().applyOptions({ scaleMargins: l.scaleMargins })
      return s
    })
    state.current = { chart, series, marks: createSeriesMarkers(series[0], []), until: null }
    return () => {
      chart.remove()
      state.current = null
    }
  }, [layers, height, options])

  useEffect(() => {
    const s = state.current
    const forward = s.until != null && until >= s.until
    layers.forEach((l, k) => {
      if (forward) l.data.filter((d) => d.time > s.until && d.time <= until).forEach((d) => s.series[k].update(d))
      else s.series[k].setData(l.data.filter((d) => d.time <= until))
    })
    if (s.until == null) {
      // one frame later: autoSize has measured the container by then
      requestAnimationFrame(() => state.current === s &&
        s.chart.timeScale().setVisibleLogicalRange({ from: -2, to: layers[0].data.length + 2 }))
    }
    s.until = until
  }, [layers, until])

  useEffect(() => {
    state.current.marks.setMarkers(markers ?? [])
  }, [layers, markers])

  return <div ref={ref} style={{ height }} />
}
