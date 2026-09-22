"""
Phase A2 Unified Canonical Scenario Test Suite.

Verifies:
1. Canonical scenario creation, persistence, retrieval, updating, and listing.
2. Parameter validation (duration > 0, interval > 0, roughness bounds, UUID checks).
3. Scenario -> PySPH translation adapter.
4. Scenario -> Delft3D FM translation adapter.
5. Scenario -> ANUGA SWE translation adapter.
6. Dam-break scenario representation & dispatch.
7. River-blockage / landslide dam scenario representation & dispatch.
8. Backward compatibility bridges (legacy Scenario -> canonical, ANUGA request -> canonical).
9. FastAPI REST API endpoints for canonical scenarios.
10. Preservation of SPH -> Delft3D hydrograph coupling workflow.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import (
    ScenarioType,
    SimulationEngine,
    CanonicalScenario,
    CanonicalScenarioCreateRequest,
    CanonicalScenarioUpdateRequest,
    DamProjectAnugaRunRequest,
    ScenarioCreateRequest,
)
from app.unified_scenario_service import (
    create_canonical_scenario,
    get_canonical_scenario,
    list_canonical_scenarios,
    update_canonical_scenario,
    scenario_to_pysph,
    scenario_to_delft3d,
    scenario_to_anuga,
    scenario_to_river_blockage,
    translate_scenario_to_engine,
    legacy_scenario_to_canonical,
    anuga_request_to_canonical,
)

client = TestClient(app)


def test_01_canonical_scenario_creation_and_retrieval():
    """Test creating a valid canonical scenario and retrieving it by ID."""
    req = CanonicalScenarioCreateRequest(
        project_id="hidkal-demo-001",
        scenario_name="Hidkal PMF Breach Scenario",
        scenario_type=ScenarioType.DAM_BREAK,
        description="Hypothetical full breach during Probable Maximum Flood",
        dem_dataset_id="dem.tif",
        crs="EPSG:4326",
        dam_crest_elevation_m=660.0,
        dam_location_lon_lat=(74.6469, 16.1558),
        initial_water_level_m=655.0,
        reservoir_volume_m3=1450000000.0,
        is_intact_control=False,
        breach_width_m=120.0,
        breach_depth_m=35.0,
        breach_start_time_s=0.0,
        breach_formation_duration_s=1800.0,
        manning_roughness=0.032,
        simulation_duration_s=7200.0,
        output_interval_s=60.0,
        target_mesh_resolution_m=40.0,
        selected_engine=SimulationEngine.ANUGA,
        engine_parameters={"cfl": 0.85},
    )

    resp = create_canonical_scenario(req)
    assert resp.scenario.scenario_id is not None
    assert resp.scenario.scenario_name == "Hidkal PMF Breach Scenario"
    assert resp.scenario.scenario_type == ScenarioType.DAM_BREAK
    assert resp.scenario.breach_width_m == 120.0
    assert resp.scenario.simulation_duration_s == 7200.0
    assert resp.scenario.provenance["creator"] == "unified_scenario_service"

    # Retrieve by ID
    retrieved = get_canonical_scenario(resp.scenario.scenario_id)
    assert retrieved.scenario.scenario_id == resp.scenario.scenario_id
    assert retrieved.scenario.scenario_name == "Hidkal PMF Breach Scenario"


def test_02_invalid_scenario_rejection():
    """Test that physical inconsistencies or invalid values are rejected during validation."""
    # 1. Invalid roughness (< 0.001)
    with pytest.raises(ValidationError):
        CanonicalScenarioCreateRequest(
            project_id="test-p",
            scenario_name="Invalid Roughness",
            manning_roughness=0.0001,
        )

    # 2. Non-positive duration
    with pytest.raises(ValidationError):
        CanonicalScenarioCreateRequest(
            project_id="test-p",
            scenario_name="Zero Duration",
            simulation_duration_s=0.0,
        )

    # 3. Output interval exceeding total duration
    scenario = CanonicalScenario(
        scenario_id=str(uuid.uuid4()),
        project_id="test-p",
        scenario_name="Bad Interval",
        simulation_duration_s=100.0,
        output_interval_s=200.0,
        breach_width_m=50.0,
        manning_roughness=0.035,
        target_mesh_resolution_m=20.0,
    )
    result = translate_scenario_to_engine(scenario, SimulationEngine.ANUGA)
    assert result.is_valid is False
    assert any("cannot exceed" in msg for msg in result.validation_messages)


def test_03_scenario_to_pysph_translation():
    """Test translating a canonical Scenario into PySPH configuration."""
    scenario = CanonicalScenario(
        scenario_id=str(uuid.uuid4()),
        project_id="pysph-project-001",
        scenario_name="Near Field Wave",
        scenario_type=ScenarioType.DAM_BREAK,
        breach_width_m=80.0,
        breach_start_time_s=1.5,
        manning_roughness=0.030,
        simulation_duration_s=3600.0,
        output_interval_s=60.0,
        target_mesh_resolution_m=10.0,
        selected_engine=SimulationEngine.PYSPH,
        engine_parameters={
            "particle_spacing_m": 20.0,
            "duration_s": 24.0,
            "timestep_s": 0.04,
            "arrival_threshold_m": 0.08,
        },
    )

    sph_cfg = scenario_to_pysph(scenario)
    assert sph_cfg["scenario_id"] == scenario.scenario_id
    assert sph_cfg["breach_width_m"] == 80.0
    assert sph_cfg["breach_start_time_s"] == 1.5
    assert sph_cfg["particle_spacing_m"] == 20.0
    assert sph_cfg["duration_s"] == 24.0
    assert sph_cfg["timestep_s"] == 0.04
    assert sph_cfg["breach_mode"] == "instantaneous"
    assert sph_cfg["provenance"]["engine"] == "PYSPH"


def test_04_scenario_to_delft3d_translation():
    """Test translating a canonical Scenario into Delft3D FM configuration."""
    scenario = CanonicalScenario(
        scenario_id=str(uuid.uuid4()),
        project_id="delft3d-project-001",
        scenario_name="Regional D-Flow FM Run",
        scenario_type=ScenarioType.DAM_BREAK,
        initial_water_level_m=658.5,
        breach_width_m=150.0,
        breach_formation_duration_s=7200.0,
        manning_roughness=0.028,
        simulation_duration_s=86400.0,  # 24 hours
        output_interval_s=300.0,
        target_mesh_resolution_m=50.0,
        selected_engine=SimulationEngine.DELFT3D,
        engine_parameters={"timestep_sec": 2.0, "sph_coupled_run_id": "mock-sph-run-123"},
    )

    d3d_cfg = scenario_to_delft3d(scenario)
    assert d3d_cfg["scenario_id"] == scenario.scenario_id
    assert d3d_cfg["simulation_duration_hr"] == 24.0
    assert d3d_cfg["breach_formation_time_hr"] == 2.0
    assert d3d_cfg["assumed_reservoir_level_m"] == 658.5
    assert d3d_cfg["mesh_resolution_m"] == 50.0
    assert d3d_cfg["sph_coupled_run_id"] == "mock-sph-run-123"
    assert d3d_cfg["provenance"]["engine"] == "DELFT3D"


def test_05_scenario_to_anuga_translation():
    """Test translating a canonical Scenario into DamProjectAnugaRunRequest."""
    scenario = CanonicalScenario(
        scenario_id=str(uuid.uuid4()),
        project_id="anuga-project-001",
        scenario_name="ANUGA SWE 2D Simulation",
        scenario_type=ScenarioType.DAM_BREAK,
        is_intact_control=False,
        breach_width_m=100.0,
        simulation_duration_s=3600.0,
        output_interval_s=60.0,
        target_mesh_resolution_m=75.0,
        selected_engine=SimulationEngine.ANUGA,
    )

    anuga_req = scenario_to_anuga(scenario)
    assert isinstance(anuga_req, DamProjectAnugaRunRequest)
    assert anuga_req.acknowledge_hypothetical_unverified is True
    assert anuga_req.scenario_type == "DAM_BREAK"
    assert anuga_req.is_intact_control is False
    assert anuga_req.opening_width == 100.0
    assert anuga_req.simulation_duration_s == 3600.0
    assert anuga_req.output_interval_s == 60.0
    assert anuga_req.target_mesh_resolution_m == 75.0


def test_06_river_blockage_scenario_representation():
    """Test canonical scenario representation for natural landslide dam / river blockage."""
    req = CanonicalScenarioCreateRequest(
        project_id="valley-project-002",
        scenario_name="Landslide Dam Valley Blockage",
        scenario_type=ScenarioType.RIVER_BLOCKAGE,
        dam_crest_elevation_m=675.0,
        initial_water_level_m=668.0,
        breach_width_m=45.0,
        simulation_duration_s=1800.0,
        output_interval_s=30.0,
        target_mesh_resolution_m=25.0,
        selected_engine=SimulationEngine.ANUGA,
    )

    resp = create_canonical_scenario(req)
    assert resp.scenario.scenario_type == ScenarioType.RIVER_BLOCKAGE

    # Translate to river blockage
    rb_cfg = scenario_to_river_blockage(resp.scenario)
    assert rb_cfg["project_id"] == "valley-project-002"
    assert rb_cfg["opening_width_m"] == 45.0
    assert rb_cfg["blockage_crest_elevation_m"] == 675.0
    assert rb_cfg["upstream_water_level_m"] == 668.0
    assert rb_cfg["simulation_duration_s"] == 1800.0

    # Translate via high-level dispatcher
    disp_res = translate_scenario_to_engine(resp.scenario, SimulationEngine.ANUGA)
    assert disp_res.is_valid is True
    assert disp_res.translated_config["opening_width_m"] == 45.0


def test_07_backward_compatibility_bridges():
    """Test converting legacy ScenarioCreateRequest and ANUGA requests into canonical scenarios."""
    # 1. Legacy ScenarioCreateRequest
    legacy_req = ScenarioCreateRequest(
        name="Legacy Format Scenario",
        site="LegacySite",
        breach_width_m=90.0,
        breach_formation_time_hr=1.5,
        assumed_reservoir_level_m=650.0,
        manning_roughness=0.035,
        mesh_resolution_m=40.0,
        simulation_duration_hr=12.0,
        timestep_sec=2.0,
    )
    canon_from_legacy = legacy_scenario_to_canonical(legacy_req, project_id="legacy-proj")
    assert canon_from_legacy.scenario_name == "Legacy Format Scenario"
    assert canon_from_legacy.breach_width_m == 90.0
    assert canon_from_legacy.simulation_duration_s == 12.0 * 3600.0
    assert canon_from_legacy.breach_formation_duration_s == 1.5 * 3600.0
    assert canon_from_legacy.provenance["converted_from_legacy"] is True

    # 2. DamProjectAnugaRunRequest
    anuga_run_req = DamProjectAnugaRunRequest(
        scenario_type="RIVER_BLOCKAGE",
        opening_width=60.0,
        simulation_duration_s=2400.0,
        output_interval_s=60.0,
        target_mesh_resolution_m=50.0,
    )
    canon_from_anuga = anuga_request_to_canonical(anuga_run_req, project_id="anuga-proj")
    assert canon_from_anuga.scenario_type == ScenarioType.RIVER_BLOCKAGE
    assert canon_from_anuga.breach_width_m == 60.0
    assert canon_from_anuga.simulation_duration_s == 2400.0
    assert canon_from_anuga.provenance["converted_from_anuga_request"] is True


def test_08_canonical_scenario_rest_api_endpoints():
    """Test canonical scenario HTTP REST API endpoints."""
    # POST /api/canonical-scenarios
    payload = {
        "project_id": "api-demo-proj",
        "scenario_name": "API Test Scenario",
        "scenario_type": "DAM_BREAK",
        "breach_width_m": 110.0,
        "manning_roughness": 0.033,
        "simulation_duration_s": 3600.0,
        "output_interval_s": 60.0,
        "target_mesh_resolution_m": 50.0,
        "selected_engine": "ANUGA",
    }
    create_res = client.post("/api/canonical-scenarios", json=payload)
    assert create_res.status_code == 200
    data = create_res.json()
    scenario_id = data["scenario"]["scenario_id"]
    assert data["scenario"]["scenario_name"] == "API Test Scenario"
    assert "ANUGA" in data["supported_engines"]

    # GET /api/canonical-scenarios/{scenario_id}
    get_res = client.get(f"/api/canonical-scenarios/{scenario_id}")
    assert get_res.status_code == 200
    assert get_res.json()["scenario"]["scenario_id"] == scenario_id

    # PUT /api/canonical-scenarios/{scenario_id}
    update_res = client.put(
        f"/api/canonical-scenarios/{scenario_id}",
        json={"scenario_name": "API Updated Scenario", "breach_width_m": 130.0},
    )
    assert update_res.status_code == 200
    assert update_res.json()["scenario"]["scenario_name"] == "API Updated Scenario"
    assert update_res.json()["scenario"]["breach_width_m"] == 130.0

    # POST /api/canonical-scenarios/{scenario_id}/translate/PYSPH
    trans_sph = client.post(f"/api/canonical-scenarios/{scenario_id}/translate/PYSPH")
    assert trans_sph.status_code == 200
    sph_data = trans_sph.json()
    assert sph_data["target_engine"] == "PYSPH"
    assert sph_data["is_valid"] is True
    assert sph_data["translated_config"]["breach_width_m"] == 130.0

    # POST /api/canonical-scenarios/{scenario_id}/translate/DELFT3D
    trans_d3d = client.post(f"/api/canonical-scenarios/{scenario_id}/translate/DELFT3D")
    assert trans_d3d.status_code == 200
    d3d_data = trans_d3d.json()
    assert d3d_data["target_engine"] == "DELFT3D"
    assert d3d_data["is_valid"] is True
    assert d3d_data["translated_config"]["breach_width_m"] == 130.0

    # GET /api/dam-projects/{project_id}/canonical-scenarios
    proj_scens = client.get("/api/dam-projects/api-demo-proj/canonical-scenarios")
    assert proj_scens.status_code == 200
    assert len(proj_scens.json()) >= 1
