"""IoT transport boundary. MQTT can be enabled without changing API or automation code."""
from __future__ import annotations
from abc import ABC, abstractmethod
import json
import os
import ssl
from typing import Any, Callable


class DeviceAdapter(ABC):
    @abstractmethod
    def send_command(self, device_id: str, command: dict[str, Any]) -> None: ...
    @abstractmethod
    def topic(self, campus_id: str, device_id: str, kind: str) -> str: ...


class MQTTDeviceAdapter(DeviceAdapter):
    """MQTT protocol contract; inject a paho client in production deployment."""
    def __init__(self, settings: Any, client: Any | None = None, on_message: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.settings, self.client, self.on_message = settings, client, on_message
        self.connected, self.subscribed, self.last_error = False, False, None
    def connect(self) -> None:
        if self.client: return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as error:
            raise RuntimeError("Install paho-mqtt to enable SIMULATION_MODE=false") from error
        if not self.settings.mqtt_broker_url:
            raise RuntimeError("MQTT_BROKER_URL is required when SIMULATION_MODE=false")
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.settings.mqtt_username: self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        if self.settings.mqtt_tls_enabled:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
            self.client.tls_insecure_set(False)
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.connect(self.settings.mqtt_broker_url, self.settings.mqtt_broker_port, keepalive=30)
        self.client.loop_start()
    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        code = getattr(reason_code, "value", reason_code)
        self.connected = code == 0 or str(reason_code).lower() == "success"
        self.last_error = None if self.connected else "connection_refused"
        if self.connected:
            result, _ = client.subscribe("smart-campus/+/+/+/+", qos=1)
            self.subscribed = result == 0
    def _on_disconnect(self, _client: Any, _userdata: Any, _flags: Any, _reason_code: Any, _properties: Any = None) -> None:
        self.connected, self.subscribed = False, False
    def health(self) -> dict[str, object]:
        return {"state": "CONNECTED" if self.connected and self.subscribed else "CONNECTING" if self.client else "NOT_CONNECTED", "tls": self.settings.mqtt_tls_enabled, "port": self.settings.mqtt_broker_port}
    def disconnect(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        self.connected, self.subscribed = False, False
    def probe_publish(self) -> bool:
        """Tests broker publish permission on a non-control status topic only."""
        if not self.client or not self.connected: return False
        result = self.client.publish("smart-campus/healthcheck/0/backend/status", json.dumps({"source":"fastapi","kind":"connectivity_probe"}), qos=1)
        if result.rc != 0: return False
        result.wait_for_publish(timeout=5)
        return result.is_published()
    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        try:
            payload = json.loads(message.payload.decode())
            if self.on_message: self.on_message(message.topic, payload)
        except (ValueError, UnicodeDecodeError):
            return
    def topic(self, campus_id: str, device_id: str, kind: str) -> str:
        # ESP32 topics are scoped by assigned room; callers never choose arbitrary topics.
        return f"smart-campus/{campus_id}/{device_id}/{kind}"
    def send_command(self, device_id: str, command: dict[str, Any]) -> None:
        if not self.client:
            raise RuntimeError("MQTT client is not connected")
        room_id = command["room_id"]
        result = self.client.publish(f"smart-campus/{room_id[0]}/{room_id[1]}00/{room_id}/command", json.dumps(command), qos=1)
        if result.rc != 0:
            self.last_error = "publish_failed"
            raise RuntimeError("MQTT publish failed")


class SimulationCommandProvider(DeviceAdapter):
    def topic(self, campus_id: str, device_id: str, kind: str) -> str:
        return f"simulation/{campus_id}/{device_id}/{kind}"
    def send_command(self, device_id: str, command: dict[str, Any]) -> None:
        return None
