import { useEffect, useState } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import './App.css'

interface HealthResponse {
  status: string
}

function App() {
  const [healthStatus, setHealthStatus] = useState<string>('Checking...')
  const [isError, setIsError] = useState<boolean>(false)

  const apiBaseUrl =
    import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  useEffect(() => {
    let isMounted = true

    fetch(`${apiBaseUrl}/api/health`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json() as Promise<HealthResponse>
      })
      .then((data) => {
        if (isMounted) {
          setHealthStatus(data.status)
          setIsError(false)
        }
      })
      .catch((err) => {
        if (isMounted) {
          setHealthStatus(`Offline (${err.message})`)
          setIsError(true)
        }
      })

    return () => {
      isMounted = false
    }
  }, [apiBaseUrl])

  return (
    <main className="app-container">
      <h1>Dam Break Decision Support System</h1>
      <div className="status-card">
        <p>
          Backend Health Status:{' '}
          <span className={isError ? 'status-offline' : 'status-online'}>
            {healthStatus}
          </span>
        </p>
        <p className="status-endpoint">Endpoint: {apiBaseUrl}/api/health</p>
      </div>
    </main>
  )
}

export default App
