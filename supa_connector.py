import paho.mqtt.client as mqtt
from supabase import create_client
from datetime import datetime

# Supabase setup
supabase = create_client(
    "https://kbpezpjnzuelrwemdabx.supabase.co",
    "sb_publishable_j19qPqyIf1RFyJrHwFOybw_3N8ymftH"
)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to HiveMQ: {reason_code}")
    client.subscribe("campus/rooms/+/telemetry")

def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    supabase.table("mqtt_messages").insert({
        "topic": msg.topic,
        "payload": payload,
        "received_at": datetime.utcnow().isoformat()
    }).execute()
    print(f"Stored: [{msg.topic}] {payload}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set("campus_pulse", "sourik@2006")
client.tls_set()
client.on_connect = on_connect
client.on_message = on_message

client.connect("26d698b9c40043fea201ceeeca118b35.s1.eu.hivemq.cloud", 8883)
client.loop_forever()