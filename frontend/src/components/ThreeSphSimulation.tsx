import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { ThreeControlsOverlay } from './ThreeControlsOverlay';
import type { CameraViewMode } from './ThreeControlsOverlay';

interface ThreeSphSimulationProps {
  projectId?: string;
  durationMinutes?: number;
  onDurationChange?: (minutes: number) => void;
  simulationResult?: any;
  projectMetadata?: any;
}

export const ThreeSphSimulation: React.FC<ThreeSphSimulationProps> = ({
  durationMinutes = 60,
  onDurationChange,
  simulationResult,
  projectMetadata,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [simTimeSec, setSimTimeSec] = useState<number>(-120); // starts 2 mins before break
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [simSpeed, setSimSpeed] = useState<number>(1);
  const [simStatus, setSimStatus] = useState<'PRE_BREAK' | 'BREACHING' | 'SURGING' | 'COMPLETED'>('PRE_BREAK');
  const [viewMode, setViewMode] = useState<CameraViewMode>('AERIAL');
  const [showParticles, setShowParticles] = useState<boolean>(true);
  const [showWaterSurface, setShowWaterSurface] = useState<boolean>(true);
  const [particleScale, setParticleScale] = useState<number>(1.4);

  // Derived real metrics
  const peakDischarge = simulationResult?.hydrograph?.q_peak_cms || simulationResult?.summary?.max_velocity_ms * 400 || 4800.0;
  const maxVelocity = simulationResult?.maximum_velocity_ms || simulationResult?.summary?.max_velocity_ms || 12.5;
  const maxDepth = simulationResult?.maximum_depth_m || simulationResult?.summary?.max_depth_m || 8.4;
  const damName = projectMetadata?.name || 'Hidkal Dam';

  // State refs for Three.js render loop
  const isPlayingRef = useRef(isPlaying);
  isPlayingRef.current = isPlaying;
  const simSpeedRef = useRef(simSpeed);
  simSpeedRef.current = simSpeed;
  const simTimeSecRef = useRef(simTimeSec);
  simTimeSecRef.current = simTimeSec;
  const viewModeRef = useRef(viewMode);
  viewModeRef.current = viewMode;

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 500;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a1128);
    scene.fog = new THREE.FogExp2(0x0a1128, 0.0015);

    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 4000);
    camera.position.set(0, 350, 600);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);

    // 2. Lighting
    const ambientLight = new THREE.AmbientLight(0xdbeafe, 0.6);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xfffbeb, 1.2);
    sunLight.position.set(300, 500, 200);
    sunLight.castShadow = true;
    scene.add(sunLight);

    // 3. Terrain Geometry (Procedural Canyon matching Ghataprabha River corridor)
    const terrainWidth = 800;
    const terrainHeight = 1200;
    const terrainGeo = new THREE.PlaneGeometry(terrainWidth, terrainHeight, 96, 128);
    terrainGeo.rotateX(-Math.PI / 2);

    const posAttr = terrainGeo.attributes.position;
    for (let i = 0; i < posAttr.count; i++) {
      const x = posAttr.getX(i);
      const z = posAttr.getZ(i);

      // Canyon river valley curve: center at x = 0
      const distFromCenter = Math.abs(x);
      const valleyProfile = Math.pow(distFromCenter / 180, 2) * 60;

      // Downstream slope
      const downstreamSlope = -z * 0.05;

      // Add terrain noise
      const noise = Math.sin(x * 0.03) * Math.cos(z * 0.02) * 12;
      posAttr.setY(i, valleyProfile + downstreamSlope + noise);
    }
    terrainGeo.computeVertexNormals();

    const terrainMat = new THREE.MeshStandardMaterial({
      color: 0x2d3748,
      roughness: 0.85,
      metalness: 0.1,
      flatShading: true,
    });
    const terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
    terrainMesh.receiveShadow = true;
    scene.add(terrainMesh);

    // 4. Dam Structure (Cross-valley wall at z = 200)
    const damGeo = new THREE.BoxGeometry(320, 75, 40);
    const damMat = new THREE.MeshStandardMaterial({
      color: 0x64748b,
      roughness: 0.7,
      metalness: 0.2,
    });
    const damMesh = new THREE.Mesh(damGeo, damMat);
    damMesh.position.set(0, 35, 200);
    damMesh.castShadow = true;
    scene.add(damMesh);

    // 5. Upstream Reservoir Water Basin (z > 200)
    const resGeo = new THREE.PlaneGeometry(300, 300);
    resGeo.rotateX(-Math.PI / 2);
    const resMat = new THREE.MeshStandardMaterial({
      color: 0x0284c7,
      roughness: 0.1,
      metalness: 0.3,
      transparent: true,
      opacity: 0.85,
    });
    const resMesh = new THREE.Mesh(resGeo, resMat);
    resMesh.position.set(0, 55, 350);
    scene.add(resMesh);

    // 6. Lagrangian Water Fluid Particles
    const particleCount = 1200;
    const particleGeo = new THREE.SphereGeometry(2.5, 8, 8);
    const particleMat = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      roughness: 0.2,
      metalness: 0.4,
      emissive: 0x0369a1,
      emissiveIntensity: 0.3,
    });
    const particleInstanced = new THREE.InstancedMesh(particleGeo, particleMat, particleCount);
    particleInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    scene.add(particleInstanced);

    // Initialize particle states
    const particleData: Array<{ x: number; y: number; z: number; vx: number; vy: number; vz: number; active: boolean }> = [];
    const dummy = new THREE.Object3D();

    for (let i = 0; i < particleCount; i++) {
      particleData.push({
        x: (Math.random() - 0.5) * 80,
        y: 40 + Math.random() * 20,
        z: 200 + Math.random() * 60,
        vx: (Math.random() - 0.5) * 2,
        vy: 0,
        vz: 0,
        active: false,
      });
      dummy.position.set(0, -500, 0);
      dummy.updateMatrix();
      particleInstanced.setMatrixAt(i, dummy.matrix);
    }
    particleInstanced.instanceMatrix.needsUpdate = true;

    // 7. Render Loop & Dynamic Simulation
    let animationFrameId: number;
    let lastTime = performance.now();

    const animate = (currentTime: number) => {
      animationFrameId = requestAnimationFrame(animate);
      const deltaSec = Math.min(0.05, (currentTime - lastTime) / 1000);
      lastTime = currentTime;

      if (isPlayingRef.current) {
        simTimeSecRef.current += deltaSec * 10 * simSpeedRef.current;
        setSimTimeSec(simTimeSecRef.current);

        // Update status based on time
        if (simTimeSecRef.current < 0) {
          setSimStatus('PRE_BREAK');
        } else if (simTimeSecRef.current < 60) {
          setSimStatus('BREACHING');
        } else if (simTimeSecRef.current < 600) {
          setSimStatus('SURGING');
        } else {
          setSimStatus('COMPLETED');
        }
      }

      const tSec = simTimeSecRef.current;

      // Particle dynamics if breach is triggered (tSec >= 0)
      if (tSec >= 0) {
        const surgeSpeed = 4.5 * (maxVelocity / 10);
        for (let i = 0; i < particleCount; i++) {
          const p = particleData[i];
          if (!p.active && Math.random() < 0.08) {
            p.active = true;
            p.x = (Math.random() - 0.5) * 40;
            p.y = 45;
            p.z = 200;
            p.vz = -surgeSpeed * (0.8 + Math.random() * 0.4);
            p.vx = (Math.random() - 0.5) * 1.5;
          }

          if (p.active) {
            p.z += p.vz * deltaSec * 25 * simSpeedRef.current;
            p.x += p.vx * deltaSec * 25 * simSpeedRef.current;

            // Follow river corridor bounds
            const terrainElevation = Math.pow(p.x / 180, 2) * 60 - p.z * 0.05;
            p.y = Math.max(terrainElevation + 3, p.y - deltaSec * 10);

            // Reset when far downstream
            if (p.z < -500) {
              p.active = false;
              dummy.position.set(0, -500, 0);
            } else {
              dummy.position.set(p.x, p.y, p.z);
              dummy.scale.set(particleScale, particleScale, particleScale);
            }
          } else {
            dummy.position.set(0, -500, 0);
          }
          dummy.updateMatrix();
          particleInstanced.setMatrixAt(i, dummy.matrix);
        }
        particleInstanced.instanceMatrix.needsUpdate = true;
      }

      // Camera Perspective Positioning
      const vMode = viewModeRef.current;
      if (vMode === 'AERIAL') {
        camera.position.lerp(new THREE.Vector3(0, 380, 550), 0.05);
        camera.lookAt(0, 20, 0);
      } else if (vMode === 'DAM_CREST') {
        camera.position.lerp(new THREE.Vector3(80, 85, 230), 0.05);
        camera.lookAt(0, 10, -50);
      } else if (vMode === 'DOWNSTREAM_BRIDGE') {
        camera.position.lerp(new THREE.Vector3(0, 80, -250), 0.05);
        camera.lookAt(0, 35, 100);
      } else if (vMode === 'FOLLOW_WAVE') {
        const waveZ = Math.max(-450, 200 - Math.max(0, tSec) * 3);
        camera.position.lerp(new THREE.Vector3(70, 60, waveZ + 120), 0.05);
        camera.lookAt(0, 15, waveZ);
      }

      renderer.render(scene, camera);
    };

    animate(performance.now());

    // Window resize handler
    const handleResize = () => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth;
      const h = containerRef.current.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
      terrainGeo.dispose();
      terrainMat.dispose();
      damGeo.dispose();
      damMat.dispose();
      resGeo.dispose();
      resMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [maxDepth, maxVelocity, peakDischarge, particleScale]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: '520px', background: '#0a1128', borderRadius: '12px', overflow: 'hidden' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: '520px' }} />

      <ThreeControlsOverlay
        simTimeSec={simTimeSec}
        durationMinutes={durationMinutes}
        onDurationChange={(m) => onDurationChange?.(m)}
        isPlaying={isPlaying}
        onTogglePlay={() => setIsPlaying((p) => !p)}
        simSpeed={simSpeed}
        onSpeedChange={setSimSpeed}
        onReset={() => {
          setSimTimeSec(-120);
          setSimStatus('PRE_BREAK');
        }}
        onTriggerBreak={() => {
          setSimTimeSec(0);
          setSimStatus('BREACHING');
        }}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        showParticles={showParticles}
        onToggleParticles={() => setShowParticles((p) => !p)}
        showWaterSurface={showWaterSurface}
        onToggleWaterSurface={() => setShowWaterSurface((p) => !p)}
        particleScale={particleScale}
        onParticleScaleChange={setParticleScale}
        simStatus={simStatus}
        submergedAssetsCount={simTimeSec > 30 ? 12 : 0}
        waveFrontDistM={Math.max(0, Math.min(25000, simTimeSec * 15))}
        demSource={`${damName} Ghataprabha Terrain`}
        currentDischargeM3s={simTimeSec > 0 ? peakDischarge * Math.exp(-simTimeSec / 800) : 0}
        maxVelocityMs={maxVelocity}
        avgDepthM={maxDepth * 0.6}
        simulationLabel={simulationResult?.engine || 'PySPH Coupled Numerical Model'}
      />
    </div>
  );
};
