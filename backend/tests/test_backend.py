import os
import tempfile
import time
import unittest

from backend.core import Settings
from backend.database import Database
from backend.services import CampusService, EventBus, natural_room_key


class FakeSupabase:
    def __init__(self): self.calls = []
    def mirror_telemetry(self, *args): self.calls.append(args)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.file.close()
        self.db = Database(self.file.name)
        self.db.initialize(); self.db.seed()
        self.service = CampusService(self.db, Settings(database_path=self.file.name, empty_delay_seconds=0), EventBus())

    def tearDown(self):
        os.unlink(self.file.name)

    def test_natural_room_order(self):
        ids = [room["id"] for room in self.service.rooms()]
        self.assertEqual(ids[:8], ["A006", "A007", "A008", "A009", "A011", "A013", "A015", "A101"])
        self.assertEqual(sorted(["A101", "A006", "A009"], key=natural_room_key), ["A006", "A009", "A101"])

    def test_empty_room_automation_acknowledges_and_saves(self):
        executions = self.service.evaluate_automation()
        a104 = self.service.room("A104")
        self.assertTrue(any(item["room_id"] == "A104" for item in executions))
        self.assertFalse(a104["appliances"]["light"]["actual"])
        self.assertFalse(a104["appliances"]["fan"]["actual"])
        self.assertEqual(a104["power_w"], 0)
        self.assertGreater(self.service.summary()["energy_saved_kwh"], 0)

    def test_command_ack_is_idempotent(self):
        command = self.service.command("ESP32-A101", "LIGHT_OFF", "TEST", {})
        self.service.ack(command["command_id"], "SUCCESS", {"light": False})
        self.assertFalse(self.service.room("A101")["appliances"]["light"]["actual"])

    def test_duplicate_pending_command_is_not_created(self):
        iot_settings = Settings(database_path=self.file.name, simulation_mode=False)
        service = CampusService(self.db, iot_settings, EventBus())
        first = service.command("ESP32-A101", "LIGHT_OFF", "TEST", {})
        second = service.command("ESP32-A101", "LIGHT_OFF", "TEST", {})
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertTrue(second["duplicate"])

    def test_mqtt_telemetry_to_automation_to_ack_pipeline(self):
        mirror = FakeSupabase()
        service = CampusService(self.db, Settings(database_path=self.file.name, empty_delay_seconds=0), EventBus(), supabase_store=mirror)
        state = service.ingest_mqtt("smart-campus/A/1/A104/telemetry", {
            "device_id": "ESP32-A104", "room_id": "A104", "occupancy": False,
            "power_kw": .20, "temperature": 26, "humidity": 58,
            "energy_kwh": 2.5, "appliances": {"light": True, "fan": True, "ac": False},
        })
        self.assertFalse(state["occupied"])
        self.assertEqual(state["power_w"], 200)
        self.assertEqual(len(mirror.calls), 1)
        execution = next(item for item in service.evaluate_automation() if item["room_id"] == "A104")
        self.assertEqual(execution["result"], "SUCCESS")
        self.assertEqual(service.room("A104")["power_w"], 0)
        self.assertEqual(service.alerts(), [])

    def test_empty_room_waits_for_configured_delay(self):
        service = CampusService(self.db, Settings(database_path=self.file.name, empty_delay_seconds=5), EventBus())
        self.assertEqual(service.evaluate_automation(), [])
        self.assertTrue(service.room("A104")["appliances"]["light"]["actual"])

    def test_stale_device_creates_single_offline_alert(self):
        service = CampusService(self.db, Settings(database_path=self.file.name, telemetry_freshness_seconds=0), EventBus())
        first = service.monitor_device_health()
        second = service.monitor_device_health()
        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertEqual(len([item for item in service.alerts() if item["category"] == "DEVICE_OFFLINE"]), len(first))

    def test_retry_exhaustion_creates_one_failure_alert(self):
        service = CampusService(self.db, Settings(database_path=self.file.name, simulation_mode=False, command_timeout_seconds=0, max_command_retries=3), EventBus())
        command = service.command("ESP32-A101", "LIGHT_OFF", "TEST", {})
        for _ in range(3):
            with self.db.connection() as con:
                con.execute("UPDATE device_commands SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (command["command_id"],))
            service.retry_pending_commands()
        self.assertTrue(any(alert["category"] == "COMMAND_FAILURE" for alert in service.alerts()))
