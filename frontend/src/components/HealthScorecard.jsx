/**
 * HealthScorecard.jsx
 *
 * Displays the overall health score, feed summary metadata, and usable-data
 * flags derived from the backend health report.
 */

import React from 'react'

function scoreColor(pct) {
  if (pct >= 80) return 'text-green-600'
  if (pct >= 50) return 'text-yellow-600'
  return 'text-red-600'
}

function scoreBg(pct) {
  if (pct >= 80) return 'bg-green-50 border-green-200'
  if (pct >= 50) return 'bg-yellow-50 border-yellow-200'
  return 'bg-red-50 border-red-200'
}

function scoreLabel(pct) {
  if (pct >= 80) return 'Good'
  if (pct >= 50) return 'Degraded'
  return 'Critical'
}

function FileBadge({ name, present }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium mr-1 mb-1 ${
        present
          ? 'bg-green-100 text-green-800'
          : 'bg-red-100 text-red-800'
      }`}
    >
      {present ? '✓' : '✗'} {name}
    </span>
  )
}

function UsableFlag({ label, usable }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`w-2 h-2 rounded-full flex-shrink-0 ${
          usable ? 'bg-green-500' : 'bg-red-400'
        }`}
      />
      <span className="text-sm text-gray-700">{label}</span>
    </div>
  )
}

const REQUIRED_FILES = [
  'agency.txt',
  'stops.txt',
  'routes.txt',
  'trips.txt',
  'stop_times.txt',
  'calendar.txt',
  'calendar_dates.txt',
]

export default function HealthScorecard({ report }) {
  const { feed_summary, health_score, usable_data } = report
  const pct = Math.round(health_score * 100)

  const allFiles = [
    ...new Set([
      ...feed_summary.files_present,
      ...feed_summary.files_missing,
    ]),
  ].sort()

  const presentSet = new Set(feed_summary.files_present)

  return (
    <section className="mt-8 space-y-4">
      {/* Score banner */}
      <div className={`border rounded-lg p-6 ${scoreBg(pct)}`}>
        <div className="flex items-baseline gap-3">
          <span className={`text-5xl font-bold tabular-nums ${scoreColor(pct)}`}>
            {pct}%
          </span>
          <span className={`text-lg font-semibold ${scoreColor(pct)}`}>
            {scoreLabel(pct)}
          </span>
        </div>
        <p className="mt-1 text-sm text-gray-500">Feed health score</p>
      </div>

      {/* Feed metadata */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Feed Summary
        </h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <dt className="font-medium text-gray-600">Agency</dt>
          <dd className="text-gray-900">
            {feed_summary.agency_name ?? (
              <span className="text-gray-400 italic">Unknown</span>
            )}
          </dd>
          <dt className="font-medium text-gray-600">Feed version</dt>
          <dd className="text-gray-900">
            {feed_summary.feed_version ?? (
              <span className="text-gray-400 italic">Not specified</span>
            )}
          </dd>
        </dl>
      </div>

      {/* Files present / missing */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Files
        </h3>
        <div className="flex flex-wrap">
          {allFiles.map((f) => (
            <FileBadge key={f} name={f} present={presentSet.has(f)} />
          ))}
        </div>
        {feed_summary.files_missing.length > 0 && (
          <p className="mt-2 text-xs text-red-600">
            {feed_summary.files_missing.length} required{' '}
            {feed_summary.files_missing.length === 1 ? 'file' : 'files'} missing
          </p>
        )}
      </div>

      {/* Usable data flags */}
      {usable_data && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Usable Data
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(usable_data).map(([key, val]) => (
              <UsableFlag
                key={key}
                label={key.replace(/_/g, ' ')}
                usable={val}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
