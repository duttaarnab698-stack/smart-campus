# Campus Pulse IoT

Run the API from the backend folder:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

For Render, use `uvicorn main:app --host 0.0.0.0 --port $PORT` as the start command.
Set `SIMULATION_MODE=true` for the current seeded demo, or set it to `false` and provide the MQTT and Supabase variables from `.env.example`.
The deployed frontend uses `https://smart-campus-sqbw.onrender.com` as its API base URL.

`SIMULATION_MODE=true` seeds a persistent SQLite database (`campus_pulse.db`) and immediately supports the presentation demo. API docs are at `http://127.0.0.1:8000/docs`.

For physical devices set `SIMULATION_MODE=false`, configure the HiveMQ TLS values in `backend/.env`, run the SQL migration in `backend/supabase_migrations/migrations/001_smart_campus.sql`, and use `smart-campus/{building}/{floor}/{room}/{telemetry|occupancy|power|appliances|command|ack|heartbeat|status}`. Device posts must include `X-Device-Token`, matching `DEVICE_AUTH_SECRET`. Commands retain desired and actual state separately; actual state is changed only by ACK.

Telemetry example:

```json
{"device_id":"ESP32-A104","occupancy":0,"temperature":26.2,"humidity":58,"voltage":230,"current":0.87,"power_w":200,"energy_kwh":12.42,"relays":{"light":true,"fan":true,"ac":false}}
```

The recommendation endpoint uses deterministic local rules and requires no cloud or paid AI service.

Safely check configured production connections (no credentials are printed):

```powershell
python -m healthcheck
```

Production CORS requires `ALLOWED_ORIGINS` to include `https://smart-campus-red.vercel.app`; localhost origins may be included for local development.
