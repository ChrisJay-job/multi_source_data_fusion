"""Versioned database altitude / SN mapping shared by importer and MQTT sender."""
from __future__ import annotations

import json
from typing import Any, Optional

MAPPING_VERSION = "database_altitude_msl_v1"
# Legacy: only trust SN extracted from source_data confirmed paths.
SN_MAPPING_VERSION = "confirmed_sn_v1"
# Company DB template: RID/spectrum business id is SN; radar id is local track only.
COMPANY_SN_MAPPING_VERSION = "company_source_id_sn_v1"
# Empty sn_mapping_version → confirmed_sn_v1 for old fixtures without the field.
CONFIRMED_FALLBACK = SN_MAPPING_VERSION

ALTITUDE_BASIS = "USER_ASSUMED"
ALTITUDE_DATUM_STATUS = "altitude_datum_not_verified"

# RID Remote ID protocol: altitudeGeodetic / DB altitude -1000 means unknown.
RID_ALTITUDE_UNKNOWN_SENTINEL = -1000.0

# User-confirmed: DB column `altitude` is MSL metres for this mapping version.
# This does NOT mean every external device file is already calibrated MSL.


def _as_source_data(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def extract_confirmed_sn(source: str, source_data: Any) -> tuple[Optional[str], list[str]]:
    """Return (sn_or_None, evidence_paths). Radar local ids are never SN."""
    evidence: list[str] = []
    if not isinstance(source_data, dict):
        return None, evidence
    src = (source or "").lower()
    if src == "rid":
        ident = (source_data.get("identification1") or {}) if isinstance(source_data.get("identification1"), dict) else {}
        id_type = ident.get("idType")
        uas = ident.get("uasIdAsString")
        evidence.append("source_data.identification1.idType")
        evidence.append("source_data.identification1.uasIdAsString")
        if id_type == "Serial_Number" and uas:
            return str(uas), evidence
        return None, evidence
    if src in {"spectrum", "pp"}:
        sn = source_data.get("serialNumber")
        evidence.append("source_data.serialNumber")
        if sn:
            return str(sn), evidence
        return None, evidence
    # radar: no SN
    evidence.append("radar_has_no_sn")
    return None, evidence


def apply_company_source_id_sn_v1(
    *,
    source: str,
    source_track_id: Any,
    source_data: Any = None,
    existing_aircraft_id: Any = None,
) -> tuple[Optional[str], list[str], dict[str, Any]]:
    """Company DB template: rid/spectrum id→aircraftId(SN); radar id local-only."""
    return resolve_aircraft_id(
        source=source,
        source_track_id=source_track_id,
        aircraft_id_field=existing_aircraft_id,
        source_data=source_data,
        sn_mapping_version=COMPANY_SN_MAPPING_VERSION,
        treat_raw_id_as_aircraftId=False,
    )


def resolve_aircraft_id(
    *,
    source: str,
    source_track_id: Any,
    aircraft_id_field: Any = None,
    source_data: Any = None,
    sn_mapping_version: str = COMPANY_SN_MAPPING_VERSION,
    treat_raw_id_as_aircraftId: bool = False,
) -> tuple[Optional[str], list[str], dict[str, Any]]:
    """Shared SN / identity mapping for importer and CSV MQTT sender.

    Returns (aircraft_id, quality_flags, raw_ref_extras).
    Preserves string ids (leading zeros). Never invents SN for empty id.
    Never fills radar local id as aircraftId.
    """
    flags: list[str] = []
    raw_ref: dict[str, Any] = {}
    src = (source or "").lower()
    stid = None if source_track_id in (None, "") else str(source_track_id)
    field_aid = None if aircraft_id_field in (None, "") else str(aircraft_id_field)
    sd = _as_source_data(source_data)
    version = (sn_mapping_version or "").strip() or CONFIRMED_FALLBACK
    raw_ref["snMappingVersion"] = version

    confirmed, evidence = extract_confirmed_sn(src, sd)
    raw_ref["snEvidencePaths"] = evidence

    if version == COMPANY_SN_MAPPING_VERSION:
        if src == "radar":
            # Local track id only; never treat as SN.
            if field_aid:
                flags.append("radar_aircraftId_field_ignored_not_sn")
                raw_ref["ignoredAircraftIdField"] = field_aid
            if confirmed:
                flags.append("radar_source_data_sn_ignored")
                raw_ref["sourceDataSn"] = confirmed
            flags.append(f"sn_mapping:{COMPANY_SN_MAPPING_VERSION}:radar_no_sn")
            return None, flags, raw_ref

        if src not in ("rid", "spectrum"):
            flags.append("aircraftId_unconfirmed")
            return field_aid, flags, raw_ref

        if stid is None:
            flags.append("aircraftId_missing_empty_id")
            flags.append(f"sn_mapping:{COMPANY_SN_MAPPING_VERSION}:missing_id")
            return None, flags, raw_ref

        # Business id is authoritative SN for company RID/spectrum.
        aircraft_id = stid
        flags.append(f"aircraftId_from_company_source_id:{COMPANY_SN_MAPPING_VERSION}")
        flags.append(f"sn_mapping:{COMPANY_SN_MAPPING_VERSION}:business_id")

        if confirmed is not None and str(confirmed) != stid:
            flags.append("identity_conflict_source_data_vs_business_id")
            flags.append(f"identity_diff:business={stid}:source_data={confirmed}")
            raw_ref["identityConflict"] = {
                "businessId": stid,
                "sourceDataSn": str(confirmed),
                "kept": "business_id",
            }
            for path in evidence:
                flags.append(f"sn_evidence:{path}")
        elif confirmed is not None and str(confirmed) == stid:
            for path in evidence:
                flags.append(f"sn_evidence:{path}")
            flags.append("source_data_sn_matches_business_id")

        if field_aid is not None and field_aid != stid:
            flags.append("identity_conflict_aircraftId_field_vs_business_id")
            raw_ref["aircraftIdField"] = field_aid
        return aircraft_id, flags, raw_ref

    # --- confirmed_sn_v1 (legacy) ---
    raw_ref["snMappingVersion"] = SN_MAPPING_VERSION
    aircraft_id = field_aid
    if aircraft_id in (None, ""):
        if confirmed:
            aircraft_id = confirmed
            flags.append(f"aircraftId_from_confirmed_sn:{SN_MAPPING_VERSION}")
            for path in evidence:
                flags.append(f"sn_evidence:{path}")
        elif src in ("rid", "spectrum"):
            flags.append("aircraftId_unconfirmed")
        elif src == "radar":
            flags.append(f"sn_mapping:{SN_MAPPING_VERSION}:radar_has_no_sn")
    if aircraft_id in (None, "") and treat_raw_id_as_aircraftId and src in ("rid", "spectrum") and stid:
        aircraft_id = stid
        flags.append("raw_id_as_aircraftId")
    sn_result = "confirmed" if (aircraft_id and confirmed and str(aircraft_id) == str(confirmed)) else (
        "radar_has_no_sn" if src == "radar" else ("raw_id" if "raw_id_as_aircraftId" in flags else "unconfirmed")
    )
    flags.append(f"sn_mapping:{SN_MAPPING_VERSION}:{sn_result}")
    return aircraft_id, flags, raw_ref


def _collect_height_evidence(source_row: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Preserve original altitude/height/source_data vertical paths; never use height as altitude."""
    if not source_row:
        return {}
    out: dict[str, Any] = {}
    if "altitude" in source_row and source_row.get("altitude") not in (None, ""):
        out["dbAltitude"] = source_row.get("altitude")
    if "height" in source_row and source_row.get("height") not in (None, ""):
        out["dbHeight"] = source_row.get("height")
    sd = _as_source_data(source_row.get("source_data"))
    if not sd:
        return out
    loc = sd.get("location") if isinstance(sd.get("location"), dict) else {}
    if loc:
        for key in ("altitudeGeodetic", "altitudePressure", "height", "heightType"):
            if loc.get(key) not in (None, ""):
                out[f"source_data.location.{key}"] = loc.get(key)
    for key in ("altitudeMsl", "heightAgl", "altitude", "height"):
        if sd.get(key) not in (None, ""):
            out[f"source_data.{key}"] = sd.get(key)
    return out


def apply_database_altitude_msl_v1(
    obs: dict[str, Any],
    *,
    enabled: bool,
    source_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Mutate a copy: when enabled and altitude present without a supported datum, set MSL.

    Company convention is USER_ASSUMED / altitude_datum_not_verified — not a physical conversion.
    Legacy / multisensor-v1 callers pass enabled=False so unknown stays unknown.
    """
    out = dict(obs)
    out.setdefault("qualityFlags", list(out.get("qualityFlags") or []))
    flags = list(out["qualityFlags"])
    raw_ref = dict(out.get("rawRef") or {})
    height_ev = _collect_height_evidence(source_row)
    if height_ev:
        raw_ref["verticalFieldEvidence"] = height_ev

    if not enabled:
        flags.append("altitude_mapping_not_applied")
        out["qualityFlags"] = flags
        out["rawRef"] = raw_ref
        return out

    alt = out.get("altitude")
    datum = out.get("altitudeDatum")
    raw_alt = None if source_row is None else source_row.get("altitude")
    if alt is None and raw_alt is not None and raw_alt != "":
        try:
            alt = float(raw_alt)
            if alt == alt and abs(alt) != float("inf"):  # finite
                out["altitude"] = alt
        except (TypeError, ValueError):
            alt = None
            flags.append("altitude_unparseable")

    # RID protocol unknown sentinel: do not feed -1000 into vertical KF as real MSL.
    source = str(out.get("source") or "").lower()
    try:
        alt_num = float(out["altitude"]) if out.get("altitude") is not None else None
    except (TypeError, ValueError):
        alt_num = None
    if source == "rid" and alt_num is not None and alt_num == RID_ALTITUDE_UNKNOWN_SENTINEL:
        raw_ref["ridAltitudeSentinel"] = RID_ALTITUDE_UNKNOWN_SENTINEL
        flags.append("rid_altitude_unknown_sentinel_-1000")
        out["altitude"] = None
        out["altitudeDatum"] = "unknown"
        flags.append("altitude_missing")
        flags.append(ALTITUDE_DATUM_STATUS)
        out["qualityFlags"] = flags
        out["altitudeMappingVersion"] = MAPPING_VERSION
        out["altitudeBasis"] = ALTITUDE_BASIS
        out["rawRef"] = raw_ref
        return out

    if out.get("altitude") is None:
        flags.append("altitude_missing")
        flags.append(ALTITUDE_DATUM_STATUS)
        out["qualityFlags"] = flags
        out["altitudeMappingVersion"] = MAPPING_VERSION
        out["altitudeBasis"] = ALTITUDE_BASIS
        out["rawRef"] = raw_ref
        return out

    # Preserve explicit unsupported/known foreign datums — do not relabel as MSL.
    if isinstance(datum, str) and datum.strip() and datum.strip().upper() not in {
        "MSL",
        "UNKNOWN",
        "",
    }:
        if datum.strip().upper() not in {"MSL", "MEAN_SEA_LEVEL"}:
            flags.append("altitude_datum_preserved_not_forced_msl")
            flags.append(ALTITUDE_DATUM_STATUS)
            out["qualityFlags"] = flags
            out["altitudeMappingVersion"] = MAPPING_VERSION
            out["altitudeBasis"] = ALTITUDE_BASIS
            out["rawAltitude"] = out.get("altitude")
            out["rawAltitudeDatum"] = datum
            out["rawRef"] = raw_ref
            return out
    if datum in (None, "", "unknown", "UNKNOWN") or (
        isinstance(datum, str) and datum.strip().upper() in {"MSL", "MEAN_SEA_LEVEL"}
    ):
        out["altitudeDatum"] = "MSL"
        flags.append("altitude_mapped_database_altitude_msl_v1")
        flags.append(ALTITUDE_BASIS)
        flags.append(ALTITUDE_DATUM_STATUS)
        out["rawAltitude"] = out.get("altitude")
        out["rawAltitudeDatum"] = datum or "unknown"
    out["qualityFlags"] = flags
    out["altitudeMappingVersion"] = MAPPING_VERSION
    out["altitudeBasis"] = ALTITUDE_BASIS
    raw_ref["altitudeMappingVersion"] = MAPPING_VERSION
    raw_ref["altitudeBasis"] = ALTITUDE_BASIS
    raw_ref["altitudeDatumStatus"] = ALTITUDE_DATUM_STATUS
    out["rawRef"] = raw_ref
    return out
