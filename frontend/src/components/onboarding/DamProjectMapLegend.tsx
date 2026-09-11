import React from 'react'
import type { DamProjectSummary, DamProjectDetailResponse } from '../../types/damProjects'
import './DamOnboardingPanel.css'

interface DamProjectMapLegendProps {
  project: DamProjectSummary | DamProjectDetailResponse
  onClose: () => void
}

export const DamProjectMapLegend: React.FC<DamProjectMapLegendProps> = ({ project, onClose }) => {
  const damName = 'dam_name' in project ? project.dam_name : undefined
  const damPoint = 'dam_point' in project ? project.dam_point : undefined
  const scientificStatus = 'scientific_status' in project ? project.scientific_status : 'validated_unverified'
  const hasAxis = 'has_reservoir_boundary' in project ? !project.dam_point || project.has_reservoir_boundary : !!project.dam_axis_file

  return (
    <div className="custom-dam-map-overlay">
      <div className="custom-dam-map-card">
        <div className="custom-dam-card-header">
          <div className="custom-dam-title-group">
            <span className="custom-dam-badge">
              {scientificStatus ? scientificStatus.toUpperCase() : 'CUSTOM ONBOARDED STUDY'}
            </span>
            <h4 className="custom-dam-title">
              {project.project_name} {damName ? `• ${damName}` : ''}
            </h4>
          </div>
          <button className="btn-close-overlay" onClick={onClose} title="Close custom project layer">
            ✕
          </button>
        </div>

        {/* Persistent Mandatory Scientific Notice */}
        <div className="custom-dam-notice-box">
          <span className="notice-icon">⚠️</span>
          <span className="notice-text">
            <strong>Input geometry only</strong> — no hydrodynamic dam-break simulation has been executed for this project.
          </span>
        </div>

        {/* Legend Classification Items */}
        <div className="custom-dam-legend-grid">
          <div className="custom-legend-item">
            <span className="legend-chip-dem" />
            <span className="legend-label">DEM Elevation Raster</span>
          </div>

          {damPoint && (
            <div className="custom-legend-item">
              <span style={{ fontSize: '12px' }}>📍</span>
              <span className="legend-label">
                Dam Point ({damPoint.latitude.toFixed(4)}°N, {damPoint.longitude.toFixed(4)}°E)
              </span>
            </div>
          )}

          {hasAxis && (
            <div className="custom-legend-item">
              <span className="legend-chip-axis" />
              <span className="legend-label">User-provided Dam Axis</span>
            </div>
          )}

          {('has_reservoir_boundary' in project ? project.has_reservoir_boundary : !!project.reservoir_boundary_file) && (
            <div className="custom-legend-item">
              <span className="legend-chip-reservoir" />
              <span className="legend-label">User-provided Reservoir Boundary</span>
            </div>
          )}

          {('breach_parameters' in project && project.breach_parameters?.breach_center) && (
            <div className="custom-legend-item">
              <span className="legend-chip-breach">⚠️</span>
              <span className="legend-label">Hypothetical Breach Center</span>
            </div>
          )}
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
