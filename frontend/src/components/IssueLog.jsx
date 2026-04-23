/**
 * IssueLog.jsx
 *
 * Lists all validation issues grouped by severity: BLOCKER → WARNING → INFO.
 * Each issue shows file, optional field, message, and count.
 */

import React, { useState } from 'react'

const SEVERITY_ORDER = ['BLOCKER', 'WARNING', 'INFO']

const SEVERITY_STYLES = {
  BLOCKER: {
    badge: 'bg-red-100 text-red-800',
    border: 'border-red-400',
    heading: 'text-red-700',
    row: 'bg-red-50',
  },
  WARNING: {
    badge: 'bg-yellow-100 text-yellow-800',
    border: 'border-yellow-400',
    heading: 'text-yellow-700',
    row: 'bg-yellow-50',
  },
  INFO: {
    badge: 'bg-blue-100 text-blue-800',
    border: 'border-blue-400',
    heading: 'text-blue-700',
    row: 'bg-blue-50',
  },
}

function IssueGroup({ severity, issues }) {
  const [collapsed, setCollapsed] = useState(false)
  const s = SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.INFO

  return (
    <div className="mb-4">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center gap-2 w-full text-left mb-2"
      >
        <span className={`text-xs font-bold uppercase px-2 py-0.5 rounded ${s.badge}`}>
          {severity}
        </span>
        <span className="text-sm text-gray-500">
          {issues.length} {issues.length === 1 ? 'issue' : 'issues'}
        </span>
        <span className="ml-auto text-gray-400 text-xs">{collapsed ? '▶ show' : '▼ hide'}</span>
      </button>

      {!collapsed && (
        <ul className="space-y-2">
          {issues.map((issue, i) => (
            <li
              key={i}
              className={`border-l-4 ${s.border} rounded-r-md p-3 ${s.row}`}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-xs font-mono font-semibold text-gray-700">
                  {issue.file}
                </span>
                {issue.field && (
                  <span className="text-xs text-gray-500">› {issue.field}</span>
                )}
                {issue.count != null && (
                  <span className="ml-auto text-xs text-gray-500 tabular-nums">
                    {issue.count} record{issue.count !== 1 ? 's' : ''}
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-gray-800">{issue.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function IssueLog({ issues }) {
  if (!issues || issues.length === 0) {
    return (
      <section className="mt-8">
        <h2 className="text-base font-semibold text-gray-700 mb-3">Issues</h2>
        <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3">
          No issues found — feed passed all checks.
        </p>
      </section>
    )
  }

  // Group by severity in display order
  const grouped = {}
  for (const sev of SEVERITY_ORDER) {
    const group = issues.filter((i) => i.severity === sev)
    if (group.length > 0) grouped[sev] = group
  }

  return (
    <section className="mt-8">
      <h2 className="text-base font-semibold text-gray-700 mb-3">
        Issues{' '}
        <span className="font-normal text-gray-400">({issues.length} total)</span>
      </h2>

      {SEVERITY_ORDER.filter((s) => grouped[s]).map((sev) => (
        <IssueGroup key={sev} severity={sev} issues={grouped[sev]} />
      ))}
    </section>
  )
}
