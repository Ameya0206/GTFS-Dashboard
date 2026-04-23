/**
 * App.jsx
 *
 * Root component. Manages feed submission state (idle → loading → results/error)
 * and renders the full dashboard once a health report is received.
 */

import React, { useState } from 'react'
import FeedInput from './components/FeedInput'
import HealthScorecard from './components/HealthScorecard'
import IssueLog from './components/IssueLog'
import InsightsPanel from './components/InsightsPanel'
import RouteAnalysis from './components/RouteAnalysis'

export default function App() {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(formData) {
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const base = import.meta.env.VITE_API_URL ?? ''
      const res = await fetch(`${base}/validate`, { method: 'POST', body: formData })
      if (!res.ok) {
        let detail = `Server error ${res.status}`
        try {
          const body = await res.json()
          detail = body?.detail ?? detail
        } catch (_) {}
        throw new Error(detail)
      }
      setReport(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-baseline gap-3">
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">
            GTFS Feed Health Dashboard
          </h1>
          <span className="text-xs text-gray-400 font-medium uppercase tracking-widest">
            MVP
          </span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        {/* Feed input */}
        <div>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Submit a feed
          </h2>
          <FeedInput onSubmit={handleSubmit} loading={loading} />
        </div>

        {/* Loading state */}
        {loading && (
          <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-lg px-5 py-4">
            <span className="animate-spin text-blue-500 text-lg">⟳</span>
            <p className="text-sm text-blue-700 font-medium">
              Validating feed — this may take a moment for large files…
            </p>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-5 py-4">
            <p className="text-sm font-semibold text-red-700 mb-0.5">Validation failed</p>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {/* Results */}
        {report && !loading && (
          <div className="space-y-0">
            <HealthScorecard report={report} />
            <IssueLog issues={report.issues} />
            <InsightsPanel
              insights={report.safe_insights}
              cleaningLog={report.cleaning_log}
            />
            <RouteAnalysis routes={report.safe_insights?.routes_detail} />
          </div>
        )}

        {/* Empty state */}
        {!report && !loading && !error && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-3">📋</p>
            <p className="text-sm">
              Upload a GTFS zip or provide a URL above to begin.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
