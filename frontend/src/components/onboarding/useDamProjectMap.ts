import { useRef, useCallback } from 'react'
import maplibregl, { Map as MapLibreMap, Marker } from 'maplibre-gl'
import type { DamProjectSummary, DamProjectDetailResponse } from '../../types/damProjects'
import {
  getDamProjectDemTileUrl,
  getDamProjectDamAxisGeometry,
  getDamProjectReservoirGeometry,
  getDamProjectBreachGeometry,
  getDamProjectAnugaLayerTileUrl,
} from '../../api/damProjects'

export function useDamProjectMap(mapRef: React.MutableRefObject<MapLibreMap | null>) {
  const breachMarkerRef = useRef<Marker | null>(null)

  const clearDamProjectMap = useCallback(() => {
    const map = mapRef.current
    if (!map) return

    // Remove breach marker
    if (breachMarkerRef.current) {
      breachMarkerRef.current.remove()
      breachMarkerRef.current = null
    }

    // Remove layers
    const layerIds = [
      'custom-dam-axis-layer',
      'custom-reservoir-line-layer',
      'custom-reservoir-fill-layer',
      'custom-anuga-hazard-layer',
      'custom-dem-tiles-layer',
    ]
    for (const lid of layerIds) {
      if (map.getLayer(lid)) {
        map.removeLayer(lid)
      }
    }

    // Remove sources
    const sourceIds = [
      'custom-dam-axis-source',
      'custom-reservoir-source',
      'custom-anuga-hazard-source',
      'custom-dem-tiles-source',
    ]
    for (const sid of sourceIds) {
      if (map.getSource(sid)) {
        map.removeSource(sid)
      }
    }
  }, [mapRef])

  const displayDamProjectOnMap = useCallback(
    async (project: DamProjectSummary | DamProjectDetailResponse) => {
      const map = mapRef.current
      if (!map) return

      // Clear previous custom layers and markers safely
      clearDamProjectMap()

      const projectId = project.project_id
      const tileUrl = getDamProjectDemTileUrl(projectId)

      // 1. Add DEM Raster Layer
      map.addSource('custom-dem-tiles-source', {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
      })

      // Insert beneath vector layers if existing
      const firstVectorLayer = map.getLayer('roads-line') ? 'roads-line' : undefined

      map.addLayer(
        {
          id: 'custom-dem-tiles-layer',
          type: 'raster',
          source: 'custom-dem-tiles-source',
          paint: {
            'raster-opacity': 0.85,
            'raster-fade-duration': 150,
          },
        },
        firstVectorLayer
      )

      // 2. Fetch and add Reservoir Boundary Geometry if present
      try {
        const reservoirGeo = await getDamProjectReservoirGeometry(projectId)
        if (reservoirGeo && reservoirGeo.features && reservoirGeo.features.length > 0) {
          map.addSource('custom-reservoir-source', {
            type: 'geojson',
            data: reservoirGeo,
          })

          map.addLayer({
            id: 'custom-reservoir-fill-layer',
            type: 'fill',
            source: 'custom-reservoir-source',
            paint: {
              'fill-color': '#0284c7',
              'fill-opacity': 0.3,
            },
          })

          map.addLayer({
            id: 'custom-reservoir-line-layer',
            type: 'line',
            source: 'custom-reservoir-source',
            paint: {
              'line-color': '#38bdf8',
              'line-width': 2,
              'line-dasharray': [2, 2],
            },
          })
        }
      } catch {
        // Reservoir is optional; proceed
      }

      // 3. Fetch and add Dam Axis Geometry
      try {
        const damAxisGeo = await getDamProjectDamAxisGeometry(projectId)
        if (damAxisGeo && damAxisGeo.features && damAxisGeo.features.length > 0) {
          map.addSource('custom-dam-axis-source', {
            type: 'geojson',
            data: damAxisGeo,
          })

          map.addLayer({
            id: 'custom-dam-axis-layer',
            type: 'line',
            source: 'custom-dam-axis-source',
            paint: {
              'line-color': '#dc2626',
              'line-width': 4.5,
            },
          })
        }
      } catch (err) {
        console.error('Failed to display dam axis on map:', err)
      }

      // 4. Fetch and add Breach Location Marker
      try {
        const breachGeo = await getDamProjectBreachGeometry(projectId)
        if (breachGeo && breachGeo.features && breachGeo.features.length > 0) {
          const pt = breachGeo.features[0]
          const coords = pt.geometry.coordinates
          const props = pt.properties || {}

          // Create custom warning marker element
          const el = document.createElement('div')
          el.className = 'custom-breach-marker'
          el.innerHTML = `
            <div style="
              background: #ea580c;
              color: #ffffff;
              font-size: 11px;
              font-weight: 700;
              padding: 3px 8px;
              border-radius: 12px;
              border: 2px solid #ffffff;
              box-shadow: 0 0 12px rgba(234, 88, 12, 0.8);
              display: flex;
              align-items: center;
              gap: 4px;
              cursor: pointer;
              white-space: nowrap;
            ">
              <span>⚠️ Hypothetical Breach</span>
            </div>
          `

          const popupHtml = `
            <div style="color: #0f172a; font-size: 12px; padding: 4px;">
              <strong style="color: #ea580c;">⚠️ Hypothetical Breach Center</strong>
              <p style="margin: 4px 0 0; color: #475569;">
                User-declared, unverified input coordinate.<br/>
                No hydrodynamic simulation has been executed.
              </p>
              ${props.breach_width_m ? `<p style="margin: 4px 0 0;"><strong>Breach Width:</strong> ${props.breach_width_m} m</p>` : ''}
              ${props.reservoir_level ? `<p style="margin: 2px 0 0;"><strong>Reservoir Level:</strong> ${props.reservoir_level}</p>` : ''}
            </div>
          `

          const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
            .setLngLat([coords[0], coords[1]])
            .setPopup(new maplibregl.Popup({ offset: 15 }).setHTML(popupHtml))
            .addTo(map)

          breachMarkerRef.current = marker
        }
      } catch {
        // Breach point optional
      }

      // 5. Fit Map to Project Bounds
      const b = 'bounds' in project ? project.bounds : project.raster_metadata?.bounds
      if (b && b.left < b.right && b.bottom < b.top) {
        if (b.left >= -180 && b.right <= 180 && b.bottom >= -90 && b.top <= 90) {
          map.fitBounds([[b.left, b.bottom], [b.right, b.top]], { padding: 40, maxZoom: 15 })
        }
      }
    },
    [mapRef, clearDamProjectMap]
  )

  const removeDamProjectAnugaHazardRaster = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    if (map.getLayer('custom-anuga-hazard-layer')) {
      map.removeLayer('custom-anuga-hazard-layer')
    }
    if (map.getSource('custom-anuga-hazard-source')) {
      map.removeSource('custom-anuga-hazard-source')
    }
  }, [mapRef])

  const displayDamProjectAnugaHazardRaster = useCallback(
    (projectId: string, runId: string, layer: string, processingId?: string) => {
      const map = mapRef.current
      if (!map) return

      removeDamProjectAnugaHazardRaster()

      let tileUrl = getDamProjectAnugaLayerTileUrl(projectId, runId, layer)
      if (processingId) {
        tileUrl += `?processing_id=${encodeURIComponent(processingId)}`
      }

      map.addSource('custom-anuga-hazard-source', {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
      })

      // Insert above custom DEM layer if present, or before vector layers
      const beforeLayer = map.getLayer('custom-dam-axis-layer')
        ? 'custom-dam-axis-layer'
        : map.getLayer('roads-line')
        ? 'roads-line'
        : undefined

      map.addLayer(
        {
          id: 'custom-anuga-hazard-layer',
          type: 'raster',
          source: 'custom-anuga-hazard-source',
          paint: {
            'raster-opacity': 0.85,
            'raster-fade-duration': 150,
          },
        },
        beforeLayer
      )
    },
    [mapRef, removeDamProjectAnugaHazardRaster]
  )

  return {
    displayDamProjectOnMap,
    clearDamProjectMap,
    displayDamProjectAnugaHazardRaster,
    removeDamProjectAnugaHazardRaster,
  }
}
