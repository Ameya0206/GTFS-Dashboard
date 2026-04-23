/**
 * InsightsPanel.jsx
 *
 * Displays safe_insights organised into four consultant-facing sections:
 *   1. Feed Health    — expiry urgency, validity window
 *   2. Network        — counts, service patterns, avg stops/trip
 *   3. Accessibility  — wheelchair accessible %, non-accessible trip count
 *   4. Data Quality   — timed stop coverage (affects trip planners)
 *
 * Any null insight renders a greyed-out card. Never fabricates values.
 */

import React, { useState } from 'react'

// ---------------------------------------------------------------------------
// Small reusable card
// ---------------------------------------------------------------------------
function Card({ label, value, sub, highlight, dim }) {
  const isEmpty = value == null
  return (
    <div className={`rounded-lg border p-4 ${
      isEmpty ? 'border-gray-200 bg-gray-50' :
      highlight ? 'border-red-300 bg-red-50' :
      'border-gray-200 bg-white shadow-sm'
    }`}>
      <p className={`text-xs font-semibold uppercase tracking-wide mb-1 ${
        isEmpty ? 'text-gray-400' : highlight ? 'text-red-600' : 'text-gray-500'
      }`}>
        {label}
      </p>
      {isEmpty ? (
        <p className="text-sm italic text-gray-400">Could not be derived</p>
      ) : (
        <>
          <p className={`text-2xl font-bold tabular-nums ${highlight ? 'text-red-700' : 'text-gray-900'}`}>
            {value}
          </p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </>
      )}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2 mt-5">
      {children}
    </h3>
  )
}

// ---------------------------------------------------------------------------
// Transfer hubs mini-table
// ---------------------------------------------------------------------------
function TransferHubs({ hubs }) {
  const [expanded, setExpanded] = useState(false)
  if (!hubs || hubs.length === 0) return null
  const shown = expanded ? hubs : hubs.slice(0, 5)
  return (
    <div className="mt-4 border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
          Transfer hubs ({hubs.length})
        </span>
        <span className="text-xs text-gray-400">Stops served by 3+ routes</span>
      </div>
      <table className="min-w-full text-sm bg-white">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="px-4 py-2 text-left text-xs text-gray-500 font-semibold">Stop</th>
            <th className="px-4 py-2 text-left text-xs text-gray-500 font-semibold">Routes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {shown.map(hub => (
            <tr key={hub.stop_id} className="hover:bg-gray-50">
              <td className="px-4 py-2 text-gray-800 font-medium text-xs">{hub.stop_name ?? hub.stop_id}</td>
              <td className="px-4 py-2 text-xs text-gray-500">{hub.routes.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hubs.length > 5 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="w-full text-center py-2 text-xs text-blue-600 hover:text-blue-800 bg-gray-50 border-t border-gray-100"
        >
          {expanded ? 'Show less' : `Show all ${hubs.length} hubs`}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function InsightsPanel({ insights, cleaningLog }) {
  if (!insights) return null

  // Feed expiry urgency
  const expiring = insights.feed_expiry_days != null && insights.feed_expiry_days <= 30
  const expired  = insights.feed_expiry_days != null && insights.feed_expiry_days < 0
  const expiryLabel = expired
    ? `Expired ${Math.abs(insights.feed_expiry_days)} days ago`
    : insights.feed_expiry_days != null
      ? `${insights.feed_expiry_days} days`
      : null

  const validityWindow = insights.feed_start_date && insights.feed_end_date
    ? `${insights.feed_start_date} → ${insights.feed_end_date}`
    : null

  return (
    <section className="mt-8">
      <h2 className="text-base font-semibold text-gray-700 mb-1">Safe Insights</h2>

      {/* ---- Feed Health ---- */}
      <SectionTitle>Feed Health</SectionTitle>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Card
          label="Feed expires in"
          value={expiryLabel}
          sub={validityWindow}
          highlight={expiring || expired}
        />
        <Card
          label="Service patterns"
          value={insights.service_pattern_count}
          sub="Distinct calendar entries"
        />
        <Card
          label="Avg stops / trip"
          value={insights.avg_stops_per_trip}
          sub="Across all trips"
        />
      </div>

      {/* ---- Network ---- */}
      <SectionTitle>Network</SectionTitle>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card label="Agencies"  value={insights.agency_count} />
        <Card label="Routes"    value={insights.route_count} />
        <Card label="Stops"     value={insights.stop_count} />
        <Card label="Trips"     value={insights.trip_count} />
        <Card
          label="Service days"
          value={insights.service_days ? insights.service_days.length : null}
          sub={insights.service_days ? insights.service_days.map(d => d.slice(0,3)).join(', ') : null}
        />
      </div>

      {/* ---- Accessibility ---- */}
      <SectionTitle>Accessibility</SectionTitle>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Card
          label="Wheelchair accessible"
          value={insights.wheelchair_accessible_pct != null ? `${insights.wheelchair_accessible_pct}%` : null}
          sub="Of all trips"
          highlight={insights.wheelchair_accessible_pct != null && insights.wheelchair_accessible_pct < 100}
        />
        <Card
          label="Non-accessible trips"
          value={insights.non_accessible_trip_count}
          sub="Trips with wheelchair_accessible=0"
          highlight={insights.non_accessible_trip_count > 0}
        />
      </div>

      {/* ---- Data Quality ---- */}
      <SectionTitle>Data Quality for Downstream Systems</SectionTitle>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Card
          label="Timed stop coverage"
          value={insights.timed_stop_pct != null ? `${insights.timed_stop_pct}%` : null}
          sub="Stop times with explicit arrival/departure"
          highlight={insights.timed_stop_pct != null && insights.timed_stop_pct < 30}
        />
      </div>
      {insights.timed_stop_pct != null && insights.timed_stop_pct < 30 && (
        <p className="mt-2 text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded px-3 py-2">
          Low timed stop coverage means trip planners (Google Maps, Transit app) cannot show accurate arrival times at most stops. Only timepoint stops have reliable times; intermediate stops are interpolated.
        </p>
      )}

      {/* ---- Transfer Hubs ---- */}
      <SectionTitle>Transfer Hubs</SectionTitle>
      <TransferHubs hubs={insights.transfer_hubs} />

      {/* ---- Cleaning log ---- */}
      {cleaningLog && cleaningLog.length > 0 && (
        <div className="mt-6 border border-yellow-200 bg-yellow-50 rounded-lg p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-yellow-700 mb-2">
            Cleaning log ({cleaningLog.length})
          </h3>
          <ul className="space-y-1">
            {cleaningLog.map((entry, i) => (
              <li key={i} className="text-xs text-yellow-800 font-mono">
                {typeof entry === 'string' ? entry : JSON.stringify(entry)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
