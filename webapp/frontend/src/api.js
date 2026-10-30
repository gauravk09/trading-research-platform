import { useEffect, useState } from 'react'

// Short-TTL cache: dedupes the parallel fetches on page mount without freezing
// state/session-dependent endpoints (daily state, order pad) for the whole
// session — the EOD update or a session change shows up within a minute.
const TTL_MS = 60_000
const cache = new Map() // url -> { at, data }
const inflight = new Map() // url -> Promise

export function peekJson(path, ttlMs = TTL_MS) {
  const hit = cache.get(path)
  return hit && Date.now() - hit.at < ttlMs ? hit.data : null
}

export function fetchJson(path, { ttlMs = TTL_MS, force = false } = {}) {
  const cached = force ? null : peekJson(path, ttlMs)
  if (cached) return Promise.resolve(cached)
  if (inflight.has(path)) return inflight.get(path)
  const request = fetch(path)
    .then((res) => {
      if (!res.ok) throw new Error(`${path} → ${res.status}`)
      return res.json()
    })
    .then((data) => {
      cache.set(path, { at: Date.now(), data })
      return data
    })
    .finally(() => inflight.delete(path))
  inflight.set(path, request)
  return request
}

export const prefetchJson = (path, options) => fetchJson(path, options).catch(() => null)

export function usePollingFetch(url, intervalMs) {
  const [state, setState] = useState({ data: peekJson(url, 0), error: null })
  useEffect(() => {
    let alive = true
    const load = () => fetchJson(url, { ttlMs: 0, force: true })
      .then((data) => alive && setState({ data, error: null }))
      .catch((error) => alive && setState((current) => ({ data: current.data, error })))
    load()
    const timer = window.setInterval(load, intervalMs)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [url, intervalMs])
  return state
}

// Data fetch tied to a URL: resets to null when the URL changes and ignores
// responses that land after the URL has moved on — no cross-tab overwrites.
export function useFetch(url) {
  const initial = url == null ? null : peekJson(url)
  const [state, setState] = useState({ url: initial ? url : null, data: initial, error: null })

  useEffect(() => {
    let alive = true
    const cached = url == null ? null : peekJson(url)
    setState({ url: cached ? url : null, data: cached, error: null })
    if (url == null) return // caller has nothing to fetch yet
    fetchJson(url)
      .then((data) => alive && setState({ url, data, error: null }))
      .catch((error) => alive && setState({ url, data: null, error }))
    return () => {
      alive = false
    }
  }, [url])

  return state.url === url ? { data: state.data, error: state.error } : { data: null, error: null }
}

export const fmt = {
  prob: (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`),
  pct: (v, digits = 1) =>
    v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`,
  num: (v, digits = 0) =>
    v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: digits }),
  rupee: (v) =>
    v == null ? '—' : `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`,
  compact: (v) => {
    if (v == null) return '—'
    if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)}L Cr`
    if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)}k Cr`
    return `₹${v.toFixed(0)} Cr`
  },
}

export const pctClass = (v) => (v == null ? 'dim' : v > 0 ? 'up' : v < 0 ? 'down' : 'dim')
