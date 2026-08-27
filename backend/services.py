from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .core import Settings
from .database import Database, utcnow


def natural_room_key(room_id: str) -> tuple[str, int]:
    return room_id[0].upper(), int(room_id[1:])


class EventBus:
    def __init__(self) -> None:
        self.connections: set[Any] = set()

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        stale = []
        for connection in self.connections:
            try:
                await connection.send_json({"event": event, "data": payload})
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.connections.discard(connection)


class RuleBasedRecommendationProvider:
    """Deterministic provider; a local model can implement this same interface later."""
    def analyze(self, rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
        insights = []
        for room in rooms:
            if not room["occupied"] and room["power_w"] >= 100:
                insights.append({"room_id": room["id"], "type": "ENERGY_WASTE", "severity": "MEDIUM", "title": "Empty room consuming power", "explanation": f"{room['id']} has no occupants while it is drawing {room['power_w']:.0f} W.", "recommendation": "Turn off non-protected light and fan appliances.", "confidence": .94})
            if room["power_w"] > max(1500, room["baseline_power_w"] * 3):
                insights.append({"room_id": room["id"], "type": "ANOMALY", "severity": "HIGH", "title": "Unusual energy spike", "explanation": f"{room['id']} exceeds its historical baseline.", "recommendation": "Inspect connected appliances and sensor readings.", "confidence": .88})
        return insights


class CampusService:
    def __init__(self, db: Database, settings: Settings, bus: EventBus, adapter: Any | None = None, supabase_store: Any | None = None) -> None:
        self.db, self.settings, self.bus = db, settings, bus
        self.provider, self.adapter, self.supabase_store = RuleBasedRecommendationProvider(), adapter, supabase_store

    def rooms(self) -> list[dict[str, Any]]:
        with self.db.connection() as con:
            rows = con.execute("""
                SELECT r.id, r.room_number, b.code AS block, f.floor_number, f.name AS floor,
                       COALESCE((SELECT occupancy_count FROM occupancy_readings o WHERE o.room_id=r.id ORDER BY o.id DESC LIMIT 1),0) AS occupancy_count,
                       COALESCE((SELECT occupied FROM occupancy_readings o WHERE o.room_id=r.id ORDER BY o.id DESC LIMIT 1),0) AS occupied,
                       COALESCE((SELECT power_w FROM energy_readings e WHERE e.room_id=r.id ORDER BY e.id DESC LIMIT 1),0) AS power_w,
                       COALESCE((SELECT energy_kwh FROM energy_readings e WHERE e.room_id=r.id ORDER BY e.id DESC LIMIT 1),0) AS energy_kwh,
                       COALESCE((SELECT temperature FROM telemetry_latest t WHERE t.room_id=r.id),26) AS temperature,
                       COALESCE((SELECT humidity FROM telemetry_latest t WHERE t.room_id=r.id),58) AS humidity
                FROM rooms r JOIN floors f ON f.id=r.floor_id JOIN buildings b ON b.id=f.building_id
                ORDER BY b.code, f.floor_number, CAST(r.room_number AS INTEGER)
            """).fetchall()
            appliances = con.execute("SELECT room_id, appliance_type, desired_state, actual_state, protected, manual_override_until FROM appliances").fetchall()
        by_room: dict[str, dict[str, Any]] = {}
        for appliance in appliances:
            by_room.setdefault(appliance["room_id"], {})[appliance["appliance_type"]] = {"desired": bool(appliance["desired_state"]), "actual": bool(appliance["actual_state"]), "protected": bool(appliance["protected"]), "manual_override_until": appliance["manual_override_until"]}
        return [{**dict(row), "occupied": bool(row["occupied"]), "warning": not bool(row["occupied"]) and row["power_w"] >= self.settings.power_threshold_w, "appliances": by_room.get(row["id"], {}), "baseline_power_w": 200} for row in rows]

    def room(self, room_id: str) -> dict[str, Any] | None:
        return next((room for room in self.rooms() if room["id"] == room_id.upper()), None)

    def summary(self) -> dict[str, Any]:
        rooms = self.rooms()
        with self.db.connection() as con:
            saved = con.execute("SELECT COALESCE(SUM(saved_kwh),0) value FROM automation_executions WHERE result='SUCCESS'").fetchone()["value"]
            alerts = con.execute("SELECT COUNT(*) value FROM alerts WHERE status='OPEN'").fetchone()["value"]
        return {"mode": self.settings.mode, "rooms_occupied": sum(r["occupied"] for r in rooms), "total_rooms": len(rooms), "live_power_w": round(sum(r["power_w"] for r in rooms), 2), "energy_today_kwh": round(sum(r["energy_kwh"] for r in rooms), 2), "energy_saved_kwh": round(saved, 3), "active_alerts": alerts}

    def _alert(self, room_id: str, category: str, severity: str, message: str) -> None:
        with self.db.connection() as con:
            existing = con.execute("SELECT id FROM alerts WHERE room_id=? AND category=? AND status='OPEN'", (room_id, category)).fetchone()
            if not existing:
                con.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), room_id, severity, category, message, "OPEN", utcnow(), None))

    def telemetry(self, data: dict[str, Any]) -> dict[str, Any]:
        room_id = data["device_id"].replace("ESP32-", "").upper()
        if not self.room(room_id):
            raise ValueError("unknown device or room")
        now = data["timestamp"].isoformat()
        with self.db.connection() as con:
            device = con.execute("SELECT id FROM devices WHERE id=?", (data["device_id"],)).fetchone()
            if not device:
                raise ValueError("unknown device")
            con.execute("UPDATE devices SET connectivity_status='ONLINE', last_seen=? WHERE id=?", (utcnow(), data["device_id"]))
            last = con.execute("SELECT timestamp FROM energy_readings WHERE room_id=? ORDER BY id DESC LIMIT 1", (room_id,)).fetchone()
            if last and last["timestamp"] == now:
                return self.room(room_id) or {}
            con.execute("INSERT OR REPLACE INTO telemetry_latest(room_id,temperature,humidity,updated_at) VALUES (?,?,?,?)", (room_id, data.get("temperature"), data.get("humidity"), now))
            con.execute("INSERT INTO occupancy_readings (room_id,occupancy_count,occupied,confidence,timestamp) VALUES (?,?,?,?,?)", (room_id,data["occupancy"],int(data["occupancy"]>0),.95,now))
            con.execute("INSERT INTO energy_readings (room_id,device_id,voltage,current,power_w,energy_kwh,timestamp) VALUES (?,?,?,?,?,?,?)", (room_id,data["device_id"],data.get("voltage"),data.get("current"),data["power_w"],data["energy_kwh"],now))
            for appliance, enabled in data["relays"].items():
                if appliance in ("light","fan","ac"):
                    con.execute("UPDATE appliances SET actual_state=? WHERE room_id=? AND appliance_type=?", (int(enabled),room_id,appliance))
        if self.supabase_store:
            self.supabase_store.mirror_telemetry(room_id,data["device_id"],data["occupancy"] > 0,data["power_w"],data.get("temperature"),data.get("humidity"),data["relays"],now)
        return self.room(room_id) or {}

    def ingest_mqtt(self, topic: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Maps the documented ESP32 MQTT schema into the same validated persistence path."""
        kind = topic.rsplit("/", 1)[-1]
        if kind == "ack":
            self.ack(str(payload.get("command_id", "")), str(payload.get("status", "failed")).upper(), payload.get("actual_state", payload.get("appliances", {})))
            return None
        if kind == "heartbeat":
            device_id = str(payload.get("device_id", ""))
            with self.db.connection() as con:
                con.execute("UPDATE devices SET connectivity_status='ONLINE',last_seen=? WHERE id=?", (utcnow(), device_id))
            return None
        if kind not in {"telemetry", "occupancy", "power", "appliances"}:
            return None
        device_id = str(payload.get("device_id", ""))
        room_id = str(payload.get("room_id", device_id.replace("ESP32-", ""))).upper()
        if device_id.upper() != f"ESP32-{room_id}".upper():
            raise ValueError("device is not authorized for this room")
        normalized = {"device_id": device_id, "timestamp": datetime.fromisoformat(str(payload.get("timestamp", utcnow())).replace("Z", "+00:00")), "occupancy": int(bool(payload.get("occupancy", False))), "temperature": payload.get("temperature"), "humidity": payload.get("humidity"), "voltage": payload.get("voltage"), "current": payload.get("current"), "power_w": float(payload.get("power_kw", 0)) * 1000, "energy_kwh": float(payload.get("energy_kwh", 0)), "relays": payload.get("appliances", {})}
        from .schemas import TelemetryIn
        return self.telemetry(TelemetryIn(**normalized).model_dump())

    def set_manual_override(self, room_id: str, appliance: str, enabled: bool, duration_seconds: int) -> dict[str, Any]:
        room = self.room(room_id)
        if not room: raise ValueError("room not found")
        until = (datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)).isoformat() if enabled else None
        with self.db.connection() as con:
            con.execute("UPDATE appliances SET manual_override_until=? WHERE room_id=? AND appliance_type=?", (until,room["id"],appliance))
            con.execute("INSERT INTO audit_logs(action,entity_type,entity_id,metadata,timestamp) VALUES (?,?,?,?,?)", ("MANUAL_OVERRIDE","appliance",f"{room['id']}-{appliance}",self.db.json({"enabled":enabled,"until":until}),utcnow()))
        return {"room_id": room["id"], "appliance": appliance, "manual_override_until": until}

    def command(self, device_id: str, command: str, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.db.connection() as con:
            if not con.execute("SELECT 1 FROM devices WHERE id=? AND connectivity_status='ONLINE'", (device_id,)).fetchone():
                raise ValueError("device is offline")
            existing = con.execute("SELECT id FROM device_commands WHERE device_id=? AND command_type=? AND status IN ('PENDING','SENT') ORDER BY created_at DESC LIMIT 1", (device_id, command)).fetchone()
            if existing:
                return {"command_id": existing["id"], "status": "PENDING", "duplicate": True}
            command_id = f"CMD-{uuid.uuid4().hex[:12].upper()}"
            con.execute("INSERT INTO device_commands VALUES (?,?,?,?,?,?,?,?,?)", (command_id,device_id,command,self.db.json(payload),"PENDING",utcnow(),None,0,reason))
            appliance = command.split("_")[0].lower()
            if appliance in ("light","fan","ac"):
                con.execute("UPDATE appliances SET desired_state=? WHERE room_id=(SELECT room_id FROM devices WHERE id=?) AND appliance_type=?", (int(command.endswith("_ON")),device_id,appliance))
        # Simulation acknowledges immediately; real mode leaves this pending until MQTT ACK arrives.
        if self.settings.mode == "simulation":
            self.ack(command_id, "SUCCESS", {command.split("_")[0].lower(): command.endswith("_ON")})
        elif self.adapter:
            room_id = device_id.removeprefix("ESP32-")
            self.adapter.send_command(device_id, {"command_id": command_id, "device_id": device_id, "room_id": room_id, "action": "turn_on" if command.endswith("_ON") else "turn_off", "appliances": [command.split("_")[0].lower()], "reason": reason, "timestamp": utcnow()})
        return {"command_id": command_id, "status": "PENDING" if self.settings.mode == "iot" else "ACKNOWLEDGED"}

    def ack(self, command_id: str, status: str, actual_state: dict[str, bool]) -> None:
        failure_room: str | None = None
        with self.db.connection() as con:
            command = con.execute("SELECT * FROM device_commands WHERE id=?", (command_id,)).fetchone()
            if not command or command["status"] in ("ACKNOWLEDGED","FAILED"):
                return
            con.execute("UPDATE device_commands SET status=?,acknowledged_at=? WHERE id=?", ("ACKNOWLEDGED" if status == "SUCCESS" else "FAILED",utcnow(),command_id))
            room = con.execute("SELECT room_id FROM devices WHERE id=?", (command["device_id"],)).fetchone()["room_id"]
            if status == "SUCCESS":
                for appliance, value in actual_state.items():
                    con.execute("UPDATE appliances SET actual_state=? WHERE room_id=? AND appliance_type=?", (int(value),room,appliance))
                measured_power = con.execute("SELECT COALESCE(SUM(rated_power_w * actual_state),0) value FROM appliances WHERE room_id=?", (room,)).fetchone()["value"]
                con.execute("UPDATE energy_readings SET power_w=? WHERE id=(SELECT id FROM energy_readings WHERE room_id=? ORDER BY id DESC LIMIT 1)", (measured_power,room))
            else:
                failure_room = room
        if failure_room:
            self._alert(failure_room,"COMMAND_FAILURE","HIGH",f"{failure_room} device did not acknowledge command acknowledgement.")

    def retry_pending_commands(self) -> list[str]:
        """Bounded retry bookkeeping for real-MQTT mode; transport republishes by command id."""
        failed: list[str] = []
        failures: list[str] = []
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.settings.command_timeout_seconds)).isoformat()
        with self.db.connection() as con:
            pending = con.execute("SELECT * FROM device_commands WHERE status='PENDING' AND created_at<?", (cutoff,)).fetchall()
            for command in pending:
                if command["retry_count"] + 1 >= self.settings.max_command_retries:
                    con.execute("UPDATE device_commands SET status='FAILED',retry_count=retry_count+1 WHERE id=?", (command["id"],))
                    room = con.execute("SELECT room_id FROM devices WHERE id=?", (command["device_id"],)).fetchone()["room_id"]
                    failed.append(command["id"])
                    failures.append(room)
                else:
                    # Exponential backoff is represented by a fresh creation timestamp for the next attempt.
                    delay = 2 ** command["retry_count"]
                    con.execute("UPDATE device_commands SET retry_count=retry_count+1,created_at=? WHERE id=?", ((datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(),command["id"]))
        for room in failures:
            self._alert(room,"COMMAND_FAILURE","HIGH",f"{room} device did not acknowledge automation command.")
        return failed

    def monitor_device_health(self) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.settings.telemetry_freshness_seconds)).isoformat()
        offline: list[str] = []
        offline_rooms: list[str] = []
        with self.db.connection() as con:
            rows = con.execute("SELECT id,room_id FROM devices WHERE last_seen IS NULL OR last_seen<?", (cutoff,)).fetchall()
            for row in rows:
                if con.execute("UPDATE devices SET connectivity_status='OFFLINE' WHERE id=? AND connectivity_status!='OFFLINE'", (row["id"],)).rowcount:
                    offline.append(row["id"])
                    offline_rooms.append(row["room_id"])
        for room in offline_rooms:
            self._alert(room,"DEVICE_OFFLINE","HIGH",f"{room} controller is offline or telemetry is stale.")
        return offline

    def energy_by_block(self) -> list[dict[str, Any]]:
        values: dict[str, dict[str, float]] = {}
        for room in self.rooms():
            bucket = values.setdefault(room["block"], {"power_w": 0, "energy_kwh": 0})
            bucket["power_w"] += room["power_w"]; bucket["energy_kwh"] += room["energy_kwh"]
        return [{"block": block, **{key: round(value, 3) for key, value in data.items()}} for block, data in sorted(values.items())]

    def evaluate_automation(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        results = []
        for room in self.rooms():
            if room["occupied"] or room["power_w"] < self.settings.power_threshold_w:
                continue
            with self.db.connection() as con:
                reading = con.execute("SELECT timestamp FROM occupancy_readings WHERE room_id=? AND occupied=0 ORDER BY id DESC LIMIT 1", (room["id"],)).fetchone()
                empty_for = (now - datetime.fromisoformat(reading["timestamp"])).total_seconds() if reading else 0
                if empty_for < self.settings.empty_delay_seconds:
                    self._alert(room["id"],"ENERGY_WASTE","MEDIUM",f"{room['id']} is empty while appliances are consuming power.")
                    continue
                candidates = [name for name, state in room["appliances"].items() if state["actual"] and not state["protected"] and not (state["manual_override_until"] and datetime.fromisoformat(state["manual_override_until"]) > now)]
            if not candidates:
                continue
            before = room["power_w"]
            execution_id = f"EXEC-{room['id']}-{now.strftime('%Y%m%d%H%M%S')}"
            outcome = "SUCCESS"
            for appliance in candidates:
                try:
                    self.command(f"ESP32-{room['id']}", f"{appliance.upper()}_OFF", "EMPTY_ROOM_AUTOMATION", {"execution_id": execution_id})
                except ValueError:
                    outcome = "FAILED"
            after = 0.0 if self.settings.mode == "simulation" else before
            saved = max(0, before-after) / 1000 * .25
            with self.db.connection() as con:
                con.execute("INSERT INTO automation_executions VALUES (?,?,?,?,?,?,?,?,?,?)", (execution_id,"empty-room-energy-saver",room["id"],utcnow(),",".join(candidates),outcome,"Empty room energy saver",before,after,saved))
                if outcome == "SUCCESS":
                    con.execute("UPDATE alerts SET status='RESOLVED',resolved_at=? WHERE room_id=? AND category='ENERGY_WASTE' AND status='OPEN'", (utcnow(),room["id"]))
            results.append({"execution_id": execution_id,"room_id": room["id"],"result": outcome,"before_power_w": before,"after_power_w": after,"saved_kwh": saved})
        return results

    def alerts(self) -> list[dict[str, Any]]:
        with self.db.connection() as con:
            return [dict(row) for row in con.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()]

    def insights(self, room_id: str | None = None) -> list[dict[str, Any]]:
        values = self.provider.analyze(self.rooms())
        return [value for value in values if not room_id or value["room_id"] == room_id.upper()]
