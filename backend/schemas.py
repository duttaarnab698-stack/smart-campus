from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class TelemetryIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=96)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    occupancy: int = Field(ge=0, le=500)
    temperature: float | None = Field(default=None, ge=-40, le=85)
    humidity: float | None = Field(default=None, ge=0, le=100)
    voltage: float | None = Field(default=None, ge=0, le=300)
    current: float | None = Field(default=None, ge=0, le=200)
    power_w: float = Field(ge=0, le=100000)
    energy_kwh: float = Field(default=0, ge=0)
    relays: dict[str, bool] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_recent(cls, value: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if abs((now - value).total_seconds()) > 86400:
            raise ValueError("timestamp is stale or too far in the future")
        return value


class HeartbeatIn(BaseModel):
    device_id: str
    firmware_version: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeviceRegistrationIn(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9_-]{3,96}$")
    room_id: str = Field(pattern=r"^[A-Za-z]+[0-9]+$")
    device_type: str = Field(default="ESP32", max_length=50)
    firmware_version: str | None = Field(default=None, max_length=60)


class OverrideIn(BaseModel):
    appliance: Literal["light", "fan", "ac"]
    enabled: bool
    duration_seconds: int = Field(default=900, ge=60, le=86400)


class CommandIn(BaseModel):
    device_id: str
    command: Literal["LIGHT_ON", "LIGHT_OFF", "FAN_ON", "FAN_OFF", "AC_ON", "AC_OFF", "EMERGENCY_OFF", "SYNC_STATE"]
    reason: str = Field(default="MANUAL_CONTROL", max_length=200)
    payload: dict[str, object] = Field(default_factory=dict)


class AckIn(BaseModel):
    command_id: str
    status: Literal["SUCCESS", "FAILED"]
    actual_state: dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModeIn(BaseModel):
    mode: Literal["simulation", "iot"]
