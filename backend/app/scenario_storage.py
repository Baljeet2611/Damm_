import os
import json
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException

from app.schemas import (
    ScenarioAssumption,
    ScenarioCreateRequest,
    ScenarioUpdateRequest,
    ScenarioResponse,
)
from app.raster_service import get_project_root, resolve_dataset_file, DEFAULT_REGISTERED_DATASETS


def get_runtime_dir() -> Path:
    """Get the active runtime storage directory, creating subdirectories if needed."""
    env_runtime = os.environ.get("SIH_RUNTIME_DIR")
    if env_runtime:
        base_path = Path(env_runtime).resolve()
    else:
        base_path = Path(get_project_root()).resolve() / "runtime"

    for sub in ["scenarios", "packages", "runs"]:
        (base_path / sub).mkdir(parents=True, exist_ok=True)

    return base_path


def get_scenarios_dir() -> Path:
    """Get directory for persistent scenario JSON storage."""
    return get_runtime_dir() / "scenarios"


def validate_uuid_str(val: str) -> str:
    """Validate that the provided string is a valid UUID v4; rejects path traversal attempts."""
    try:
        parsed = uuid.UUID(str(val).strip(), version=4)
        return str(parsed)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scenario ID format '{val}'. Must be a valid UUID v4 identifier.",
        )


def compute_file_sha256(file_path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a local file safely in chunks."""
    if not file_path.is_file():
        return None
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_scenario_snapshot_checksum(scenario_data: Dict[str, Any]) -> str:
    """
    Compute deterministic SHA-256 checksum over scenario configuration and referenced DEM file.
    """
    hasher = hashlib.sha256()

    # Canonical scenario properties (excluding mutable timestamps)
    canonical_keys = [
        "name", "description", "site", "dem_dataset_id", "crs",
        "breach_width_m", "breach_formation_time_hr", "assumed_reservoir_level_m",
        "upstream_boundary_desc", "downstream_boundary_desc", "manning_roughness",
        "mesh_resolution_m", "simulation_duration_hr", "timestep_sec"
    ]
    canonical_dict = {k: scenario_data.get(k) for k in canonical_keys}
    hasher.update(json.dumps(canonical_dict, sort_keys=True).encode("utf-8"))

    # Include referenced DEM dataset checksum if available
    dem_id = scenario_data.get("dem_dataset_id", "dem")
    if dem_id in DEFAULT_REGISTERED_DATASETS:
        _, dem_path = resolve_dataset_file(dem_id)
        if dem_path and dem_path.is_file():
            dem_hash = compute_file_sha256(dem_path)
            if dem_hash:
                hasher.update(f"dem_sha256:{dem_hash}".encode("utf-8"))

    return hasher.hexdigest()


def get_default_assumptions(req: ScenarioCreateRequest) -> List[ScenarioAssumption]:
    """Generate explicit assumption metadata with verification statuses and unit tags."""
    return [
        ScenarioAssumption(
            parameter="breach_width_m",
            value=req.breach_width_m,
            unit="meters",
            status="unverified_illustrative",
            note="Illustrative trapezoidal breach dimension without geotechnical structural analysis.",
        ),
        ScenarioAssumption(
            parameter="breach_formation_time_hr",
            value=req.breach_formation_time_hr,
            unit="hours",
            status="unverified_illustrative",
            note="Assumed linear/parabolic erosion time without soil erodibility calibration.",
        ),
        ScenarioAssumption(
            parameter="assumed_reservoir_level_m",
            value=req.assumed_reservoir_level_m,
            unit="meters",
            status="unverified_datum",
            note="Assumed reservoir level; absolute vertical datum (MSL vs local) unverified in sample DEM.",
        ),
        ScenarioAssumption(
            parameter="manning_roughness",
            value=req.manning_roughness,
            unit="s/m^(1/3)",
            status="unverified_illustrative",
            note="Uniform spatial friction; uncalibrated against riverbed or floodplain land cover.",
        ),
        ScenarioAssumption(
            parameter="upstream_boundary",
            value=req.upstream_boundary_desc,
            unit="text_descriptor",
            status="unverified_illustrative",
            note="Inflow boundary condition requires verified inflow hydrograph or reservoir stage-storage curve.",
        ),
        ScenarioAssumption(
            parameter="downstream_boundary",
            value=req.downstream_boundary_desc,
            unit="text_descriptor",
            status="unverified_illustrative",
            note="Downstream boundary requires hydraulic water-level gauge or rating curve data.",
        ),
    ]


def evaluate_scenario_validation(scenario_dict: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Separates schema-valid from scientifically verified.
    Evaluates scenario inputs and generates transparent scientific validation notes.
    """
    notes: List[str] = []

    dem_id = scenario_dict.get("dem_dataset_id", "dem")
    if dem_id == "dem":
        notes.append("Referenced DEM ('hidkal_dem.tif') has unverified vertical datum and unknown sample provenance.")
    else:
        notes.append(f"Referenced DEM dataset '{dem_id}' requires vertical datum verification.")

    notes.append("Dam breach parameters are illustrative; structural geotechnical failure modeling is required.")
    notes.append("Bed roughness Manning's n is assumed spatially uniform and uncalibrated.")
    notes.append("Boundary conditions are descriptive placeholders lacking calibrated time-series hydrographs.")

    # Scientific status remains 'input_review_required' until formal calibration
    status = "input_review_required"
    return status, notes


def atomic_save_scenario(scenario_dict: Dict[str, Any]) -> None:
    """Save scenario dictionary to disk using atomic rename to prevent partial writes."""
    scenarios_dir = get_scenarios_dir()
    scenario_id = scenario_dict["id"]
    final_path = scenarios_dir / f"{scenario_id}.json"
    temp_path = scenarios_dir / f"{scenario_id}.tmp_{uuid.uuid4().hex}"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(scenario_dict, f, indent=2, ensure_ascii=False)

    # Atomic replace
    os.replace(temp_path, final_path)


def load_scenario_dict(scenario_id: str) -> Dict[str, Any]:
    """Load scenario dictionary from disk by UUID, raising 404 if not found."""
    valid_id = validate_uuid_str(scenario_id)
    scenario_path = get_scenarios_dir() / f"{valid_id}.json"
    if not scenario_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{valid_id}' not found in runtime storage.",
        )
    try:
        with open(scenario_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read scenario file '{valid_id}': {str(e)}",
        )


def scenario_dict_to_response(data: Dict[str, Any]) -> ScenarioResponse:
    """Convert raw scenario dict to validated ScenarioResponse."""
    assumptions = [
        ScenarioAssumption(**a) if isinstance(a, dict) else a
        for a in data.get("assumptions", [])
    ]
    checksum = compute_scenario_snapshot_checksum(data)

    return ScenarioResponse(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        site=data.get("site", "Hidkal Dam, Belagavi, Karnataka"),
        dem_dataset_id=data.get("dem_dataset_id", "dem"),
        crs=data.get("crs", "EPSG:4326"),
        breach_width_m=float(data.get("breach_width_m", 100.0)),
        breach_formation_time_hr=float(data.get("breach_formation_time_hr", 2.0)),
        assumed_reservoir_level_m=float(data.get("assumed_reservoir_level_m", 660.0)),
        upstream_boundary_desc=data.get("upstream_boundary_desc", ""),
        downstream_boundary_desc=data.get("downstream_boundary_desc", ""),
        manning_roughness=float(data.get("manning_roughness", 0.035)),
        mesh_resolution_m=float(data.get("mesh_resolution_m", 50.0)),
        simulation_duration_hr=float(data.get("simulation_duration_hr", 24.0)),
        timestep_sec=float(data.get("timestep_sec", 1.0)),
        assumptions=assumptions,
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        revision=int(data.get("revision", 1)),
        archived=bool(data.get("archived", False)),
        status=data.get("status", "input_review_required"),
        validation_notes=data.get("validation_notes", []),
        snapshot_checksum=checksum,
    )


def list_scenarios(include_archived: bool = False) -> List[ScenarioResponse]:
    """List all stored scenarios, optionally filtering out archived ones."""
    scenarios_dir = get_scenarios_dir()
    results: List[ScenarioResponse] = []

    for file_path in scenarios_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not include_archived and data.get("archived", False):
                continue
            results.append(scenario_dict_to_response(data))
        except Exception:
            continue

    # Sort newest first
    results.sort(key=lambda s: s.updated_at, reverse=True)
    return results


def get_scenario(scenario_id: str) -> ScenarioResponse:
    """Retrieve a single scenario by UUID."""
    data = load_scenario_dict(scenario_id)
    return scenario_dict_to_response(data)


def create_scenario(req: ScenarioCreateRequest) -> ScenarioResponse:
    """Create a new scenario with generated UUID v4, initial revision 1, and default assumptions."""
    now_iso = datetime.now(timezone.utc).isoformat()
    scenario_id = str(uuid.uuid4())

    assumptions = req.assumptions or get_default_assumptions(req)
    assumptions_dicts = [a.model_dump() for a in assumptions]

    scenario_dict: Dict[str, Any] = {
        "id": scenario_id,
        "name": req.name.strip(),
        "description": req.description or "",
        "site": req.site,
        "dem_dataset_id": req.dem_dataset_id,
        "crs": req.crs,
        "breach_width_m": req.breach_width_m,
        "breach_formation_time_hr": req.breach_formation_time_hr,
        "assumed_reservoir_level_m": req.assumed_reservoir_level_m,
        "upstream_boundary_desc": req.upstream_boundary_desc,
        "downstream_boundary_desc": req.downstream_boundary_desc,
        "manning_roughness": req.manning_roughness,
        "mesh_resolution_m": req.mesh_resolution_m,
        "simulation_duration_hr": req.simulation_duration_hr,
        "timestep_sec": req.timestep_sec,
        "assumptions": assumptions_dicts,
        "created_at": now_iso,
        "updated_at": now_iso,
        "revision": 1,
        "archived": False,
    }

    status, notes = evaluate_scenario_validation(scenario_dict)
    scenario_dict["status"] = status
    scenario_dict["validation_notes"] = notes

    atomic_save_scenario(scenario_dict)
    return scenario_dict_to_response(scenario_dict)


def update_scenario(scenario_id: str, req: ScenarioUpdateRequest) -> ScenarioResponse:
    """Update an existing scenario, incrementing revision and updating timestamp."""
    data = load_scenario_dict(scenario_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    update_fields = req.model_dump(exclude_unset=True)
    for k, v in update_fields.items():
        if k == "assumptions" and v is not None:
            data["assumptions"] = [
                a.model_dump() if isinstance(a, ScenarioAssumption) else a for a in v
            ]
        elif v is not None:
            data[k] = v

    data["revision"] = int(data.get("revision", 1)) + 1
    data["updated_at"] = now_iso

    status, notes = evaluate_scenario_validation(data)
    data["status"] = status
    data["validation_notes"] = notes

    atomic_save_scenario(data)
    return scenario_dict_to_response(data)


def clone_scenario(scenario_id: str) -> ScenarioResponse:
    """Clone an existing scenario with a new UUID v4, revision 1, and 'Clone of' name prefix."""
    orig = load_scenario_dict(scenario_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_id = str(uuid.uuid4())

    cloned_dict = dict(orig)
    cloned_dict["id"] = new_id
    cloned_dict["name"] = f"Clone of {orig.get('name', 'Scenario')}"[:120]
    cloned_dict["revision"] = 1
    cloned_dict["archived"] = False
    cloned_dict["created_at"] = now_iso
    cloned_dict["updated_at"] = now_iso

    status, notes = evaluate_scenario_validation(cloned_dict)
    cloned_dict["status"] = status
    cloned_dict["validation_notes"] = notes

    atomic_save_scenario(cloned_dict)
    return scenario_dict_to_response(cloned_dict)


def archive_scenario(scenario_id: str, archive: bool = True) -> ScenarioResponse:
    """Set the archived status of a scenario without deleting file."""
    data = load_scenario_dict(scenario_id)
    data["archived"] = archive
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_save_scenario(data)
    return scenario_dict_to_response(data)
