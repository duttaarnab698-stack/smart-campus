"""Optional server-side Supabase mirror. It is never imported by frontend code."""
from __future__ import annotations
from typing import Any


class SupabaseStore:
    def __init__(self, url: str | None, service_role_key: str | None) -> None:
        self.client: Any | None = None
        self.last_error: str | None = None
        if url and service_role_key:
            try:
                from supabase import create_client
                self.client = create_client(url, service_role_key)
            except Exception:
                # SQLite remains available in development if the hosted database is temporarily unreachable.
                self.client = None

    @property
    def configured(self) -> bool:
        return self.client is not None

    def health(self) -> str:
        if not self.client:
            return "NOT_CONFIGURED"
        try:
            self.client.table("rooms").select("id").limit(1).execute()
            self.last_error = None
            return "CONNECTED"
        except Exception as error:
            self.last_error = type(error).__name__
            return "UNAVAILABLE"

    def mirror_telemetry(self, room_id: str, device_id: str, occupancy: bool, power_w: float, temperature: float | None, humidity: float | None, appliances: dict[str, bool], timestamp: str) -> None:
        if not self.client: return
        try:
            self.client.table("room_telemetry").insert({"room_id":room_id,"device_id":device_id,"occupancy":occupancy,"power_kw":power_w/1000,"temperature":temperature,"humidity":humidity,"appliances":appliances,"recorded_at":timestamp}).execute()
        except Exception as error:
            self.last_error = type(error).__name__
            return
