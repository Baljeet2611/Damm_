import React, { useEffect, useState } from 'react'
import type { SystemHealthSummaryResponse, SubsystemHealth } from '../../types/damProjects'
import { getSystemHealthSummary } from '../../api/damProjects'
import './SystemHealthPanel.css'

interface SystemHealthPanelProps {
  onSelectSubsystem?: (subsystemId: string) => void
}

export const SystemHealthPanel: React.FC<SystemHealthPanelProps> = ({ onSelectSubsystem }) => {
  const [healthData, setHealthData] = useState<SystemHealthSummaryResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState<boolean>(false)
  const [selectedSubsystemId, setSelectedSubsystemId] = useState<string | null>(null)

  const fetchHealth = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await getSystemHealthSummary()
      setHealthData(data)
    } catch (err: any) {
      setError(err?.message || 'Failed to retrieve system health status')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let isMounted = true
    getSystemHealthSummary()
      .then((data) => {
        if (isMounted) {
          setHealthData(data)
          setLoading(false)
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setError(err?.message || 'Failed to retrieve system health status')
          setLoading(false)
        }
      })
    return () => {
      isMounted = false
    }
  }, [])

  const getStatusIcon = (status: SubsystemHealth['status']) => {
    switch (status) {
      case 'ready':
        return '🟢'
      case 'execution_disabled':
        return '🟡'
      case 'available_not_configured':
        return '🟣'
      case 'missing_data':
        return '🟠'
      case 'failed':
        return '🔴'
      case 'unavailable':
      default:
        return '⚪'
    }
  }

  const handleChipClick = (subsystem: SubsystemHealth) => {
    setSelectedSubsystemId(subsystem.id)
    setIsExpanded(true)
    if (onSelectSubsystem) {
      onSelectSubsystem(subsystem.id)
    }
  }

  return (
    <div className="health-panel-container">
      <div className="health-header">
        <div className="health-title">
          <span>🩺</span>
          <span>System Capability & Health Status</span>
        </div>
        <div className="health-summary-actions">
          <button
            className="health-btn-toggle"
            onClick={fetchHealth}
            title="Refresh system capability checks"
          >
            🔄 Refresh
          </button>
          <button
            className="health-btn-toggle"
            onClick={() => setIsExpanded((prev) => !prev)}
            title="Toggle detailed subsystem breakdown"
          >
            {isExpanded ? '▲ Hide Details' : '▼ Inspect All'}
          </button>
        </div>
      </div>

      {loading && !healthData && (
        <div className="health-loading">
          <span className="spinner" /> Polling subsystem capability matrix...
        </div>
      )}

      {error && !healthData && (
        <div style={{ fontSize: '0.72rem', color: '#f87171', padding: '0.3rem 0' }}>
          ⚠️ {error} — backend API connection required.
        </div>
      )}

      {healthData && (
        <>
          <div className="health-chips-grid">
            {healthData.subsystems.map((sub) => (
              <div
                key={sub.id}
                className={`health-chip status-${sub.status}`}
                onClick={() => handleChipClick(sub)}
                title={`${sub.name}: ${sub.status_label}\n${sub.details}`}
                style={{
                  outline: selectedSubsystemId === sub.id ? '2px solid #38bdf8' : undefined,
                }}
              >
                <div className="health-chip-name">{sub.name}</div>
                <div className="health-chip-status">
                  <span>{getStatusIcon(sub.status)}</span>
                  <span>{sub.status_label}</span>
                </div>
              </div>
            ))}
          </div>

          {isExpanded && (
            <div className="health-details-drawer">
              <table className="health-drawer-table">
                <thead>
                  <tr>
                    <th>Subsystem</th>
                    <th>Status</th>
                    <th>Environment</th>
                    <th>Details & Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {healthData.subsystems.map((sub) => (
                    <tr
                      key={sub.id}
                      style={{
                        background: selectedSubsystemId === sub.id ? 'rgba(56, 189, 248, 0.1)' : undefined,
                      }}
                    >
                      <td style={{ fontWeight: 600 }}>{sub.name}</td>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                          <span>{getStatusIcon(sub.status)}</span>
                          <span>{sub.status_label}</span>
                        </span>
                      </td>
                      <td>
                        {sub.environment ? (
                          <span className="health-detail-env">{sub.environment}</span>
                        ) : (
                          <span style={{ color: '#64748b' }}>None</span>
                        )}
                        {sub.version && (
                          <div style={{ fontSize: '0.66rem', color: '#94a3b8' }}>v{sub.version}</div>
                        )}
                      </td>
                      <td>
                        <div>{sub.details}</div>
                        {sub.scientific_caveat && (
                          <div className="health-detail-caveat">⚠️ {sub.scientific_caveat}</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
