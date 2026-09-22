import React, { useState } from 'react';
import {
  Play, Pause, RotateCcw, Clock,
  Gauge, Waves, Sliders, Sparkles,
  Video, ShieldAlert, ShieldCheck, Info
} from 'lucide-react';

export type CameraViewMode = 'AERIAL' | 'DAM_CREST' | 'DOWNSTREAM_BRIDGE' | 'FOLLOW_WAVE';
export type ParticleRenderMode = '3D_SPHERES' | 'POINT_BEADS';

interface ThreeControlsOverlayProps {
  simTimeSec: number;
  durationMinutes?: number;
  onDurationChange?: (minutes: number) => void;
  isPlaying: boolean;
  onTogglePlay: () => void;
  simSpeed: number;
  onSpeedChange: (speed: number) => void;
  onReset: () => void;
  onTriggerBreak: () => void;
  viewMode: CameraViewMode;
  onViewModeChange: (view: CameraViewMode) => void;
  showParticles: boolean;
  onToggleParticles: () => void;
  showWaterSurface: boolean;
  onToggleWaterSurface: () => void;
  particleRenderMode?: ParticleRenderMode;
  onParticleRenderModeChange?: (mode: ParticleRenderMode) => void;
  particleScale?: number;
  onParticleScaleChange?: (scale: number) => void;
  simStatus: 'PRE_BREAK' | 'BREACHING' | 'SURGING' | 'COMPLETED';
  submergedAssetsCount?: number;
  waveFrontDistM: number;
  demSource?: string;
  froudeNumber?: number;
  currentDischargeM3s?: number;
  maxVelocityMs?: number;
  avgDepthM?: number;
  manningN?: number;
  onManningNChange?: (n: number) => void;
  simulationLabel?: string;
}

export const ThreeControlsOverlay: React.FC<ThreeControlsOverlayProps> = ({
  simTimeSec,
  durationMinutes = 60,
  onDurationChange,
  isPlaying,
  onTogglePlay,
  simSpeed,
  onSpeedChange,
  onReset,
  onTriggerBreak,
  viewMode,
  onViewModeChange,
  showParticles,
  onToggleParticles,
  showWaterSurface,
  onToggleWaterSurface,
  particleRenderMode = '3D_SPHERES',
  onParticleRenderModeChange,
  particleScale = 1.4,
  onParticleScaleChange,
  simStatus,
  submergedAssetsCount = 0,
  waveFrontDistM,
  demSource = 'Ghataprabha DEM',
  froudeNumber = 0,
  currentDischargeM3s = 0,
  maxVelocityMs = 0,
  avgDepthM = 0,
  manningN = 0.035,
  simulationLabel = 'PySPH Hydrodynamic Coupled Model',
}) => {
  const [activeTab, setActiveTab] = useState<'METRICS' | 'CAMERA' | 'SETTINGS'>('METRICS');

  const formatTime = (totalSec: number) => {
    const isNegative = totalSec < 0;
    const absSec = Math.abs(Math.round(totalSec));
    const m = Math.floor(absSec / 60);
    const s = absSec % 60;
    const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
    if (isNegative) {
      return `T - ${pad(m)}:${pad(s)} (Pre-Break)`;
    }
    return `T + ${pad(m)}:${pad(s)} (Active Flood)`;
  };

  const getStatusBadge = () => {
    switch (simStatus) {
      case 'PRE_BREAK':
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 8px', borderRadius: '6px', fontSize: '11px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            <ShieldCheck size={13} /> Intact Reservoir Baseline
          </span>
        );
      case 'BREACHING':
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 8px', borderRadius: '6px', fontSize: '11px', background: 'rgba(239, 68, 68, 0.2)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.4)' }}>
            <ShieldAlert size={13} /> Breach Failure Active
          </span>
        );
      case 'SURGING':
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 8px', borderRadius: '6px', fontSize: '11px', background: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.4)' }}>
            <Waves size={13} /> Wave Surging Downstream
          </span>
        );
      case 'COMPLETED':
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 8px', borderRadius: '6px', fontSize: '11px', background: 'rgba(34, 197, 94, 0.2)', color: '#22c55e', border: '1px solid rgba(34, 197, 94, 0.4)' }}>
            <ShieldCheck size={13} /> Simulation Complete
          </span>
        );
    }
  };

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '16px' }}>
      {/* Top Header Card */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', pointerEvents: 'auto' }}>
        <div style={{ background: 'rgba(15, 23, 42, 0.85)', backdropFilter: 'blur(8px)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '10px', padding: '12px 16px', color: '#f8fafc', maxWidth: '420px', boxShadow: '0 8px 32px rgba(0,0,0,0.37)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span style={{ fontWeight: 700, fontSize: '14px', color: '#38bdf8' }}>3D Near-Field Fluid Visualizer</span>
            {getStatusBadge()}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
            Source: <strong style={{ color: '#e2e8f0' }}>{demSource}</strong> | Model: <strong style={{ color: '#e2e8f0' }}>{simulationLabel}</strong>
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Info size={12} /> Visualization derived from genuine hydraulic outputs & terrain bounds
          </div>
        </div>

        {/* Tab Navigation Controls */}
        <div style={{ display: 'flex', gap: '6px', background: 'rgba(15, 23, 42, 0.85)', backdropFilter: 'blur(8px)', padding: '4px', borderRadius: '8px', border: '1px solid rgba(255, 255, 255, 0.1)', pointerEvents: 'auto' }}>
          {(['METRICS', 'CAMERA', 'SETTINGS'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                background: activeTab === tab ? '#0284c7' : 'transparent',
                color: activeTab === tab ? '#fff' : '#94a3b8',
                border: 'none',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {tab === 'METRICS' && 'Telemetry'}
              {tab === 'CAMERA' && 'Cameras'}
              {tab === 'SETTINGS' && 'Render'}
            </button>
          ))}
        </div>
      </div>

      {/* Floating Side Info Panel */}
      <div style={{ display: 'flex', justifyContent: 'flex-start', pointerEvents: 'auto' }}>
        <div style={{ background: 'rgba(15, 23, 42, 0.88)', backdropFilter: 'blur(8px)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '10px', padding: '14px', color: '#f8fafc', width: '280px', boxShadow: '0 8px 32px rgba(0,0,0,0.37)' }}>
          {activeTab === 'METRICS' && (
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#38bdf8', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Gauge size={14} /> Hydraulic Telemetry
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '11px' }}>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Discharge Q</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{currentDischargeM3s.toFixed(1)} <span style={{ fontSize: '10px' }}>m³/s</span></div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Max Velocity</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{maxVelocityMs.toFixed(1)} <span style={{ fontSize: '10px' }}>m/s</span></div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Average Depth</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{avgDepthM.toFixed(1)} <span style={{ fontSize: '10px' }}>m</span></div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Wave Front</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{(waveFrontDistM / 1000).toFixed(2)} <span style={{ fontSize: '10px' }}>km</span></div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Manning n</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{manningN.toFixed(3)}</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '6px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8' }}>Froude Fr</div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>{froudeNumber > 0 ? froudeNumber.toFixed(2) : (maxVelocityMs / Math.max(1, Math.sqrt(9.81 * Math.max(0.1, avgDepthM)))).toFixed(2)}</div>
                </div>
              </div>
              {submergedAssetsCount > 0 && (
                <div style={{ marginTop: '8px', padding: '4px 8px', background: 'rgba(239, 68, 68, 0.15)', borderRadius: '6px', fontSize: '10px', color: '#f87171' }}>
                  ⚠️ Inundated Infrastructure Assets: ~{submergedAssetsCount}
                </div>
              )}
            </div>
          )}

          {activeTab === 'CAMERA' && (
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#38bdf8', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Video size={14} /> Camera Perspectives
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {[
                  { id: 'AERIAL', label: 'Aerial Overview' },
                  { id: 'DAM_CREST', label: 'Dam Crest View' },
                  { id: 'DOWNSTREAM_BRIDGE', label: 'Downstream Reach' },
                  { id: 'FOLLOW_WAVE', label: 'Follow Wave Front' },
                ].map((c) => (
                  <button
                    key={c.id}
                    onClick={() => onViewModeChange(c.id as CameraViewMode)}
                    style={{
                      background: viewMode === c.id ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255,255,255,0.04)',
                      color: viewMode === c.id ? '#38bdf8' : '#cbd5e1',
                      border: viewMode === c.id ? '1px solid #38bdf8' : '1px solid transparent',
                      borderRadius: '6px',
                      padding: '6px 10px',
                      fontSize: '11px',
                      textAlign: 'left',
                      cursor: 'pointer',
                    }}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'SETTINGS' && (
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#38bdf8', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sliders size={14} /> Visualizer Controls
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '11px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>3D Droplets</span>
                  <button
                    onClick={onToggleParticles}
                    style={{
                      background: showParticles ? '#0284c7' : '#334155',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '3px 8px',
                      fontSize: '10px',
                      cursor: 'pointer',
                    }}
                  >
                    {showParticles ? 'Enabled' : 'Disabled'}
                  </button>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>Water Surface</span>
                  <button
                    onClick={onToggleWaterSurface}
                    style={{
                      background: showWaterSurface ? '#0284c7' : '#334155',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '3px 8px',
                      fontSize: '10px',
                      cursor: 'pointer',
                    }}
                  >
                    {showWaterSurface ? 'Visible' : 'Hidden'}
                  </button>
                </div>
                {onParticleRenderModeChange && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>Render Mode</span>
                    <button
                      onClick={() => onParticleRenderModeChange(particleRenderMode === '3D_SPHERES' ? 'POINT_BEADS' : '3D_SPHERES')}
                      style={{
                        background: '#334155',
                        color: '#38bdf8',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                        borderRadius: '4px',
                        padding: '3px 6px',
                        fontSize: '10px',
                        cursor: 'pointer',
                      }}
                    >
                      {particleRenderMode}
                    </button>
                  </div>
                )}
                {onParticleScaleChange && (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
                      <span>Particle Scale</span>
                      <span>{particleScale.toFixed(1)}x</span>
                    </div>
                    <input
                      type="range"
                      min="0.5"
                      max="3.0"
                      step="0.1"
                      value={particleScale}
                      onChange={(e) => onParticleScaleChange(parseFloat(e.target.value))}
                      style={{ width: '100%' }}
                    />
                  </div>
                )}
                {onDurationChange && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8' }}>
                    <span>Target Duration:</span>
                    <span>{durationMinutes} min</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Timeline & Playback Controller */}
      <div style={{ display: 'flex', justifyContent: 'center', pointerEvents: 'auto' }}>
        <div style={{ background: 'rgba(15, 23, 42, 0.92)', backdropFilter: 'blur(10px)', border: '1px solid rgba(255, 255, 255, 0.12)', borderRadius: '12px', padding: '10px 18px', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '16px', boxShadow: '0 10px 40px rgba(0,0,0,0.5)' }}>
          <button
            onClick={onTogglePlay}
            style={{
              background: isPlaying ? '#ef4444' : '#0284c7',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 14px',
              fontWeight: 700,
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
            }}
          >
            {isPlaying ? <Pause size={15} /> : <Play size={15} />}
            {isPlaying ? 'Pause' : 'Play'}
          </button>

          <button
            onClick={onReset}
            style={{
              background: 'rgba(255,255,255,0.06)',
              color: '#cbd5e1',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
              padding: '8px 10px',
              cursor: 'pointer',
            }}
            title="Reset Simulation"
          >
            <RotateCcw size={14} />
          </button>

          {simStatus === 'PRE_BREAK' && (
            <button
              onClick={onTriggerBreak}
              style={{
                background: 'linear-gradient(135deg, #dc2626, #b91c1c)',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '8px 14px',
                fontWeight: 700,
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <Sparkles size={14} /> Trigger Dam Breach
            </button>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#cbd5e1', fontSize: '13px', fontWeight: 600 }}>
            <Clock size={15} style={{ color: '#38bdf8' }} />
            <span>{formatTime(simTimeSec)}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94a3b8', fontSize: '11px' }}>
            <span>Speed:</span>
            {[1, 2, 5].map((s) => (
              <button
                key={s}
                onClick={() => onSpeedChange(s)}
                style={{
                  background: simSpeed === s ? '#0284c7' : 'rgba(255,255,255,0.05)',
                  color: simSpeed === s ? '#fff' : '#94a3b8',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '3px 7px',
                  fontSize: '10px',
                  cursor: 'pointer',
                }}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
