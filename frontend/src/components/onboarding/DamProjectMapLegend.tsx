import React from 'react'
import type { DamProjectSummary, DamProjectDetailResponse } from '../../types/damProjects'
import './DamOnboardingPanel.css'

interface DamProjectMapLegendProps {
  project: DamProjectSummary | DamProjectDetailResponse
  onClose: () => void
}

export const DamProjectMapLegend: React.FC<DamProjectMapLegendProps> = ({ project, onClose }) => {
  return (
    <div className="custom-dam-map-overlay">
      <div className="custom-dam-map-card">
        <div className="custom-dam-card-header">
          <div className="custom-dam-title-group">
            <span className="custom-dam-badge">CUSTOM ONBOARDED PROJECT</span>
            <h4 className="custom-dam-title">{project.project_name}</h4>
          </div>
          <button className="btn-close-overlay" onClick={onClose} title="Close custom project layer">
            ✕
          </button>
        </div>

        {/* Persistent Mandatory Scientific Notice */}
        <div className="custom-dam-notice-box">
          <span className="notice-icon">⚠️</span>
          <span className="notice-text">
            <strong>Input geometry only</strong> — no dam-break simulation has been executed for this project.
          </span>
        </div>

        {/* Legend Classification Items */}
        <div className="custom-dam-legend-grid">
          <div className="custom-legend-item">
            <span className="legend-chip-dem" />
            <span className="legend-label">DEM Elevation Raster</span>
          </div>

          <div className="custom-legend-item">
            <span className="legend-chip-axis" />
            <span className="legend-label">User-provided Dam Axis</span>
          </div>

          {('has_reservoir_boundary' in project ? project.has_reservoir_boundary : !!project.reservoir_boundary_file) && (
            <div className="custom-legend-item">
              <span className="legend-chip-reservoir" />
              <span className="legend-label">User-provided Reservoir Boundary</span>
            </div>
          )}

          <div className="custom-legend-item">
            <span className="legend-chip-breach">⚠️</span>
            <span className="legend-label">Hypothetical Breach Location</span>
          </div>
        </div>

        <div className="custom-dam-footer">
          <button className="btn-return-hidkal" onClick={onClose}>
            🎯 Return to Standard Hidkal View
          </button>
        </div>
      </div>
    </div>
  )
}
