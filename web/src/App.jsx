import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const money = value => value == null ? 'Not detected' : `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const errorText = err => typeof err.response?.data?.detail === 'string' ? err.response.data.detail : err.message

function App() {
  const [images, setImages] = useState([])
  const [mode, setMode] = useState('rules')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState({})
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const input = useRef(null)
  const urls = useRef(new Set())
  useEffect(() => {
    const previews = urls.current
    return () => previews.forEach(url => URL.revokeObjectURL(url))
  }, [])

  function selectFiles(files) {
    if (loading) return
    const selected = [], invalid = []
    for (const file of files) {
      if (!/\.(jpe?g|png|webp|bmp|tiff?)$/i.test(file.name) || (file.type && !/^image\/(jpeg|png|webp|bmp|tiff)$/.test(file.type)) || !file.size) {
        invalid.push(file.name)
        continue
      }
      const preview = URL.createObjectURL(file)
      urls.current.add(preview)
      selected.push({ file, preview, id: crypto.randomUUID() })
    }
    setImages(previous => [...previous, ...selected])
    setResults({})
    setError(invalid.length ? `Skipped invalid or empty files: ${invalid.join(', ')}` : null)
  }

  function removeImage(image) {
    URL.revokeObjectURL(image.preview)
    urls.current.delete(image.preview)
    setImages(previous => previous.filter(item => item.id !== image.id))
    setResults({})
    setError(null)
  }

  async function analyzeImages() {
    if (!images.length || loading) return
    setLoading(true)
    setResults({})
    setError(null)
    const methods = mode === 'compare' ? ['rules', 'llm'] : [mode]
    try {
      // Keep each method's batch and grand total independent in Compare mode.
      for (const method of methods) {
        const form = new FormData()
        images.forEach(image => form.append('files', image.file))
        setProgress(`Uploading ${images.length} receipt(s) for ${method}…`)
        try {
          const response = await axios.post(`${API_URL}/analyze/batch/${method}`, form, {
            onUploadProgress: event => setProgress(event.total && event.loaded < event.total
              ? `Uploading: ${Math.round(event.loaded / event.total * 100)}%`
              : `Processing ${images.length} receipt(s) using ${method}. OCR may take several minutes…`),
          })
          setResults(previous => ({ ...previous, [method]: response.data }))
        } catch (err) {
          setResults(previous => ({ ...previous, [method]: { requestError: errorText(err) } }))
        }
      }
    } finally {
      setLoading(false)
      setProgress('')
    }
  }

  return <div className="app">
    <header className="header"><h1>📄 Receipt OCR</h1><p>Extract and combine data from your receipts</p></header>
    <div className="main-content">
      <div className="card">
        <h2>Upload receipts</h2>
        <div className={`upload-zone ${dragOver ? 'dragover' : ''}`} role="button" tabIndex={loading ? -1 : 0}
          aria-disabled={loading} onClick={() => !loading && input.current.click()}
          onKeyDown={event => { if (!loading && ['Enter', ' '].includes(event.key)) { event.preventDefault(); input.current.click() } }}
          onDragOver={event => { event.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={event => { event.preventDefault(); setDragOver(false); selectFiles(event.dataTransfer.files) }}>
          <p>Drop receipt images here or click to browse</p><small>JPEG, PNG, WebP, BMP, TIFF</small>
        </div>
        <input ref={input} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff" hidden disabled={loading}
          onChange={event => { selectFiles(event.target.files); event.target.value = '' }} />
        <div className="preview-list">{images.map(image => <div className="preview-card" key={image.id}>
          <img src={image.preview} alt={image.file.name} /><span>{image.file.name}</span>
          <button disabled={loading} onClick={() => removeImage(image)} aria-label={`Remove ${image.file.name}`}>Remove</button>
        </div>)}</div>
        <div className="mode-selector">{['rules', 'llm', 'compare'].map(value => <button key={value}
          disabled={loading} className={`mode-btn ${mode === value ? 'active' : ''}`}
          onClick={() => { setMode(value); setResults({}) }}>{value === 'llm' ? 'LLM' : value === 'rules' ? 'Rules' : 'Compare'}</button>)}</div>
        <button className="analyze-btn" disabled={!images.length || loading} onClick={analyzeImages}>
          {loading ? <><span className="spinner" />Processing…</> : `Analyze ${images.length || ''} receipt${images.length === 1 ? '' : 's'}`}</button>
        {loading && <p role="status" aria-live="polite">{progress}</p>}
        {error && <div className="error-message" role="alert">{error}</div>}
      </div>
      <div className="card results-panel" aria-busy={loading}>
        <h2>Results</h2>
        {!Object.keys(results).length && <div className="empty-state">Select receipts and click Analyze to see results.</div>}
        {Object.entries(results).map(([method, batch]) => <BatchResults key={method} method={method} batch={batch} />)}
      </div>
    </div>
  </div>
}

function BatchResults({ method, batch }) {
  const [downloadError, setDownloadError] = useState(null)
  const [downloading, setDownloading] = useState(false)
  async function download() {
    setDownloadError(null)
    setDownloading(true)
    try {
      const response = await axios.get(`${API_URL}${batch.download_url}`, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = batch.export_filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setDownloadError('Download failed. Check the backend connection and try again.')
    } finally { setDownloading(false) }
  }
  if (batch.requestError) return <section><h3>{method.toUpperCase()}</h3><p className="error-message" role="alert">{batch.requestError}</p></section>
  const missingTotals = batch.receipts.filter(receipt => receipt.status === 'success' && receipt.data.total == null).length
  return <section className="batch-results">
    <h3>{method.toUpperCase()}</h3>
    <p>{batch.successful_count} succeeded · {batch.failed_count} failed</p>
    <div className="result-field"><label>Combined grand total</label><div className="value large">{money(batch.grand_total)}</div></div>
    {missingTotals > 0 && <p>{missingTotals} receipt(s) have no detected total and are excluded from this sum.</p>}
    {batch.download_url && <button className="mode-btn" onClick={download} disabled={downloading}>{downloading ? 'Downloading…' : 'Download Excel (.xlsx)'}</button>}
    {(batch.export_error || downloadError) && <p className="error-message" role="alert">{batch.export_error || downloadError}</p>}
    <h4>Individual receipts</h4>
    {batch.receipts.map(receipt => <details className="receipt-result" key={receipt.receipt_id} open>
      <summary>#{receipt.receipt_id} {receipt.filename} — {receipt.status}</summary>
      {receipt.error ? <p className="error-message">{receipt.error}</p> : <>
        <p>Vendor: {receipt.data.vendor || 'Not detected'}</p><p>Date: {receipt.data.date || 'Not detected'}</p>
        <p><strong>Receipt total: {money(receipt.data.total)}</strong></p>
        <ul>{receipt.data.items.map((item, index) => <li key={index}>{item.item_name || 'Not detected'}: {money(item.price)}</li>)}</ul>
      </>}
    </details>)}
    <h4>All extracted items ({batch.items.length})</h4>
    <div className="table-scroll"><table className="items-table"><thead><tr>
      <th>Receipt</th><th>Filename</th><th>Vendor</th><th>Date</th><th>Item</th><th>Price</th>
    </tr></thead><tbody>{batch.items.map((item, index) => <tr key={index}>
      <td>{item.receipt_id}</td><td>{item.filename}</td><td>{item.vendor || 'Not detected'}</td>
      <td>{item.date || 'Not detected'}</td><td>{item.item_name || 'Not detected'}</td><td>{money(item.price)}</td>
    </tr>)}</tbody></table></div>
  </section>
}

export default App
