from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
try:
    from .core import settings
    from .database import Database
    from .schemas import AckIn, CommandIn, DeviceRegistrationIn, HeartbeatIn, ModeIn, OverrideIn, TelemetryIn
    from .services import CampusService, EventBus
    from .iot import MQTTDeviceAdapter
    from .supabase_store import SupabaseStore
except ImportError:
    from core import settings
    from database import Database
    from schemas import AckIn, CommandIn, DeviceRegistrationIn, HeartbeatIn, ModeIn, OverrideIn, TelemetryIn
    from services import CampusService, EventBus
    from iot import MQTTDeviceAdapter
    from supabase_store import SupabaseStore

db = Database(settings.database_path)
bus = EventBus()
supabase_store = SupabaseStore(settings.supabase_url, settings.supabase_service_role_key)
service = CampusService(db, settings, bus, supabase_store=supabase_store)
def on_mqtt_message(topic: str, payload: dict):
    try: service.ingest_mqtt(topic, payload)
    except ValueError: return
adapter = MQTTDeviceAdapter(settings, on_message=on_mqtt_message) if settings.mode == "iot" else None
service.adapter = adapter

def require_device_token(x_device_token: str | None = Header(default=None)) -> None:
    if not settings.device_auth_secret or x_device_token != settings.device_auth_secret: raise HTTPException(401, "invalid device credential")

async def automation_loop() -> None:
    while True:
        for execution in service.evaluate_automation(): await bus.publish("automation.executed", execution)
        for command_id in service.retry_pending_commands(): await bus.publish("command.failed", {"command_id": command_id})
        for device_id in service.monitor_device_health(): await bus.publish("device.offline", {"device_id": device_id})
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize(); db.seed()
    if adapter: adapter.connect()
    task = asyncio.create_task(automation_loop())
    yield
    task.cancel()

app = FastAPI(title="Campus Pulse IoT API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "X-Device-Token"])

@app.get("/api/health")
def health():
    return {"status":"ok","mode":settings.mode,"automation":"ACTIVE","supabase": "SIMULATION" if settings.simulation_mode else supabase_store.health(),"mqtt": "SIMULATION" if settings.simulation_mode else (adapter.health() if adapter else {"state":"NOT_CONFIGURED"}),"timestamp":datetime.now(timezone.utc)}
@app.get("/health")
def root_health(): return health()
@app.get("/api/system/status")
def system_status():
    with db.connection() as con:
        online = con.execute("SELECT COUNT(*) value FROM devices WHERE connectivity_status='ONLINE'").fetchone()["value"]
        last = con.execute("SELECT MAX(last_seen) value FROM devices").fetchone()["value"]
    return {"fastapi":"ONLINE","supabase":"SIMULATION" if settings.simulation_mode else supabase_store.health(),"mqtt":"SIMULATION" if settings.simulation_mode else (adapter.health() if adapter else {"state":"NOT_CONFIGURED"}),"automation":"ACTIVE","simulation_mode":settings.simulation_mode,"online_devices":online,"offline_devices":service.summary()["total_rooms"]-online,"last_telemetry_at":last}
@app.get("/api/hardware/readiness")
def hardware_readiness():
    with db.connection() as con:
        devices = [dict(row) for row in con.execute("SELECT id,room_id,connectivity_status,last_seen,firmware_version FROM devices ORDER BY id").fetchall()]
    return {"mode": settings.mode, "transport": "MQTT" if settings.mode == "iot" else "SIMULATION", "ack_required": True, "device_authentication": True, "devices": devices, "commissioning_required": settings.mode != "iot"}
@app.get("/api/rooms")
def rooms():
    values=service.rooms(); return {"total":len(values),"rooms":values,"summary":service.summary()}
@app.get("/api/rooms/{room_id}")
def room(room_id: str):
    value=service.room(room_id)
    if not value: raise HTTPException(404,"room not found")
    return value
@app.get("/api/devices")
def devices():
    with db.connection() as con: return {"devices":[dict(row) for row in con.execute("SELECT * FROM devices ORDER BY id").fetchall()]}
@app.get("/api/devices/{device_id}")
def device(device_id: str):
    with db.connection() as con: row=con.execute("SELECT * FROM devices WHERE id=?",(device_id,)).fetchone()
    if not row: raise HTTPException(404,"device not found")
    return dict(row)
@app.post("/api/devices/register",dependencies=[Depends(require_device_token)])
def register_device(payload: DeviceRegistrationIn):
    room = service.room(payload.room_id)
    if not room: raise HTTPException(404,"room not found")
    if payload.device_id.upper() != f"ESP32-{room['id']}".upper(): raise HTTPException(403,"device ID is not authorized for this room")
    with db.connection() as con:
        con.execute("UPDATE devices SET firmware_version=?,connectivity_status='ONLINE',last_seen=? WHERE id=?",(payload.firmware_version,datetime.now(timezone.utc).isoformat(),payload.device_id))
    return {"device_id":payload.device_id,"room_id":room["id"],"status":"REGISTERED"}
@app.post("/api/devices/{device_id}/heartbeat",dependencies=[Depends(require_device_token)])
def device_heartbeat(device_id: str, payload: HeartbeatIn):
    if payload.device_id != device_id: raise HTTPException(403,"device ID mismatch")
    return heartbeat(payload)
@app.get("/api/energy")
def energy(): return service.summary()
@app.get("/api/energy/overview")
def energy_overview():
    data=service.summary(); data.update({"estimated_cost":round(data["energy_today_kwh"]*settings.electricity_rate_per_kwh,2),"co2_kg":round(data["energy_today_kwh"]*settings.co2_kg_per_kwh,3)}); return data
@app.get("/api/energy/by-block")
def energy_by_block(): return {"blocks":service.energy_by_block()}
@app.get("/api/energy/top-rooms")
def energy_top_rooms(): return {"rooms":sorted(service.rooms(),key=lambda room:room["energy_kwh"],reverse=True)[:10]}
@app.get("/api/energy/{room_id}")
def room_energy(room_id: str):
    value=service.room(room_id)
    if not value: raise HTTPException(404,"room not found")
    return {"room_id":value["id"],"power_w":value["power_w"],"energy_kwh":value["energy_kwh"]}
@app.get("/api/rooms/{room_id}/telemetry")
def room_telemetry(room_id: str): return room_energy(room_id)
@app.get("/api/rooms/{room_id}/appliances")
def room_appliances(room_id: str):
    value=service.room(room_id)
    if not value: raise HTTPException(404,"room not found")
    return {"room_id":value["id"],"appliances":value["appliances"]}
@app.post("/api/rooms/{room_id}/commands")
async def room_command(room_id: str, payload: CommandIn):
    room=service.room(room_id)
    if not room or payload.device_id.upper()!=f"ESP32-{room_id}".upper(): raise HTTPException(403,"device is not authorized for this room")
    return await device_command(payload)
@app.post("/api/rooms/{room_id}/override")
def room_override(room_id: str, payload: OverrideIn):
    try: return service.set_manual_override(room_id,payload.appliance,payload.enabled,payload.duration_seconds)
    except ValueError as error: raise HTTPException(404,str(error)) from error
@app.get("/api/alerts")
def alerts(): return {"alerts":service.alerts()}
@app.post("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str):
    with db.connection() as con:
        if not con.execute("SELECT id FROM alerts WHERE id=?",(alert_id,)).fetchone(): raise HTTPException(404,"alert not found")
        con.execute("UPDATE alerts SET status='RESOLVED',resolved_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),alert_id))
    return {"id":alert_id,"status":"RESOLVED"}
@app.get("/api/insights")
@app.get("/api/recommendations")
def insights(): return {"provider":"RULE_BASED_LOCAL","insights":service.insights()}
@app.get("/api/insights/{room_id}")
def room_insights(room_id: str): return {"provider":"RULE_BASED_LOCAL","insights":service.insights(room_id)}
@app.post("/api/insights/analyze")
@app.post("/api/insights/generate")
def analyze_insights(): return {"provider":"RULE_BASED_LOCAL","insights":service.insights()}
@app.post("/api/telemetry",dependencies=[Depends(require_device_token)])
async def telemetry(payload: TelemetryIn):
    try: room_state=service.telemetry(payload.model_dump())
    except ValueError as error: raise HTTPException(422,str(error)) from error
    await bus.publish("telemetry.updated",room_state); return room_state
@app.post("/api/heartbeat",dependencies=[Depends(require_device_token)])
def heartbeat(payload: HeartbeatIn):
    with db.connection() as con: updated=con.execute("UPDATE devices SET connectivity_status='ONLINE',firmware_version=COALESCE(?,firmware_version),last_seen=? WHERE id=?",(payload.firmware_version,payload.timestamp.isoformat(),payload.device_id)).rowcount
    if not updated: raise HTTPException(404,"device not found")
    return {"status":"ONLINE","device_id":payload.device_id}
@app.post("/api/device-command")
async def device_command(payload: CommandIn):
    try: response=service.command(payload.device_id,payload.command,payload.reason,payload.payload)
    except ValueError as error: raise HTTPException(409,str(error)) from error
    await bus.publish("command.created",response); return response
@app.post("/api/device-command/ack",dependencies=[Depends(require_device_token)])
async def command_ack(payload: AckIn):
    service.ack(payload.command_id,payload.status,payload.actual_state); await bus.publish("command.acknowledged",{"command_id":payload.command_id,"status":payload.status}); return {"status":"accepted"}
@app.post("/api/automation/evaluate")
async def evaluate_automation():
    executions=service.evaluate_automation()
    for execution in executions: await bus.publish("automation.executed",execution)
    return {"executions":executions}
@app.post("/api/automation/execute")
async def execute_automation(): return await evaluate_automation()
@app.get("/api/automation/executions")
def executions():
    with db.connection() as con: return {"executions":[dict(row) for row in con.execute("SELECT * FROM automation_executions ORDER BY triggered_at DESC").fetchall()]}
@app.get("/api/settings")
def get_settings(): return {"mode":settings.mode,"empty_room_delay_seconds":settings.empty_delay_seconds,"power_threshold_w":settings.power_threshold_w,"command_timeout_seconds":settings.command_timeout_seconds,"max_command_retries":settings.max_command_retries}
@app.post("/api/settings/mode")
def set_mode(payload: ModeIn):
    if payload.mode != settings.mode: raise HTTPException(409,"restart with SIMULATION_MODE set to switch providers")
    return {"mode":settings.mode}
@app.websocket("/ws/campus")
async def campus_socket(websocket: WebSocket):
    await websocket.accept(); bus.connections.add(websocket)
    try:
        await websocket.send_json({"event":"snapshot","data":service.summary()})
        while True: await websocket.receive_text()
    except WebSocketDisconnect: bus.connections.discard(websocket)
