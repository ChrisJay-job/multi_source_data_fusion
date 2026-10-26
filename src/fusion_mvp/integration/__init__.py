"""TASK-008 MQTT realtime adapter (HTTP core unchanged)."""

from .schemas import ALTITUDE_MAPPING_VERSION, SCHEMA_VERSION, SN_MAPPING_VERSION

__all__ = [
    "ALTITUDE_MAPPING_VERSION",
    "BridgeConfig",
    "MqttBridge",
    "SCHEMA_VERSION",
    "SN_MAPPING_VERSION",
]


def __getattr__(name: str):
    if name in {"BridgeConfig", "MqttBridge"}:
        from .mqtt_bridge import BridgeConfig, MqttBridge

        return {"BridgeConfig": BridgeConfig, "MqttBridge": MqttBridge}[name]
    raise AttributeError(name)
