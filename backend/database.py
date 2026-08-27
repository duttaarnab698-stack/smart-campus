from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connection() as con:
            con.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS campuses (id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT, timezone TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS buildings (id TEXT PRIMARY KEY, campus_id TEXT NOT NULL, name TEXT NOT NULL, code TEXT NOT NULL, FOREIGN KEY(campus_id) REFERENCES campuses(id));
            CREATE TABLE IF NOT EXISTS floors (id TEXT PRIMARY KEY, building_id TEXT NOT NULL, floor_number INTEGER NOT NULL, name TEXT NOT NULL, FOREIGN KEY(building_id) REFERENCES buildings(id));
            CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, floor_id TEXT NOT NULL, room_number TEXT NOT NULL, room_name TEXT, capacity INTEGER NOT NULL DEFAULT 40, room_type TEXT DEFAULT 'CLASSROOM', created_at TEXT NOT NULL, UNIQUE(floor_id, room_number));
            CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, room_id TEXT NOT NULL, device_uid TEXT UNIQUE NOT NULL, device_type TEXT NOT NULL, name TEXT NOT NULL, firmware_version TEXT, connectivity_status TEXT NOT NULL DEFAULT 'ONLINE', last_seen TEXT, created_at TEXT NOT NULL, FOREIGN KEY(room_id) REFERENCES rooms(id));
            CREATE TABLE IF NOT EXISTS sensors (id TEXT PRIMARY KEY, device_id TEXT NOT NULL, sensor_type TEXT NOT NULL, unit TEXT, status TEXT NOT NULL DEFAULT 'ONLINE');
            CREATE TABLE IF NOT EXISTS telemetry_latest (room_id TEXT PRIMARY KEY, temperature REAL, humidity REAL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appliances (id TEXT PRIMARY KEY, room_id TEXT NOT NULL, appliance_type TEXT NOT NULL, name TEXT NOT NULL, rated_power_w REAL NOT NULL, relay_channel TEXT, desired_state INTEGER NOT NULL DEFAULT 0, actual_state INTEGER NOT NULL DEFAULT 0, protected INTEGER NOT NULL DEFAULT 0, manual_override_until TEXT, FOREIGN KEY(room_id) REFERENCES rooms(id));
            CREATE TABLE IF NOT EXISTS occupancy_readings (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, sensor_id TEXT, occupancy_count INTEGER NOT NULL, occupied INTEGER NOT NULL, confidence REAL NOT NULL, timestamp TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS energy_readings (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, device_id TEXT, voltage REAL, current REAL, power_w REAL NOT NULL, energy_kwh REAL NOT NULL, power_factor REAL, frequency REAL, timestamp TEXT NOT NULL, UNIQUE(room_id, timestamp));
            CREATE TABLE IF NOT EXISTS automation_rules (id TEXT PRIMARY KEY, name TEXT, enabled INTEGER NOT NULL, priority INTEGER NOT NULL, conditions TEXT, actions TEXT, cooldown_seconds INTEGER NOT NULL DEFAULT 30);
            CREATE TABLE IF NOT EXISTS automation_executions (id TEXT PRIMARY KEY, rule_id TEXT, room_id TEXT NOT NULL, triggered_at TEXT NOT NULL, action TEXT, result TEXT NOT NULL, reason TEXT, before_power_w REAL, after_power_w REAL, saved_kwh REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS device_commands (id TEXT PRIMARY KEY, device_id TEXT NOT NULL, command_type TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, acknowledged_at TEXT, retry_count INTEGER NOT NULL DEFAULT 0, reason TEXT);
            CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, room_id TEXT, severity TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
            CREATE TABLE IF NOT EXISTS insights (id TEXT PRIMARY KEY, room_id TEXT, insight_type TEXT NOT NULL, title TEXT NOT NULL, explanation TEXT NOT NULL, recommendation TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT, metadata TEXT, timestamp TEXT NOT NULL);
            """)

    def seed(self) -> None:
        with self.connection() as con:
            if con.execute("SELECT 1 FROM campuses LIMIT 1").fetchone():
                return
            now = utcnow()
            con.execute("INSERT INTO campuses VALUES ('campus-25','Campus 25','SIH Demo Campus','Asia/Kolkata',?)", (now,))
            room_numbers = {"A": ["006","007","008","009","011","013","015","101","102","103","104","105","106","201","202","203","301","302"], "B": ["001","002","003","004","101","102","103","201","202","301","302"], "C": ["001","002","101","102","201","202","301","302"]}
            for block, numbers in room_numbers.items():
                building = f"block-{block.lower()}"
                con.execute("INSERT INTO buildings VALUES (?,?,?,?)", (building, "campus-25", f"Block {block}", block))
                floor_ids: dict[int, str] = {}
                for number, name in enumerate(("Ground Floor", "First Floor", "Second Floor", "Third Floor")):
                    fid = f"{building}-f{number}"
                    floor_ids[number] = fid
                    con.execute("INSERT INTO floors VALUES (?,?,?,?)", (fid, building, number, name))
                for i, number in enumerate(numbers):
                    room_id, floor_number = f"{block}{number}", 0 if int(number) < 100 else int(number) // 100
                    con.execute("INSERT INTO rooms VALUES (?,?,?,?,?,?,?)", (room_id, floor_ids[floor_number], number, room_id, 40, "CLASSROOM", now))
                    device_id = f"ESP32-{room_id}"
                    con.execute("INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?)", (device_id, room_id, device_id, "ESP32", f"{room_id} Controller", "sim-1.0", "ONLINE", now, now))
                    for appliance, watts in (("light",80),("fan",120),("ac",1200)):
                        on = 1 if (i * 7) % 10 < 5 and appliance != "ac" else 0
                        con.execute("INSERT INTO appliances VALUES (?,?,?,?,?,?,?,?,?,?)", (f"{room_id}-{appliance}",room_id,appliance,appliance.title(),watts,appliance,on,on,0,None))
                    con.execute("INSERT INTO occupancy_readings (room_id, occupancy_count, occupied, confidence, timestamp) VALUES (?,?,?,?,?)", (room_id, 1 if i % 2 else 0, i % 2, .92, now))
                    con.execute("INSERT INTO energy_readings (room_id,device_id,power_w,energy_kwh,timestamp) VALUES (?,?,?,?,?)", (room_id,device_id,200 if i % 2 else 0,round(1+i*.13,2),now))
            con.execute("UPDATE appliances SET desired_state=1,actual_state=1 WHERE id IN ('A104-light','A104-fan')")
            con.execute("UPDATE occupancy_readings SET occupancy_count=0,occupied=0 WHERE room_id='A104'")
            con.execute("UPDATE energy_readings SET power_w=200 WHERE room_id='A104'")

    @staticmethod
    def json(value: object) -> str:
        return json.dumps(value, separators=(",", ":"))
