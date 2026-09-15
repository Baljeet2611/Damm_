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
  const hasAxis = 'has_reservoir_boundary' in project ? !project.dam_point || project.has_reservoir_boundary : !!('dam_axis_file' in project && project.dam_axis_file)
  const hasDomain = 'has_model_domain' in project && project.has_model_domain != null ? project.has_model_domain : !!('model_domain_file' in project && project.model_domain_file)
  const hasOutlet = 'has_downstream_outlet' in project && project.has_downstream_outlet != null ? project.has_downstream_outlet : !!('downstream_outlet_file' in project && project.downstream_outlet_file)
  const isHypothetical = (project.provenance === 'HYPOTHETICAL_UNVERIFIED') ||
    project.project_name.toLowerCase().includes('demo') ||
    project.project_name.toLowerCase().includes('hypothetical')

  return (
    <div className="custom-dam-map-overlay">
      <div className="custom-dam-map-card">
        <div className="custom-dam-card-header">
          <div className="custom-dam-title-group">
            <span className="custom-dam-badge">
              {isHypothetical ? 'HYPOTHETICAL DEMO CONFIGURATION' : (scientificStatus ? scientificStatus.toUpperCase() : 'CUSTOM ONBOARDED STUDY')}
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
        <div className="custom-dam-notice-box" style={{ background: '#451a03', border: '1px solid #f59e0b', color: '#fef3c7' }}>
          <span className="notice-icon">⚠️</span>
          <span className="notice-text">
            <strong>Hypothetical Demonstration Configuration</strong> — Not for engineering or operational decision-making. No simulation has been certified.
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

          {hasDomain && (
            <div className="custom-legend-item">
              <span style={{ width: '14px', height: '14px', border: '2px dashed #a78bfa', background: 'rgba(139, 92, 246, 0.2)', borderRadius: '2px', display: 'inline-block' }} />
              <span className="legend-label">Simulation Model Domain</span>
            </div>
          )}

          {('has_reservoir_boundary' in project ? project.has_reservoir_boundary : !!project.reservoir_boundary_file) && (
            <div className="custom-legend-item">
              <span className="legend-chip-reservoir" />
              <span className="legend-label">Reservoir Pool Boundary</span>
            </div>
          )}

          {hasAxis && (
            <div className="custom-legend-item">
              <span className="legend-chip-axis" />
              <span className="legend-label">Dam Crest Axis</span>
            </div>
          )}

          {hasOutlet && (
            <div className="custom-legend-item">
              <span style={{ width: '14px', height: '3px', background: '#10b981', display: 'inline-block' }} />
              <span className="legend-label">Downstream Model Outlet</span>
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
