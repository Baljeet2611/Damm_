"""
Phase A2: Canonical Unified Scenario Service & Multi-Engine Adapters.

Provides:
1. Canonical scenario lifecycle management (Create, Read, Update, List, Validate)
2. Precise translation adapters for:
   - PySPH (Near-field Lagrangian particle engine)
   - Delft3D FM (Regional Flexible Mesh hydrodynamic model package)
   - ANUGA (2D finite-volume shallow water solver)
   - River Blockage / Landslide Dam (Synthetic valley dual intact/breach solver)
3. Backward-compatible conversion bridges between legacy and canonical representations.
4. Comprehensive provenance tracking for every translated configuration.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from fastapi import HTTPException
from pydantic import BaseModel

from app.schemas import (
    ScenarioType,
    SimulationEngine,
    CanonicalScenario,
    CanonicalScenarioCreateRequest,
    CanonicalScenarioUpdateRequest,
    CanonicalScenarioResponse,
    EngineTranslationResult,
    DamProjectAnugaRunRequest,
    ScenarioCreateRequest,
    ScenarioResponse,
)
from app.raster_service import get_project_root


def get_runtime_scenarios_dir() -> Path:
    """Get the active directory for canonical scenario JSON storage."""
    env_runtime = os.environ.get("SIH_RUNTIME_DIR")
    if env_runtime:
        base_path = Path(env_runtime).resolve()
    else:
        base_path = Path(get_project_root()).resolve() / "runtime"
    scenarios_dir = base_path / "canonical_scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    return scenarios_dir


def validate_scenario_uuid(val: str) -> str:
    """Validate scenario UUID format to prevent path traversal."""
    try:
        parsed = uuid.UUID(str(val).strip())
        return str(parsed)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scenario ID format '{val}'. Must be a valid UUID string.",
        )


# ==============================================================================
# Canonical Scenario Storage & Lifecycle
# ==============================================================================

def create_canonical_scenario(req: CanonicalScenarioCreateRequest) -> CanonicalScenarioResponse:
    """Create and persist a new canonical scenario."""
    scenario_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    scenario = CanonicalScenario(
        scenario_id=scenario_id,
        project_id=req.project_id,
        scenario_name=req.scenario_name,
        scenario_type=req.scenario_type,
        description=req.description,
        dem_dataset_id=req.dem_dataset_id,
        crs=req.crs,
        dam_crest_elevation_m=req.dam_crest_elevation_m,
        dam_location_lon_lat=req.dam_location_lon_lat,
        initial_water_level_m=req.initial_water_level_m,
        reservoir_volume_m3=req.reservoir_volume_m3,
        is_intact_control=req.is_intact_control,
        breach_width_m=req.breach_width_m,
        breach_depth_m=req.breach_depth_m,
        breach_start_time_s=req.breach_start_time_s,
        breach_formation_duration_s=req.breach_formation_duration_s,
        manning_roughness=req.manning_roughness,
        simulation_duration_s=req.simulation_duration_s,
        output_interval_s=req.output_interval_s,
        target_mesh_resolution_m=req.target_mesh_resolution_m,
        selected_engine=req.selected_engine,
        engine_parameters=req.engine_parameters,
        provenance={
            **req.provenance,
            "created_at": now_iso,
            "creator": "unified_scenario_service",
            "schema_version": "1.0",
        },
    )

    save_canonical_scenario(scenario)

    return CanonicalScenarioResponse(
        scenario=scenario,
        created_at=now_iso,
        updated_at=now_iso,
    )


def save_canonical_scenario(scenario: CanonicalScenario) -> Path:
    """Save canonical scenario to JSON storage."""
    scenarios_dir = get_runtime_scenarios_dir()
    filepath = scenarios_dir / f"{scenario.scenario_id}.json"
    data = scenario.dict()
    filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return filepath


def get_canonical_scenario(scenario_id: str) -> CanonicalScenarioResponse:
    """Retrieve canonical scenario by ID."""
    valid_id = validate_scenario_uuid(scenario_id)
    filepath = get_runtime_scenarios_dir() / f"{valid_id}.json"
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Canonical scenario '{valid_id}' not found.")

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        scenario = CanonicalScenario(**data)
        created_at = scenario.provenance.get("created_at", datetime.now(timezone.utc).isoformat())
        updated_at = scenario.provenance.get("updated_at", created_at)
        return CanonicalScenarioResponse(
            scenario=scenario,
            created_at=created_at,
            updated_at=updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load canonical scenario: {str(e)}")


def list_canonical_scenarios(project_id: Optional[str] = None) -> List[CanonicalScenarioResponse]:
    """List all canonical scenarios, optionally filtered by project_id."""
    scenarios_dir = get_runtime_scenarios_dir()
    results: List[CanonicalScenarioResponse] = []

    for item in scenarios_dir.glob("*.json"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
            scenario = CanonicalScenario(**data)
            if project_id and scenario.project_id != project_id:
                continue
            created_at = scenario.provenance.get("created_at", datetime.now(timezone.utc).isoformat())
            updated_at = scenario.provenance.get("updated_at", created_at)
            results.append(
                CanonicalScenarioResponse(
                    scenario=scenario,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        except Exception:
            continue

    return results


def update_canonical_scenario(scenario_id: str, req: CanonicalScenarioUpdateRequest) -> CanonicalScenarioResponse:
    """Update fields on an existing canonical scenario."""
    current_resp = get_canonical_scenario(scenario_id)
    current_dict = current_resp.scenario.dict()

    update_data = req.dict(exclude_unset=True, exclude_none=True)
    if not update_data:
        return current_resp

    current_dict.update(update_data)
    now_iso = datetime.now(timezone.utc).isoformat()
    current_dict["provenance"] = {
        **current_dict.get("provenance", {}),
        "updated_at": now_iso,
    }

    updated_scenario = CanonicalScenario(**current_dict)
    save_canonical_scenario(updated_scenario)

    return CanonicalScenarioResponse(
        scenario=updated_scenario,
        created_at=current_resp.created_at,
        updated_at=now_iso,
    )


# ==============================================================================
# Engine Translation Adapters
# ==============================================================================

def scenario_to_pysph(scenario: CanonicalScenario) -> Dict[str, Any]:
    """
    Translate a canonical Scenario into SPH terrain simulation options.
    Compatible with sph_service.execute_dam_project_sph_terrain_simulation.
    """
    p = scenario.engine_parameters
    return {
        "scenario_id": scenario.scenario_id,
        "project_id": scenario.project_id,
        "particle_spacing_m": float(p.get("particle_spacing_m", 25.0)),
        "duration_s": float(p.get("duration_s", min(scenario.simulation_duration_s, 60.0))),
        "timestep_s": float(p.get("timestep_s", 0.05)),
        "breach_mode": "none" if scenario.is_intact_control else "instantaneous",
        "breach_width_m": float(scenario.breach_width_m),
        "breach_start_time_s": float(scenario.breach_start_time_s),
        "manning_roughness": float(scenario.manning_roughness),
        "target_resolution_m": float(scenario.target_mesh_resolution_m if scenario.target_mesh_resolution_m <= 20.0 else 10.0),
        "arrival_threshold_m": float(p.get("arrival_threshold_m", 0.05)),
        "custom_notes": f"SPH run for scenario: {scenario.scenario_name}",
        "provenance": {
            "source_scenario_id": scenario.scenario_id,
            "scenario_type": scenario.scenario_type.value,
            "engine": SimulationEngine.PYSPH.value,
            "translated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def scenario_to_delft3d(scenario: CanonicalScenario) -> Dict[str, Any]:
    """
    Translate a canonical Scenario into Delft3D D-Flow FM package configuration.
    Compatible with simulation_service.build_model_package and SPH coupling.
    """
    p = scenario.engine_parameters
    return {
        "scenario_id": scenario.scenario_id,
        "project_id": scenario.project_id,
        "name": scenario.scenario_name,
        "description": scenario.description or f"Delft3D model for {scenario.scenario_name}",
        "site": scenario.project_id,
        "dem_dataset_id": scenario.dem_dataset_id or "dem.tif",
        "crs": scenario.crs,
        "breach_width_m": float(scenario.breach_width_m),
        "breach_formation_time_hr": float(scenario.breach_formation_duration_s / 3600.0),
        "assumed_reservoir_level_m": float(scenario.initial_water_level_m or 660.0),
        "manning_roughness": float(scenario.manning_roughness),
        "mesh_resolution_m": float(scenario.target_mesh_resolution_m),
        "simulation_duration_hr": float(scenario.simulation_duration_s / 3600.0),
        "timestep_sec": float(p.get("timestep_sec", 1.0)),
        "sph_coupled_run_id": p.get("sph_coupled_run_id", None),
        "provenance": {
            "source_scenario_id": scenario.scenario_id,
            "scenario_type": scenario.scenario_type.value,
            "engine": SimulationEngine.DELFT3D.value,
            "translated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def scenario_to_anuga(scenario: CanonicalScenario) -> DamProjectAnugaRunRequest:
    """
    Translate a canonical Scenario into DamProjectAnugaRunRequest.
    Compatible with onboarding_service.create_dam_project_anuga_run.
    """
    scen_type_literal: Optional[str] = "DAM_BREAK"
    if scenario.scenario_type == ScenarioType.RIVER_BLOCKAGE or scenario.scenario_type == ScenarioType.LANDSLIDE_DAM_FAILURE:
        scen_type_literal = "RIVER_BLOCKAGE"

    return DamProjectAnugaRunRequest(
        acknowledge_hypothetical_unverified=True,
        scenario_type=scen_type_literal,  # type: ignore
        is_intact_control=scenario.is_intact_control,
        opening_width=float(scenario.breach_width_m),
        simulation_duration_s=float(scenario.simulation_duration_s),
        output_interval_s=float(scenario.output_interval_s),
        target_mesh_resolution_m=float(scenario.target_mesh_resolution_m),
        custom_notes=f"Canonical scenario: {scenario.scenario_name} (Type: {scenario.scenario_type.value})",
    )


def scenario_to_river_blockage(scenario: CanonicalScenario) -> Dict[str, Any]:
    """
    Translate a canonical Scenario into River Blockage dual simulation parameters.
    Compatible with river_blockage_service.execute_river_blockage_analysis.
    """
    return {
        "project_id": scenario.project_id,
        "opening_width_m": float(scenario.breach_width_m),
        "blockage_crest_elevation_m": float(scenario.dam_crest_elevation_m or 670.0),
        "upstream_water_level_m": float(scenario.initial_water_level_m or 665.0),
        "simulation_duration_s": float(scenario.simulation_duration_s),
        "output_interval_s": float(scenario.output_interval_s),
        "provenance": {
            "source_scenario_id": scenario.scenario_id,
            "scenario_type": scenario.scenario_type.value,
            "engine": "RIVER_BLOCKAGE_DUAL_ANUGA",
            "translated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def translate_scenario_to_engine(
    scenario: CanonicalScenario,
    target_engine: Optional[SimulationEngine] = None,
) -> EngineTranslationResult:
    """
    High-level dispatch function translating a canonical scenario to a specific target engine.
    """
    engine = target_engine or scenario.selected_engine
    val_msgs: List[str] = []

    # Basic physical validation
    if scenario.simulation_duration_s <= 0:
        val_msgs.append("Simulation duration must be positive.")
    if scenario.output_interval_s <= 0:
        val_msgs.append("Output interval must be positive.")
    if scenario.output_interval_s > scenario.simulation_duration_s:
        val_msgs.append("Output interval cannot exceed total simulation duration.")
    if scenario.manning_roughness <= 0.001 or scenario.manning_roughness > 0.5:
        val_msgs.append(f"Manning roughness {scenario.manning_roughness} is outside typical range [0.005, 0.2].")

    translated: Dict[str, Any] = {}
    if engine == SimulationEngine.PYSPH:
        translated = scenario_to_pysph(scenario)
    elif engine == SimulationEngine.DELFT3D or engine == SimulationEngine.COUPLED_SPH_DELFT3D:
        translated = scenario_to_delft3d(scenario)
    elif engine == SimulationEngine.ANUGA:
        if scenario.scenario_type in (ScenarioType.RIVER_BLOCKAGE, ScenarioType.LANDSLIDE_DAM_FAILURE):
            translated = scenario_to_river_blockage(scenario)
        else:
            translated = scenario_to_anuga(scenario).dict()
    else:
        val_msgs.append(f"Unsupported simulation engine: {engine}")

    provenance = {
        "scenario_id": scenario.scenario_id,
        "project_id": scenario.project_id,
        "scenario_name": scenario.scenario_name,
        "scenario_type": scenario.scenario_type.value,
        "target_engine": engine.value,
        "translated_at": datetime.now(timezone.utc).isoformat(),
    }

    return EngineTranslationResult(
        scenario_id=scenario.scenario_id,
        target_engine=engine,
        translated_config=translated,
        provenance=provenance,
        is_valid=len(val_msgs) == 0,
        validation_messages=val_msgs,
    )


# ==============================================================================
# Backward Compatibility Bridges
# ==============================================================================

def legacy_scenario_to_canonical(
    legacy: Union[ScenarioResponse, ScenarioCreateRequest, Dict[str, Any]],
    project_id: str = "default_project",
) -> CanonicalScenario:
    """
    Convert a legacy ScenarioResponse, ScenarioCreateRequest, or raw dict into a CanonicalScenario.
    """
    if isinstance(legacy, BaseModel):
        d = legacy.dict()
    else:
        d = dict(legacy)

    scenario_id = str(d.get("id") or d.get("scenario_id") or uuid.uuid4())
    duration_hr = float(d.get("simulation_duration_hr", 24.0))
    duration_s = duration_hr * 3600.0
    formation_hr = float(d.get("breach_formation_time_hr", 1.0))
    formation_s = formation_hr * 3600.0

    return CanonicalScenario(
        scenario_id=scenario_id,
        project_id=str(d.get("project_id") or d.get("site") or project_id),
        scenario_name=str(d.get("name") or "Legacy Converted Scenario"),
        scenario_type=ScenarioType.DAM_BREAK,
        description=d.get("description"),
        dem_dataset_id=d.get("dem_dataset_id"),
        crs=str(d.get("crs", "EPSG:4326")),
        dam_crest_elevation_m=None,
        dam_location_lon_lat=None,
        initial_water_level_m=d.get("assumed_reservoir_level_m"),
        reservoir_volume_m3=None,
        is_intact_control=False,
        breach_width_m=float(d.get("breach_width_m", 100.0)),
        breach_depth_m=None,
        breach_start_time_s=0.0,
        breach_formation_duration_s=formation_s,
        manning_roughness=float(d.get("manning_roughness", 0.035)),
        simulation_duration_s=duration_s,
        output_interval_s=float(d.get("timestep_sec", 60.0)),
        target_mesh_resolution_m=float(d.get("mesh_resolution_m", 50.0)),
        selected_engine=SimulationEngine.DELFT3D,
        engine_parameters={
            "timestep_sec": float(d.get("timestep_sec", 1.0)),
            "upstream_boundary_desc": d.get("upstream_boundary_desc"),
            "downstream_boundary_desc": d.get("downstream_boundary_desc"),
        },
        provenance={
            "converted_from_legacy": True,
            "converted_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def anuga_request_to_canonical(
    req: DamProjectAnugaRunRequest,
    project_id: str,
    scenario_name: str = "ANUGA Dam Project Run",
) -> CanonicalScenario:
    """
    Convert a DamProjectAnugaRunRequest into a CanonicalScenario.
    """
    scenario_id = str(uuid.uuid4())
    stype = ScenarioType.RIVER_BLOCKAGE if req.scenario_type == "RIVER_BLOCKAGE" else ScenarioType.DAM_BREAK

    return CanonicalScenario(
        scenario_id=scenario_id,
        project_id=project_id,
        scenario_name=scenario_name,
        scenario_type=stype,
        description=req.custom_notes or "ANUGA simulation run request",
        is_intact_control=bool(req.is_intact_control),
        breach_width_m=float(req.opening_width or 100.0),
        manning_roughness=0.035,
        simulation_duration_s=float(req.simulation_duration_s or 3600.0),
        output_interval_s=float(req.output_interval_s or 60.0),
        target_mesh_resolution_m=float(req.target_mesh_resolution_m or 50.0),
        selected_engine=SimulationEngine.ANUGA,
        engine_parameters={},
        provenance={
            "converted_from_anuga_request": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
