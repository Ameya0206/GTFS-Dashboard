/**
 * FeedInput.jsx
 *
 * Accepts either a GTFS zip file upload or a URL, then calls onSubmit with
 * a FormData object ready to POST to /validate.
 */

import React, { useState, useRef } from 'react'

export default function FeedInput({ onSubmit, loading }) {
  const [url, setUrl] = useState('')
  const [fileName, setFileName] = useState(null)
  const [activeTab, setActiveTab] = useState('file') // 'file' | 'url'
  const fileInputRef = useRef(null)

  function handleFileChange(e) {
    const file = e.target.files[0]
    if (!file) return
    setFileName(file.name)
    const formData = new FormData()
    formData.append('file', file)
    onSubmit(formData)
  }

  function handleUrlSubmit(e) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return
    const formData = new FormData()
    formData.append('url', trimmed)
    onSubmit(formData)
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
      {/* Tab switcher */}
      <div className="flex gap-1 mb-6 border-b border-gray-200">
        <button
          onClick={() => setActiveTab('file')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'file'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Upload zip file
        </button>
        <button
          onClick={() => setActiveTab('url')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'url'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Provide URL
        </button>
      </div>

      {activeTab === 'file' && (
        <div>
          <p className="text-sm text-gray-500 mb-3">
            Select a GTFS zip archive from your local machine.
          </p>
          <div
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
          >
            {fileName ? (
              <p className="text-sm font-medium text-gray-800">{fileName}</p>
            ) : (
              <>
                <p className="text-sm text-gray-500">Click to choose a file</p>
                <p className="text-xs text-gray-400 mt-1">.zip only</p>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            onChange={handleFileChange}
            className="hidden"
          />
        </div>
      )}

      {activeTab === 'url' && (
        <form onSubmit={handleUrlSubmit}>
          <p className="text-sm text-gray-500 mb-3">
            Provide a direct link to a GTFS zip file.
          </p>
          <div className="flex gap-2">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/gtfs.zip"
              required
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              type="submit"
              disabled={loading || !url.trim()}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Validating…' : 'Validate'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
