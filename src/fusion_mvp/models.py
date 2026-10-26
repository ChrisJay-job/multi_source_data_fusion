from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SourceKind = Literal["rid", "spectrum", "radar"]
Mode = Literal["realtime", "replay", "flush"]
TrackStatus = Literal["tentative", "tracked", "coasting", "lost", "terminated"]
PositionMode = Literal["measured_assisted", "predicted", "stale"]


class Observation(BaseModel):
    observationId: str
    source: SourceKind
    detectorId: str
    sourceTrackId: str
    aircraftId: Optional[str] = None
    measurementTime: str
    receivedAt: Optional[str] = None
    timeBasis: str = "created_at_assumed_measure"
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    altitude: Optional[float] = None
    altitudeDatum: Optional[str] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    verticalSpeed: Optional[float] = None
    qualityFlags: list[str] = Field(default_factory=list)
    rawRef: Optional[dict[str, Any]] = None


class Rejected(BaseModel):
    observationId: Optional[str] = None
    reason: str
    detail: Optional[str] = None
    rawRef: Optional[dict[str, Any]] = None


class SourceTrackRef(BaseModel):
    source: SourceKind
    detectorId: str
    sourceTrackId: str
    aircraftId: Optional[str] = None
    lastSeen: str
    bindingStatus: Optional[Literal["candidate", "confirmed"]] = None  # from engine BoundSource.confirmed
    origin: Optional[Literal["device", "generated"]] = None


class TargetSnapshot(BaseModel):
    fusionId: str
    trackSegmentId: str
    aircraftId: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    altitude: Optional[float] = None
    altitudeDatum: Optional[str] = None
    altitudeMode: Optional[str] = None
    altitudeStateTime: Optional[str] = None
    lastAltitudeObservedAt: Optional[str] = None
    altitudeObservationIds: list[str] = Field(default_factory=list)
    speed: Optional[float] = None
    heading: Optional[float] = None
    verticalSpeed: Optional[float] = None
    stateTime: str
    lastObservedAt: str
    displayStateTime: Optional[str] = None
    trackStatus: TrackStatus
    positionMode: PositionMode
    positionSource: Optional[SourceKind] = None
    sources: list[SourceKind] = Field(default_factory=list)
    sourceTracks: list[SourceTrackRef] = Field(default_factory=list)
    qualityFlags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    # Immutable KF primary-update history (not display/predicted coast copies)
    committedHistory: list[dict[str, Any]] = Field(default_factory=list)
    identityStatus: Optional[Literal["unknown", "identified", "conflict"]] = None
    objectClass: Optional[Literal["unknown", "drone", "bird", "other"]] = None
    fusionMethod: Optional[Literal["primary_source", "multi_sensor_estimate"]] = None
    contributingSources: list[SourceKind] = Field(default_factory=list)


class FusionEvent(BaseModel):
    type: str
    time: str
    fusionId: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ProcessRequest(BaseModel):
    sessionId: str
    batchId: str
    mode: Mode = "realtime"
    fusionProfile: Optional[str] = None  # omitted or legacy keeps the existing engine
    processingTime: str
    observations: list[dict[str, Any]] = Field(default_factory=list)


class ProcessResponse(BaseModel):
    sessionId: str
    batchId: str
    epoch: str
    snapshotSeq: int
    algorithmVersion: str
    configVersion: str
    watermark: str
    tracks: list[TargetSnapshot]
    rejected: list[Rejected]
    events: list[FusionEvent]
    error: Optional[str] = None
    fusionProfile: Optional[str] = None
    trajectoryUpdates: list[dict[str, Any]] = Field(default_factory=list)
    altitudeUpdates: list[dict[str, Any]] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    jobId: str
    fusionProfile: str = "multisensor-v1"
    observations: list[dict[str, Any]] = Field(default_factory=list)
    maxSnapshots: int = 2000


class ReplayResponse(BaseModel):
    jobId: str
    fusionProfile: str
    algorithmVersion: str
    configVersion: str
    summary: dict[str, Any]
    snapshots: list[dict[str, Any]]
    trajectory: list[dict[str, Any]]
    altitudeUpdates: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    error: Optional[str] = None
