"""R6-v5: company_source_id_sn_v1 + database_altitude_msl_v1 USER_ASSUMED mini-cases."""
from __future__ import annotations

from fusion_mvp.workbench.altitude_mapping import (
    ALTITUDE_BASIS,
    ALTITUDE_DATUM_STATUS,
    COMPANY_SN_MAPPING_VERSION,
    MAPPING_VERSION,
    SN_MAPPING_VERSION,
    apply_company_source_id_sn_v1,
    apply_database_altitude_msl_v1,
    resolve_aircraft_id,
)
from fusion_mvp.workbench.importer import MappingTemplate, row_to_observation


def _base_row(**kw):
    row = {
        "id": "SN-A",
        "source": "rid",
        "detector": "D-rid",
        "created_at": "2026-06-24T18:42:01+08:00",
        "longitude": 118.35,
        "latitude": 35.14,
        "altitude": 80,
        "height": 1,
        "source_data": {},
    }
    row.update(kw)
    return row


def _company_tmpl(**kw) -> MappingTemplate:
    base = dict(
        source_timezone="Asia/Shanghai",
        sn_mapping_version=COMPANY_SN_MAPPING_VERSION,
        altitude_mapping_version=MAPPING_VERSION,
        field_map={
            "source": "source",
            "sourceTrackId": "id",
            "measurementTime": "created_at",
            "detectorId": "detector",
            "longitude": "longitude",
            "latitude": "latitude",
            "altitude": "altitude",
        },
    )
    base.update(kw)
    return MappingTemplate(**base)


def test_company_rid_id_is_sn():
    obs, err = row_to_observation(_base_row(source="rid", id="SN-A"), _company_tmpl(), 1)
    assert err is None and obs is not None
    assert obs["sourceTrackId"] == "SN-A"
    assert obs["aircraftId"] == "SN-A"
    assert obs["rawRef"]["snMappingVersion"] == COMPANY_SN_MAPPING_VERSION


def test_company_spectrum_pp_id_is_sn():
    obs, err = row_to_observation(_base_row(source="pp", id="SN-A"), _company_tmpl(), 2)
    assert err is None and obs is not None
    assert obs["source"] == "spectrum"
    assert obs["sourceTrackId"] == "SN-A"
    assert obs["aircraftId"] == "SN-A"


def test_company_radar_id_not_sn():
    obs, err = row_to_observation(_base_row(source="leida", id="R7"), _company_tmpl(), 3)
    assert err is None and obs is not None
    assert obs["source"] == "radar"
    assert obs["sourceTrackId"] == "R7"
    assert obs["aircraftId"] is None


def test_leading_zeros_preserved_as_string():
    aid, flags, _ = apply_company_source_id_sn_v1(
        source="rid", source_track_id="00123", source_data={}
    )
    assert aid == "00123"
    assert isinstance(aid, str)


def test_identity_conflict_keeps_business_id():
    sd = {"identification1": {"idType": "Serial_Number", "uasIdAsString": "OTHER-SN"}}
    aid, flags, extra = resolve_aircraft_id(
        source="rid",
        source_track_id="SN-A",
        source_data=sd,
        sn_mapping_version=COMPANY_SN_MAPPING_VERSION,
    )
    assert aid == "SN-A"
    assert any("identity_conflict" in f for f in flags)
    assert extra.get("identityConflict", {}).get("kept") == "business_id"
    assert extra["identityConflict"]["sourceDataSn"] == "OTHER-SN"


def test_confirmed_sn_v1_still_extracts_from_source_data():
    sd = {"identification1": {"idType": "Serial_Number", "uasIdAsString": "FROM-SD"}}
    aid, flags, extra = resolve_aircraft_id(
        source="rid",
        source_track_id="DB-ID",
        source_data=sd,
        sn_mapping_version=SN_MAPPING_VERSION,
    )
    assert aid == "FROM-SD"
    assert extra["snMappingVersion"] == SN_MAPPING_VERSION
    assert any("aircraftId_from_confirmed_sn" in f for f in flags)


def test_altitude_msl_user_assumed_flags_and_height_evidence():
    obs = {
        "source": "rid",
        "altitude": 80.0,
        "altitudeDatum": "unknown",
        "qualityFlags": [],
        "rawRef": {},
    }
    out = apply_database_altitude_msl_v1(
        obs, enabled=True, source_row={"altitude": 80, "height": 12, "source_data": "{}"}
    )
    assert out["altitude"] == 80.0
    assert out["altitudeDatum"] == "MSL"
    assert out["altitudeMappingVersion"] == MAPPING_VERSION
    assert out["altitudeBasis"] == ALTITUDE_BASIS
    assert ALTITUDE_BASIS in out["qualityFlags"]
    assert ALTITUDE_DATUM_STATUS in out["qualityFlags"]
    assert out["rawRef"]["verticalFieldEvidence"]["dbHeight"] == 12
    # height must not replace altitude
    assert out["altitude"] != 12


def test_missing_altitude_stays_null_not_zero():
    out = apply_database_altitude_msl_v1(
        {"source": "radar", "altitude": None, "altitudeDatum": "unknown", "qualityFlags": [], "rawRef": {}},
        enabled=True,
        source_row={"altitude": ""},
    )
    assert out["altitude"] is None
    assert "altitude_missing" in out["qualityFlags"]


def test_rid_minus_1000_sentinel_null():
    out = apply_database_altitude_msl_v1(
        {
            "source": "rid",
            "altitude": -1000.0,
            "altitudeDatum": "unknown",
            "qualityFlags": [],
            "rawRef": {},
        },
        enabled=True,
        source_row={"altitude": -1000},
    )
    assert out["altitude"] is None
    assert any("sentinel" in f for f in out["qualityFlags"])


def test_importer_company_altitude_and_sn_together():
    obs, err = row_to_observation(
        _base_row(id="SN-A", altitude=50, height=9),
        _company_tmpl(),
        10,
    )
    assert err is None and obs is not None
    assert obs["aircraftId"] == "SN-A"
    assert obs["altitude"] == 50.0
    assert obs["altitudeDatum"] == "MSL"
    assert obs.get("altitudeBasis") == ALTITUDE_BASIS
    assert ALTITUDE_DATUM_STATUS in (obs.get("qualityFlags") or [])
