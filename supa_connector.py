import paho.mqtt.client as mqtt
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.environ["SUPABASE_URL"]
supabase_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase = create_client(supabase_url, supabase_key)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to HiveMQ: {reason_code}")
    client.subscribe("campus/rooms/+/telemetry")

def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    data = json.loads(payload)
    device_id = str(data["device_id"])
    room_id = str(data.get("room_id", device_id.removeprefix("ESP32-"))).upper()
    supabase.table("room_telemetry").insert({
        "room_id": room_id,
        "device_id": device_id,
        "occupancy": bool(data.get("occupancy", False)),
        "power_kw": float(data.get("power_kw", data.get("power_w", 0) / 1000)),
        "temperature": data.get("temperature"),
        "humidity": data.get("humidity"),
        "appliances": data.get("appliances", data.get("relays", {})),
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    print(f"Stored: [{msg.topic}] {payload}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(os.environ["MQTT_BROKER_USERNAME"], os.environ["MQTT_BROKER_PASSWORD"])
client.tls_set()
client.on_connect = on_connect
client.on_message = on_message

client.connect(os.environ["MQTT_BROKER_URL"], int(os.getenv("MQTT_BROKER_PORT", "8883")))
client.loop_forever()