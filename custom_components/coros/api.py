"""Coros Training Hub API client.

Adapted from cygnusb/coros-mcp (MIT license):
https://github.com/cygnusb/coros-mcp - including the mobile API's
AES-128-CBC scheme (key pulled from libencrypt-lib.so in the Coros
Android APK). See this repo's README Credits section for the full
attribution. This port trims the original down to what a Home Assistant
sensor integration needs (auth + read-only fetches) and drops its SQLite
cache, keyring-based token storage, and workout/schedule-management
endpoints - none of which apply here, since Home Assistant's own config
entry storage and DataUpdateCoordinator already cover that ground.

Auth mechanism: MD5-hashed password + accessToken header (web API).
HRV data comes from /dashboard/query (last 7 days of nightly RMSSD).
Sleep phase data comes from the mobile API (/coros/data/statistic/daily
on apieu.coros.com), authenticated separately via AES-encrypted credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import time

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .models import DailyRecord, HRVRecord, SleepPhases, SleepRecord, StoredAuth

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

MOBILE_LOGIN_ENDPOINT = "/coros/user/login"

# AES key hardcoded in libencrypt-lib.so (reverse-engineered from the Coros
# APK by cygnusb/coros-mcp).
_MOBILE_AES_IV = b"weloop3_2015_03#"

ENDPOINTS = {
    "login": "/account/login",
    "dashboard": "/dashboard/query",  # contains sleepHrvData (last 7 days)
    "analyse": "/analyse/query",  # last 28 days, has VO2max/fitness
    "analyse_detail": "/analyse/dayDetail/query",  # up to 24 weeks, no VO2max
    "sleep": "/coros/data/statistic/daily",  # mobile API (apieu.coros.com)
}

# Login works on the "team" host but tokens are only valid on the
# region-specific API host - always use the regional URL for all calls.
BASE_URLS = {
    "eu": "https://teameuapi.coros.com",
    "us": "https://teamapi.coros.com",
    "asia": "https://teamcnapi.coros.com",
}

# Mobile app API - used for sleep data (different host from the web API).
MOBILE_BASE_URLS = {
    "eu": "https://apieu.coros.com",
    "us": "https://api.coros.com",
    "asia": "https://apicn.coros.com",
}


class CorosAPIError(ValueError):
    """Coros API returned a non-success result code.

    Carries the raw result code so callers can distinguish auth failures
    (e.g. "1019" - token invalid) from other API errors.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _check_response(body: dict, context: str) -> None:
    if body.get("result") != "0000":
        raise CorosAPIError(
            str(body.get("result")),
            f"Coros {context} error: {body.get('message', 'unknown error')} "
            f"(result={body.get('result')})",
        )


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()  # noqa: S324 - Coros's own auth scheme, not ours to choose


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS["eu"])


def _auth_headers(auth: StoredAuth) -> dict:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "accessToken": auth.access_token,
        "yfheader": json.dumps({"userId": auth.user_id}),
    }


# ---------------------------------------------------------------------------
# Mobile API encryption (AES-128-CBC, key reverse-engineered from the APK)
# ---------------------------------------------------------------------------


def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    """Encrypt a string for the Coros mobile login API.

    Scheme reverse-engineered from libencrypt-lib.so in the Coros Android
    APK (credit: cygnusb/coros-mcp):
      1. XOR plaintext bytes with appKey bytes cyclically
      2. PKCS7-pad the XOR'd result to a 16-byte boundary
      3. AES-128-CBC encrypt: key = appKey bytes, IV = 'weloop3_2015_03#'
      4. Base64-encode the ciphertext
    """
    key = app_key.encode("ascii")
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    pad_len = 16 - (len(xored) % 16)
    padded = xored + bytes([pad_len] * pad_len)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(_MOBILE_AES_IV)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")


async def _mobile_login(email: str, password: str, region: str = "eu") -> tuple[str, dict]:
    """Authenticate against the Coros mobile API with encrypted credentials.

    Returns (access_token, login_payload_for_replay) - the payload can be
    replayed later to refresh the token without re-entering credentials.
    """
    mobile_base = MOBILE_BASE_URLS.get(region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    app_key = str(random.randint(1_000_000_000_000_000, 9_999_999_999_999_999))  # noqa: S311
    payload = {
        "account": _mobile_encrypt(email, app_key) + "\n",
        "accountType": 2,
        "appKey": app_key,
        "clientType": 1,
        "hasHrCalibrated": 0,
        "kbValidity": 0,
        "pwd": _mobile_encrypt(_md5(password), app_key) + "\n",
        # Device SIM/locale telemetry, not the account region (routing is by
        # base URL). Captured from a real login by cygnusb/coros-mcp.
        "region": "310|Europe/Berlin|US",
        "skipValidation": False,
    }
    yfheader = json.dumps(
        {
            "appVersion": 1125917087236096,
            "clientType": 1,
            "language": "en-US",
            "mobileName": "sdk_gphone64_arm64,google,Google",
            "releaseType": 1,
            "systemVersion": "13",
            "timezone": 4,
            "versionCode": "404080400",
        },
        separators=(",", ":"),
    )
    headers = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
        "yfheader": yfheader,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "mobile login")

    token = body.get("data", {}).get("accessToken")
    if not token:
        raise ValueError("No accessToken in Coros mobile login response")

    return token, payload


async def _refresh_mobile_token(auth: StoredAuth) -> bool:
    """Refresh the mobile API token by replaying the stored login payload.

    The Coros server accepts replay of the same encrypted payload - no
    nonce or anti-replay protection. Returns True and updates
    auth.mobile_access_token in place on success. Deliberately has no
    password-based fallback: if replay fails, the caller should trigger a
    Home Assistant reauth flow rather than silently re-logging in with a
    stored password (this integration never persists the password).
    """
    if not auth.mobile_login_payload:
        return False

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    headers = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=auth.mobile_login_payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()

        if body.get("result") != "0000":
            return False

        token = body.get("data", {}).get("accessToken")
        if not token:
            return False

        auth.mobile_access_token = token
        return True
    except Exception:
        _LOGGER.debug("Mobile token refresh via replay payload failed", exc_info=True)
        return False


async def _ensure_mobile_token(auth: StoredAuth) -> bool:
    """Ensure auth has a valid mobile access token, refreshing if needed."""
    if auth.mobile_access_token:
        return True
    return await _refresh_mobile_token(auth)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def login(
    email: str, password: str, region: str = "eu", *, skip_mobile: bool = False
) -> StoredAuth:
    """Authenticate against Coros (web + mobile) and return the resulting auth.

    Callers persist the result themselves (Home Assistant config entry
    storage) - this function has no side-effecting storage of its own.
    """
    pwd_hash = _md5(password)
    login_payload = {"account": email, "accountType": 2, "pwd": pwd_hash}
    json_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(region) + ENDPOINTS["login"], json=login_payload, headers=json_headers
        )
        resp.raise_for_status()
        body = resp.json()
        _check_response(body, "login")
        data = body.get("data", {})

    mobile_token = None
    mobile_payload = None
    if not skip_mobile:
        try:
            mobile_token, mobile_payload = await _mobile_login(email, password, region)
        except Exception:
            _LOGGER.debug("Mobile login failed during combined login", exc_info=True)

    return StoredAuth(
        access_token=data["accessToken"],
        user_id=data["userId"],
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_token,
        mobile_login_payload=mobile_payload,
    )


async def verify_web_token(auth: StoredAuth) -> None:
    """Confirm with Coros that the stored web access token is still accepted.

    Raises CorosAPIError on an auth failure. Does not mutate the token.
    """
    url = _base_url(auth.region) + ENDPOINTS["dashboard"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_auth_headers(auth))
        resp.raise_for_status()
        body = resp.json()
    _check_response(body, "token verification")


# ---------------------------------------------------------------------------
# HRV data (/dashboard/query -> data.summaryInfo.sleepHrvData)
# ---------------------------------------------------------------------------


async def fetch_hrv(auth: StoredAuth) -> list[HRVRecord]:
    """Fetch nightly HRV data. No date-range parameter - Coros always
    returns the last ~7 days from this endpoint."""
    url = _base_url(auth.region) + ENDPOINTS["dashboard"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_auth_headers(auth))
        resp.raise_for_status()
        body = resp.json()
    _check_response(body, "dashboard")

    hrv_data = body.get("data", {}).get("summaryInfo", {}).get("sleepHrvData", {})
    records: list[HRVRecord] = []
    for item in hrv_data.get("sleepHrvList", []):
        records.append(
            HRVRecord(
                date=str(item.get("happenDay", "")),
                avg_sleep_hrv=item.get("avgSleepHrv"),
                baseline=item.get("sleepHrvBase"),
                standard_deviation=item.get("sleepHrvSd"),
                interval_list=item.get("sleepHrvIntervalList"),
            )
        )

    today_day = hrv_data.get("happenDay")
    if today_day and not any(r.date == str(today_day) for r in records):
        records.append(
            HRVRecord(
                date=str(today_day),
                avg_sleep_hrv=hrv_data.get("avgSleepHrv"),
                baseline=hrv_data.get("sleepHrvBase"),
                standard_deviation=hrv_data.get("sleepHrvSd"),
                interval_list=hrv_data.get("sleepHrvAllIntervalList"),
            )
        )

    return sorted(records, key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Daily analysis data
# ---------------------------------------------------------------------------


def _parse_daily_record(item: dict) -> DailyRecord:
    return DailyRecord(
        date=str(item.get("happenDay", "")),
        avg_sleep_hrv=item.get("avgSleepHrv"),
        baseline=item.get("sleepHrvBase"),
        interval_list=item.get("sleepHrvIntervalList"),
        rhr=item.get("rhr"),
        training_load=item.get("trainingLoad"),
        training_load_ratio=item.get("trainingLoadRatio"),
        tired_rate=item.get("tiredRateNew"),
        ati=item.get("ati"),
        cti=item.get("cti"),
        performance=item.get("performance"),
        distance=item.get("distance"),
        duration=item.get("duration"),
        vo2max=item.get("vo2max"),
        lthr=item.get("lthr"),
        ltsp=item.get("ltsp"),
        stamina_level=item.get("staminaLevel"),
        stamina_level_7d=item.get("staminaLevel7d"),
    )


async def fetch_daily_records(auth: StoredAuth, start_day: str, end_day: str) -> list[DailyRecord]:
    """Fetch daily metrics (HRV, RHR, training load, VO2max, etc.).

    Merges two endpoints: dayDetail (long range, no VO2max) + analyse
    (last ~28 days, has VO2max/fitness fields).
    """
    headers = _auth_headers(auth)
    base = _base_url(auth.region)

    async with httpx.AsyncClient(timeout=30) as client:
        detail_resp = await client.get(
            base + ENDPOINTS["analyse_detail"],
            params={"startDay": start_day, "endDay": end_day},
            headers=headers,
        )
        analyse_resp = await client.get(base + ENDPOINTS["analyse"], headers=headers)

    detail_resp.raise_for_status()
    detail_body = detail_resp.json()
    analyse_resp.raise_for_status()
    analyse_body = analyse_resp.json()

    _check_response(detail_body, "analyse")

    records_by_date: dict[str, DailyRecord] = {}
    for item in detail_body.get("data", {}).get("dayList", []):
        rec = _parse_daily_record(item)
        records_by_date[rec.date] = rec

    if analyse_body.get("result") == "0000":
        for item in analyse_body.get("data", {}).get("t7dayList", []):
            date = str(item.get("happenDay", ""))
            if date in records_by_date:
                rec = records_by_date[date]
                if (v := item.get("vo2max")) is not None:
                    rec.vo2max = v
                if (v := item.get("lthr")) is not None:
                    rec.lthr = v
                if (v := item.get("ltsp")) is not None:
                    rec.ltsp = v
                if (v := item.get("staminaLevel")) is not None:
                    rec.stamina_level = v
                if (v := item.get("staminaLevel7d")) is not None:
                    rec.stamina_level_7d = v

    return sorted(records_by_date.values(), key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Sleep data (mobile API: apieu.coros.com/coros/data/statistic/daily)
# ---------------------------------------------------------------------------


async def fetch_sleep(auth: StoredAuth, start_day: str, end_day: str) -> list[SleepRecord]:
    """Fetch sleep stage data for a date range from the Coros mobile API.

    start_day / end_day: YYYYMMDD strings. Raises ValueError if no mobile
    token is available and the stored replay payload can't refresh one -
    the caller should treat that as "needs reauth", not a transient error.
    """
    if not await _ensure_mobile_token(auth):
        raise ValueError("No mobile API token available - reauthentication needed")

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + ENDPOINTS["sleep"]
    sleep_payload = {
        "allDeviceSleep": 1,
        "dataType": [5],
        "dataVersion": 0,
        "startTime": int(start_day),
        "endTime": int(end_day),
        "statisticType": 1,
    }

    async def _do_request(token: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                params={"accessToken": token},
                json=sleep_payload,
                headers={"Content-Type": "application/json", "accesstoken": token},
            )
            resp.raise_for_status()
            return resp.json()

    token = auth.mobile_access_token
    assert token is not None  # guaranteed by _ensure_mobile_token above
    body = await _do_request(token)

    if body.get("result") == "1019" and await _refresh_mobile_token(auth):
        body = await _do_request(auth.mobile_access_token or token)

    _check_response(body, "sleep")

    records: list[SleepRecord] = []
    for item in body.get("data", {}).get("statisticData", {}).get("dayDataList", []):
        sd = item.get("sleepData", {})
        quality = item.get("performance")
        records.append(
            SleepRecord(
                date=str(item.get("happenDay", "")),
                total_duration_minutes=sd.get("totalSleepTime"),
                phases=SleepPhases(
                    deep_minutes=sd.get("deepTime"),
                    light_minutes=sd.get("lightTime"),
                    rem_minutes=sd.get("eyeTime"),
                    awake_minutes=sd.get("wakeTime"),
                    nap_minutes=sd.get("shortSleepTime") or None,
                ),
                avg_hr=sd.get("avgHeartRate"),
                min_hr=sd.get("minHeartRate"),
                max_hr=sd.get("maxHeartRate"),
                quality_score=quality if quality != -1 else None,
            )
        )
    return sorted(records, key=lambda r: r.date)
