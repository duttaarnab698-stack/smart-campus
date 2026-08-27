"""Safe command-line connectivity check; it deliberately never prints configuration values."""
from __future__ import annotations

import json
import time
from dataclasses import replace

try:
    from .core import settings
    from .iot import MQTTDeviceAdapter
    from .supabase_store import SupabaseStore
except ImportError:
    from core import settings
    from iot import MQTTDeviceAdapter
    from supabase_store import SupabaseStore


def main() -> None:
    supabase = SupabaseStore(settings.supabase_url, settings.supabase_service_role_key)
    result: dict[str, object] = {"simulation_mode": settings.simulation_mode, "configuration": {"supabase_url_present": bool(settings.supabase_url), "supabase_service_role_key_present": bool(settings.supabase_service_role_key), "mqtt_host_present": bool(settings.mqtt_broker_url), "mqtt_username_present": bool(settings.mqtt_username), "mqtt_password_present": bool(settings.mqtt_password), "device_auth_secret_present": bool(settings.device_auth_secret)}, "supabase": supabase.health()}
    result["supabase_error_kind"] = supabase.last_error
    if settings.simulation_mode:
        result["mqtt"] = {"state": "SKIPPED_SIMULATION_MODE", "tls": settings.mqtt_tls_enabled, "port": settings.mqtt_broker_port}
    else:
        adapter = MQTTDeviceAdapter(settings)
        try:
            adapter.connect()
            time.sleep(3)
            result["mqtt"] = {**adapter.health(), "publish_probe": adapter.probe_publish()}
            adapter.disconnect()
        except Exception:
            result["mqtt"] = {"state": "UNAVAILABLE", "tls": settings.mqtt_tls_enabled, "port": settings.mqtt_broker_port}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
