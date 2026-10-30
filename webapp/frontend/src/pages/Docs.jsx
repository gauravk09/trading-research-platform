import { useEffect, useState } from 'react'
import { marked } from 'marked'
import { fetchJson } from '../api.js'

export default function Docs() {
  const [md, setMd] = useState(null)

  useEffect(() => {
    fetchJson('/api/docs').then((d) => setMd(d.markdown))
  }, [])

  if (!md) return <div className="loading">Loading reference…</div>

  return (
    <>
      <div className="page-head">
        <h1>How Scans Work</h1>
        <p>The scans reference — what every scan computes, from the rule files</p>
      </div>
      <div
        className="card panel docs-body"
        dangerouslySetInnerHTML={{ __html: marked.parse(md) }}
      />
    </>
  )
}
