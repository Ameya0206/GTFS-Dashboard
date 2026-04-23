/**
 * RouteAnalysis.jsx
 *
 * Per-route breakdown table for consultant-grade analysis.
 * Shows service span, headway, timed stop coverage, accessibility, and flags.
 */

import React, { useState } from 'react'

const FLAG_META = {
  LOW_FREQUENCY:      { label: 'Low frequency',     color: 'bg-yellow-100 text-yellow-800' },
  ADA_GAP:            { label: 'ADA gap',            color: 'bg-red-100 text-red-700' },
  POOR_TIMING_DATA:   { label: 'Poor timing data',   color: 'bg-orange-100 text-orange-700' },
  INFREQUENT_SERVICE: { label: 'Infrequent service', color: 'bg-yellow-100 text-yellow-800' },
  SINGLE_DIRECTION:   { label: 'Single direction',   color: 'bg-purple-100 text-purple-700' },
}

function Flag({ code }) {
  const meta = FLAG_META[code] ?? { label: code, color: 'bg-gray-100 text-gray-600' }
  return (
    <span className={`inline-block text-xs font-medium px-1.5 py-0.5 rounded ${meta.color}`}>
      {meta.label}
    </span>
  )
}

function PctBar({ value, warnBelow, goodAbove }) {
  if (value == null) return <span className="text-gray-400 text-xs">—</span>
  const color =
    value >= (goodAbove ?? 80) ? 'text-green-700' :
    value >= (warnBelow ?? 50) ? 'text-yellow-700' :
    'text-red-600'
  return <span className={`font-mono text-sm font-semibold ${color}`}>{value.toFixed(1)}%</span>
}

export default function RouteAnalysis({ routes }) {
  const [sortKey, setSortKey] = useState('trip_count')
  const [sortDir, setSortDir] = useState('desc')

  if (!routes || routes.length === 0) return null

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = [...routes].sort((a, b) => {
    const av = a[sortKey] ?? (sortDir === 'asc' ? Infinity : -Infinity)
    const bv = b[sortKey] ?? (sortDir === 'asc' ? Infinity : -Infinity)
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const flaggedCount = routes.filter(r => r.flags && r.flags.length > 0).length

  function ColHeader({ label, key }) {
    const active = sortKey === key
    return (
      <th
        className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide cursor-pointer select-none hover:text-gray-700 whitespace-nowrap"
        onClick={() => handleSort(key)}
      >
        {label}
        {active && <span className="ml-1 text-gray-400">{sortDir === 'asc' ? '↑' : '↓'}</span>}
      </th>
    )
  }

  return (
    <section className="mt-8">
      <div className="flex items-baseline gap-3 mb-3">
        <h2 className="text-base font-semibold text-gray-700">Route Analysis</h2>
        {flaggedCount > 0 && (
          <span className="text-xs text-red-600 font-medium">
            {flaggedCount} route{flaggedCount > 1 ? 's' : ''} with issues
          </span>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
        <table className="min-w-full text-sm bg-white">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <ColHeader label="Route" key="route_short_name" />
              <ColHeader label="Trips" key="trip_count" />
              <ColHeader label="Service span" key="first_departure" />
              <ColHeader label="Avg headway" key="avg_headway_minutes" />
              <ColHeader label="Timed stops" key="timed_stop_pct" />
              <ColHeader label="Wheelchair %" key="wheelchair_accessible_pct" />
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Flags</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(route => (
              <tr
                key={route.route_id}
                className={route.flags && route.flags.length > 0 ? 'bg-red-50/30' : 'hover:bg-gray-50'}
              >
                {/* Route name */}
                <td className="px-3 py-2.5">
                  <span className="font-semibold text-gray-900">{route.route_short_name ?? route.route_id}</span>
                  {route.route_long_name && (
                    <p className="text-xs text-gray-400 truncate max-w-[160px]">{route.route_long_name}</p>
                  )}
                </td>

                {/* Trip count */}
                <td className="px-3 py-2.5 font-mono text-gray-700 text-sm">
                  {route.trip_count}
                </td>

                {/* Service span */}
                <td className="px-3 py-2.5 text-gray-600 text-xs font-mono whitespace-nowrap">
                  {route.first_departure && route.last_departure
                    ? `${route.first_departure} – ${route.last_departure}`
                    : <span className="text-gray-400">—</span>}
                </td>

                {/* Avg headway */}
                <td className="px-3 py-2.5 text-sm font-mono">
                  {route.avg_headway_minutes != null
                    ? <span className={route.avg_headway_minutes > 60 ? 'text-red-600 font-semibold' : 'text-gray-700'}>
                        {route.avg_headway_minutes} min
                      </span>
                    : <span className="text-gray-400">—</span>}
                </td>

                {/* Timed stops */}
                <td className="px-3 py-2.5">
                  <PctBar value={route.timed_stop_pct} warnBelow={40} goodAbove={70} />
                </td>

                {/* Wheelchair */}
                <td className="px-3 py-2.5">
                  <PctBar value={route.wheelchair_accessible_pct} warnBelow={90} goodAbove={100} />
                </td>

                {/* Flags */}
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    {route.flags && route.flags.map(f => <Flag key={f} code={f} />)}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        Click column headers to sort. Timed stops % below 25% impacts trip planner accuracy (Google Maps, apps).
      </p>
    </section>
  )
}
