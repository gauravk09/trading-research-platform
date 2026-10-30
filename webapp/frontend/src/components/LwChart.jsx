import { useEffect, useRef } from 'react'
import { createChart, createSeriesMarkers, LineSeries, HistogramSeries, BarSeries } from 'lightweight-charts'

export const BASE_OPTS = {
  layout: {
    background: { color: 'transparent' },
    textColor: '#8b93a7',
    fontFamily: 'Inter, sans-serif',
    attributionLogo: false,
  },
  grid: {
    vertLines: { color: 'rgba(148,163,196,0.06)' },
    horzLines: { color: 'rgba(148,163,196,0.06)' },
  },
  // keep the fitted range when autoSize widens the chart after the first frame
  timeScale: { borderColor: 'rgba(148,163,196,0.15)', lockVisibleTimeRangeOnResize: true },
  rightPriceScale: { borderColor: 'rgba(148,163,196,0.15)' },
  crosshair: { mode: 0 },
}

const SERIES_TYPES = { line: LineSeries, histogram: HistogramSeries, bars: BarSeries }

// series: [{ type: 'line'|'histogram'|'bars', data, options, pane?, markers? }]
// pane: stacked sub-chart index sharing one time axis; paneHeights sets lower panes' px heights
// options: extra createChart options (e.g. a fixed price-scale width so stacked charts align)
export default function LwChart({ series, height = 260, fit = true, options, paneHeights }) {
  const ref = useRef(null)

  useEffect(() => {
    const chart = createChart(ref.current, { ...BASE_OPTS, ...options, height, autoSize: true })
    for (const s of series) {
      const created = chart.addSeries(SERIES_TYPES[s.type], s.options ?? {}, s.pane ?? 0)
      created.setData(s.data)
      if (s.scaleMargins) created.priceScale().applyOptions({ scaleMargins: s.scaleMargins })
      if (s.markers) createSeriesMarkers(created, s.markers)
    }
    paneHeights?.forEach((h, i) => chart.panes()[i + 1]?.setHeight(h))
    // defer fitContent one frame — autoSize hasn't measured the container yet
    const raf = fit ? requestAnimationFrame(() => chart.timeScale().fitContent()) : 0
    return () => {
      cancelAnimationFrame(raf)
      chart.remove()
    }
  }, [series, height, fit, options, paneHeights])

  return <div ref={ref} style={{ height }} />
}
