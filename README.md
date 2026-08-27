# Campus Pulse IoT backend

Run the API from this folder:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

`SIMULATION_MODE=true` seeds a persistent SQLite database (`campus_pulse.db`) and immediately supports the presentation demo. API docs are at `http://127.0.0.1:8000/docs`.

For physical devices set `SIMULATION_MODE=false`, configure the HiveMQ TLS values in `.env`, run the SQL migration in `supabase_migrations/migrations/001_smart_campus.sql`, and use `smart-campus/{building}/{floor}/{room}/{telemetry|occupancy|power|appliances|command|ack|heartbeat|status}`. Device posts must include `X-Device-Token`, matching `DEVICE_AUTH_SECRET`. Commands retain desired and actual state separately; actual state is changed only by ACK.

Telemetry example:

```json
{"device_id":"ESP32-A104","occupancy":0,"temperature":26.2,"humidity":58,"voltage":230,"current":0.87,"power_w":200,"energy_kwh":12.42,"relays":{"light":true,"fan":true,"ac":false}}
```

The recommendation endpoint uses deterministic local rules and requires no cloud or paid AI service.

Safely check configured production connections (no credentials are printed):

```powershell
python -m backend.healthcheck
```
