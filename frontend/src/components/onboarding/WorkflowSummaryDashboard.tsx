import React, { useEffect, useState } from 'react';
import {
  ShieldAlert, Activity, Gauge,
  Waves, Users, AlertTriangle, Download,
  Satellite, CheckCircle2, FileText, RefreshCw
} from 'lucide-react';
import { fetchWorkflowSummary } from '../../api/damProjects';
import type { HidkalWorkflowSummaryResponse } from '../../types/damProjects';
import './WorkflowSummaryDashboard.css';

interface WorkflowSummaryDashboardProps {
  projectId?: string;
  onNavigateToTab?: (tab: string) => void;
}

export const WorkflowSummaryDashboard: React.FC<WorkflowSummaryDashboardProps> = ({
  projectId,
  onNavigateToTab: _onNavigateToTab,
}) => {
  const [data, setData] = useState<HidkalWorkflowSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const targetProjectId = projectId || 'sample_hidkal';

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchWorkflowSummary(targetProjectId);
      setData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load workflow summary');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [targetProjectId]);

  if (loading) {
    return (
      <div className="workflow-dashboard-container" style={{ textAlign: 'center', padding: '3rem' }}>
        <RefreshCw className="animate-spin" size={28} style={{ color: '#38bdf8', margin: '0 auto 1rem' }} />
        <div style={{ color: '#94a3b8' }}>Loading Unified PS-161 End-to-End Workflow Summary...</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="workflow-dashboard-container">
        <div className="warnings-box" style={{ background: 'rgba(239, 68, 68, 0.1)', borderColor: 'rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}>
          <strong>Error Loading Workflow Summary:</strong> {error || 'No workflow data returned'}
          <div style={{ marginTop: '0.5rem' }}>
            <button onClick={loadData} className="export-btn" style={{ borderColor: '#fca5a5', color: '#fca5a5' }}>Retry</button>
          </div>
        </div>
      </div>
    );
  }

  const {
    project_name,
    scenario,
    available_engines,
    latest_canonical_results,
    exposure_summary,
    hadr_decision_support,
    gis_export,
    gee_validation,
    provenance_warnings,
  } = data;

  return (
    <div className="workflow-dashboard-container">
      {/* Top Header */}
      <div className="workflow-header">
        <div>
          <h2 className="workflow-title">
            <Activity size={20} /> Unified PS-161 Workflow Summary
          </h2>
          <div className="workflow-subtitle">
            Project: <strong style={{ color: '#e2e8f0' }}>{project_name}</strong> | ID: <code>{targetProjectId.slice(0, 8)}...</code>
          </div>
        </div>
        <button onClick={loadData} className="export-btn" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <RefreshCw size={13} /> Refresh Summary
        </button>
      </div>

      {/* Row 1: Scenario Parameters & Multi-Engine Status */}
      <div className="workflow-grid-2">
        {/* Scenario Card */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <FileText size={16} style={{ color: '#38bdf8' }} /> Canonical Scenario Baseline
          </h3>
          {scenario ? (
            <>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Scenario Type</span>
                <span className="workflow-metric-val">{scenario.scenario_type}</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Initial Water Level / FRL</span>
                <span className="workflow-metric-val">{scenario.initial_water_level_m?.toFixed(2)} m</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Breach Width & Depth</span>
                <span className="workflow-metric-val">{scenario.breach_width_m} m × {scenario.breach_depth_m || 35.0} m</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Manning Roughness n</span>
                <span className="workflow-metric-val">{scenario.manning_roughness}</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Simulation Duration</span>
                <span className="workflow-metric-val">{(scenario.simulation_duration_s / 3600).toFixed(1)} hrs ({scenario.simulation_duration_s}s)</span>
              </div>
            </>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>No canonical scenario generated yet.</div>
          )}
        </div>

        {/* Multi-Engine Availability & Status */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <Gauge size={16} style={{ color: '#38bdf8' }} /> Multi-Engine Status Matrix
          </h3>
          {Object.entries(available_engines).map(([engKey, engStatus]) => (
            <div key={engKey} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '0.4rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                <span style={{ fontWeight: 700, fontSize: '0.825rem', textTransform: 'uppercase' }}>{engKey}</span>
                {engStatus.solver_status === 'available' ? (
                  <span className="engine-status-badge available">
                    <CheckCircle2 size={12} /> Live Solver Ready
                  </span>
                ) : (
                  <span className="engine-status-badge unavailable">
                    <AlertTriangle size={12} /> {engStatus.solver_status}
                  </span>
                )}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                Runs completed: <strong style={{ color: '#e2e8f0' }}>{engStatus.completed_runs_count}</strong> | Package: <strong>Ready</strong> | Ingestion: <strong>Ready</strong>
              </div>
              {engStatus.reason && (
                <div style={{ fontSize: '0.72rem', color: '#fbbf24', marginTop: '2px' }}>
                  ℹ️ {engStatus.reason}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Row 2: Canonical Simulation Results Across Engines */}
      <div className="workflow-card">
        <h3 className="workflow-card-title">
          <Waves size={16} style={{ color: '#38bdf8' }} /> Latest Simulation Results (Canonical Outputs)
        </h3>
        <div className="workflow-grid-3">
          {['anuga', 'pysph', 'delft3d_fm'].map((engKey) => {
            const res = latest_canonical_results[engKey];
            return (
              <div key={engKey} style={{ background: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <strong style={{ textTransform: 'uppercase', fontSize: '0.8rem', color: '#38bdf8' }}>{engKey}</strong>
                  <span style={{ fontSize: '0.725rem', color: res ? '#4ade80' : '#94a3b8' }}>
                    {res ? 'Completed' : 'No Runs Yet'}
                  </span>
                </div>
                {res ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', fontSize: '0.775rem' }}>
                    <div>Max Depth: <strong>{res.maximum_depth_m ? `${res.maximum_depth_m.toFixed(2)} m` : 'N/A'}</strong></div>
                    <div>Max Velocity: <strong>{res.maximum_velocity_ms ? `${res.maximum_velocity_ms.toFixed(2)} m/s` : 'N/A'}</strong></div>
                    <div>Flood Extent: <strong>{res.flood_extent_km2 ? `${res.flood_extent_km2.toFixed(2)} km²` : 'N/A'}</strong></div>
                    {res.hydrograph && (
                      <div style={{ color: '#38bdf8' }}>Q Peak: <strong>{res.hydrograph.q_peak_cms?.toFixed(0)} m³/s</strong></div>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Run or import a simulation to populate results.</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Row 3: Exposure, HADR & Decision Support */}
      <div className="workflow-grid-2">
        {/* Exposure Summary */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <Users size={16} style={{ color: '#38bdf8' }} /> Population & Infrastructure Exposure
          </h3>
          {exposure_summary ? (
            <>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Exposed Population</span>
                <span className="workflow-metric-val" style={{ color: '#f87171' }}>{exposure_summary.total_exposed_population?.toLocaleString()} persons</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Exposed Buildings</span>
                <span className="workflow-metric-val">{exposure_summary.exposed_buildings_count?.toLocaleString()} structures</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Flooded Road Network</span>
                <span className="workflow-metric-val">{exposure_summary.flooded_road_length_km?.toFixed(1)} km</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Critical Infrastructure Assets</span>
                <span className="workflow-metric-val">{exposure_summary.critical_facilities_exposed} facilities</span>
              </div>
            </>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>Run exposure assessment to calculate affected population & assets.</div>
          )}
        </div>

        {/* HADR Decision Support */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <ShieldAlert size={16} style={{ color: '#38bdf8' }} /> HADR Decision Support & Downstream Severity
          </h3>
          {hadr_decision_support ? (
            <>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Primary Solver</span>
                <span className="workflow-metric-val">{hadr_decision_support.source_engine?.toUpperCase()}</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Peak Inflow / Discharge</span>
                <span className="workflow-metric-val">{hadr_decision_support.peak_discharge_cms?.toFixed(0)} m³/s</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">High Severity Corridor</span>
                <span className="workflow-metric-val" style={{ color: '#fb923c' }}>{hadr_decision_support.high_severity_area_km2?.toFixed(2)} km²</span>
              </div>
              <div className="workflow-metric-row">
                <span className="workflow-metric-label">Modeled Critical Evacuation Points</span>
                <span className="workflow-metric-val">{hadr_decision_support.critical_points_count} points</span>
              </div>
            </>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>Decision support summary ready on hydrodynamic run completion.</div>
          )}
        </div>
      </div>

      {/* Row 4: GIS Export & Satellite Earth Observation Status */}
      <div className="workflow-grid-2">
        {/* GIS Export */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <Download size={16} style={{ color: '#38bdf8' }} /> Geospatial Data Exports
          </h3>
          <div style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>Direct vector download endpoints for GIS & civil emergency planning:</div>
          <div className="export-button-group">
            {Object.entries(gis_export.endpoints).map(([name, url]) => (
              <a
                key={name}
                href={url.startsWith('http') ? url : `http://localhost:8000${url}`}
                target="_blank"
                rel="noreferrer"
                className="export-btn"
              >
                {name.replace('_', ' ').toUpperCase()}
              </a>
            ))}
          </div>
        </div>

        {/* GEE Validation */}
        <div className="workflow-card">
          <h3 className="workflow-card-title">
            <Satellite size={16} style={{ color: '#38bdf8' }} /> Satellite Earth Observation (Sentinel-1 SAR)
          </h3>
          <div style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>
            Status: <strong>Gated / Offline Adapter</strong>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
            {gee_validation.gated_reason}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
            Whitelisted Collections: <code>{gee_validation.whitelisted_datasets.join(', ')}</code>
          </div>
        </div>
      </div>

      {/* Provenance Warnings & Disclaimers */}
      {provenance_warnings && provenance_warnings.length > 0 && (
        <div className="warnings-box">
          <strong>Scientific Integrity & Verification Notes:</strong>
          <ul>
            {provenance_warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
