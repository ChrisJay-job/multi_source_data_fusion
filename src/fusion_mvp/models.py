from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SourceKind = Literal["rid", "spectrum", "radar"]
Mode = Literal["realtime", "replay"]
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


class TargetSnapshot(BaseModel):
    fusionId: str
    trackSegmentId: str
    aircraftId: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    altitude: Optional[float] = None
    altitudeDatum: Optional[str] = None
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


class FusionEvent(BaseModel):
    type: str
    time: str
    fusionId: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ProcessRequest(BaseModel):
    sessionId: str
    batchId: str
    mode: Mode = "realtime"
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
