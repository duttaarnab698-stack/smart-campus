"""Central, environment-only configuration. Secrets never reach frontend code or logs."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import find_dotenv, load_dotenv
    # Search upward so a private workspace-root .env is discovered; .env.example is never loaded.
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:  # Deployment platforms normally inject environment variables directly.
    pass


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", os.getenv("APP_ENVIRONMENT", "development"))
    database_path: str = os.getenv("CAMPUS_DATABASE_PATH", "campus_pulse.db")
    simulation_mode: bool = env_bool("SIMULATION_MODE", True)
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    supabase_service_role_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_SECRET_KEY"))
    mqtt_broker_url: str = os.getenv("MQTT_BROKER_URL", "")
    mqtt_broker_port: int = int(os.getenv("MQTT_BROKER_PORT", "8883"))
    mqtt_username: str | None = os.getenv("MQTT_BROKER_USERNAME")
    mqtt_password: str | None = os.getenv("MQTT_BROKER_PASSWORD")
    mqtt_tls_enabled: bool = env_bool("MQTT_TLS_ENABLED", True)
    device_auth_secret: str = os.getenv("DEVICE_AUTH_SECRET", "")
    allowed_origins: tuple[str, ...] = tuple(value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",") if value.strip())
    empty_delay_seconds: int = int(os.getenv("EMPTY_ROOM_SHUTDOWN_DELAY_SECONDS", os.getenv("EMPTY_SHUTDOWN_DELAY_SECONDS", "5")))
    power_threshold_w: float = float(os.getenv("EMPTY_ROOM_POWER_THRESHOLD_KW", "0.05")) * 1000
    telemetry_freshness_seconds: int = int(os.getenv("TELEMETRY_FRESHNESS_SECONDS", "60"))
    command_timeout_seconds: int = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "5"))
    max_command_retries: int = int(os.getenv("MAX_COMMAND_RETRIES", "3"))
    electricity_rate_per_kwh: float = float(os.getenv("ELECTRICITY_RATE_PER_KWH", "8"))
    co2_kg_per_kwh: float = float(os.getenv("CO2_KG_PER_KWH", "0.417"))

    @property
    def mode(self) -> str:
        return "simulation" if self.simulation_mode else "iot"


settings = Settings()
