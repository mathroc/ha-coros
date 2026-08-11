"""Data models for the Coros integration.

Field shapes adapted from cygnusb/coros-mcp (MIT license) — see the
project README's Credits section for full attribution. Converted from
that project's pydantic models to plain dataclasses here to avoid adding
pydantic as an extra Home Assistant manifest requirement.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StoredAuth:
    """Coros auth state persisted in the config entry (never the password)."""

    access_token: str
    user_id: str
    region: str
    timestamp: int  # Unix milliseconds
    mobile_access_token: str | None = None
    # Encrypted login payload, replayed to refresh the mobile token without
    # re-entering credentials. Equivalent to a long-lived credential -
    # persisted only via Home Assistant's own config entry storage.
    mobile_login_payload: dict | None = None

    def as_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "user_id": self.user_id,
            "region": self.region,
            "timestamp": self.timestamp,
            "mobile_access_token": self.mobile_access_token,
            "mobile_login_payload": self.mobile_login_payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StoredAuth:
        return cls(
            access_token=data["access_token"],
            user_id=data["user_id"],
            region=data["region"],
            timestamp=data["timestamp"],
            mobile_access_token=data.get("mobile_access_token"),
            mobile_login_payload=data.get("mobile_login_payload"),
        )


@dataclass
class HRVRecord:
    date: str
    avg_sleep_hrv: float | None = None  # nightly average RMSSD (ms)
    baseline: float | None = None  # rolling baseline
    standard_deviation: float | None = None
    interval_list: list[int] | None = None  # percentile bands


@dataclass
class DailyRecord:
    date: str
    avg_sleep_hrv: float | None = None
    baseline: float | None = None
    interval_list: list[int] | None = None
    rhr: int | None = None  # resting heart rate (bpm)
    training_load: int | None = None
    training_load_ratio: float | None = None  # acute/chronic ratio
    tired_rate: float | None = None
    ati: float | None = None  # acute training index
    cti: float | None = None  # chronic training index
    performance: int | None = None  # -1 = no data
    distance: float | None = None  # daily distance (m)
    duration: int | None = None  # daily duration (s)
    vo2max: int | None = None
    lthr: int | None = None  # lactate threshold HR (bpm)
    ltsp: int | None = None  # lactate threshold pace (s/km)
    stamina_level: float | None = None
    stamina_level_7d: float | None = None


@dataclass
class SleepPhases:
    deep_minutes: int | None = None
    light_minutes: int | None = None
    rem_minutes: int | None = None
    awake_minutes: int | None = None
    nap_minutes: int | None = None  # daytime naps


@dataclass
class SleepRecord:
    date: str
    total_duration_minutes: int | None = None
    phases: SleepPhases | None = None
    avg_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    quality_score: int | None = None  # None where Coros reports -1 (not computed)
