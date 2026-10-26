# Schema 示例（fusion-mqtt.v1）

## 输入 observations

```json
{
  "schemaVersion": "fusion-mqtt.v1",
  "messageType": "observations",
  "messageId": "demo-run-b000001",
  "tenantId": "tenant-demo",
  "siteId": "site-demo",
  "sessionId": "tenant-demo-site-demo-demo-run",
  "sentAt": "2026-10-24T13:00:00.100Z",
  "payload": {
    "batchId": "demo-run-b000001",
    "fusionProfile": "multisensor-v1",
    "mode": "realtime",
    "clockMode": "wallclock_rebase_1x",
    "observations": [
      {
        "observationId": "5_rid_pp5_leida1_simp-2-1581F67QC24CL015638V",
        "source": "rid",
        "detectorId": "78799483c4da136d0000",
        "sourceTrackId": "1581F67QC24CL015638V",
        "aircraftId": "1581F67QC24CL015638V",
        "measurementTime": "2026-10-24T13:00:00.000Z",
        "receivedAt": "2026-10-24T13:00:00.000Z",
        "longitude": 118.3558425,
        "latitude": 35.1462593,
        "altitude": 80.0,
        "altitudeDatum": "MSL",
        "speed": 0.5,
        "heading": 253.0,
        "rawRef": {
          "originalMeasurementTime": "2026-06-24T18:42:01.691Z",
          "altitudeMappingVersion": "database_altitude_msl_v1"
        }
      }
    ]
  }
}
```

> 当前 HTTP 核心已支持 `multisensor-v1` / `legacy`。示例默认 `multisensor-v1`；`multisensor-3d-v1` 待高度 profile 落地后再作默认。

## ack（stored）

```json
{
  "schemaVersion": "fusion-mqtt.v1",
  "messageType": "ack",
  "messageId": "ack-demo-run-b000001-stored",
  "tenantId": "tenant-demo",
  "siteId": "site-demo",
  "sessionId": "tenant-demo-site-demo-demo-run",
  "sentAt": "2026-10-24T13:00:00.120Z",
  "payload": {
    "refMessageId": "demo-run-b000001",
    "status": "stored",
    "detail": { "batchId": "demo-run-b000001" }
  }
}
```

## result（摘要）

`payload.tracks` 不含完整 `committedHistory`。`trajectoryUpdates[].evidence` 按持久 `observationId` 回填。

## control

```json
{
  "schemaVersion": "fusion-mqtt.v1",
  "messageType": "control",
  "messageId": "ctrl-run-end-1",
  "tenantId": "tenant-demo",
  "siteId": "site-demo",
  "sessionId": "tenant-demo-site-demo-demo-run",
  "sentAt": "2026-10-24T13:30:00.000Z",
  "payload": { "action": "run.end" }
}
```
