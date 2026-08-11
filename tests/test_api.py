"""Tests for the ported Coros API client - pure logic only, no live network.

Auth/fetch logic adapted from cygnusb/coros-mcp (MIT) - see README Credits.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from custom_components.coros import api
from custom_components.coros.models import StoredAuth


def test_mobile_encrypt_round_trips():
    """Decrypting our own ciphertext with the documented scheme recovers the
    original plaintext - verifies the XOR+AES composition is wired correctly,
    since there's no live server to check the real output against."""
    app_key = "1234567890123456"  # 16 ASCII chars, matches real appKey format
    plaintext = "someone@example.com"

    ciphertext_b64 = api._mobile_encrypt(plaintext, app_key)
    ciphertext = base64.b64decode(ciphertext_b64)

    key = app_key.encode("ascii")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(api._MOBILE_AES_IV)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = padded[-1]
    xored = padded[:-pad_len]
    recovered = bytes(b ^ key[i % len(key)] for i, b in enumerate(xored)).decode("utf-8")

    assert recovered == plaintext


def test_mobile_encrypt_output_is_deterministic_per_key():
    app_key = "1234567890123456"
    assert api._mobile_encrypt("same input", app_key) == api._mobile_encrypt("same input", app_key)


def test_check_response_raises_on_error_code():
    with pytest.raises(api.CorosAPIError) as exc_info:
        api._check_response({"result": "1019", "message": "Access token is invalid"}, "test")
    assert exc_info.value.code == "1019"


def test_check_response_passes_on_success():
    api._check_response({"result": "0000"}, "test")  # should not raise


def test_parse_daily_record_maps_fields():
    item = {
        "happenDay": "20260810",
        "rhr": 48,
        "trainingLoad": 120,
        "vo2max": 52,
        "staminaLevel": 87.5,
    }
    record = api._parse_daily_record(item)
    assert record.date == "20260810"
    assert record.rhr == 48
    assert record.training_load == 120
    assert record.vo2max == 52
    assert record.stamina_level == 87.5


def test_parse_daily_record_handles_missing_fields():
    record = api._parse_daily_record({"happenDay": "20260810"})
    assert record.date == "20260810"
    assert record.rhr is None
    assert record.vo2max is None


def test_auth_headers_include_access_token_and_user_id():
    auth = StoredAuth(access_token="tok123", user_id="u1", region="eu", timestamp=0)
    headers = api._auth_headers(auth)
    assert headers["accessToken"] == "tok123"
    assert '"userId": "u1"' in headers["yfheader"] or '"userId":"u1"' in headers["yfheader"]


def test_base_url_falls_back_to_eu_for_unknown_region():
    assert api._base_url("nonexistent") == api.BASE_URLS["eu"]


def test_base_url_known_regions():
    assert api._base_url("us") == "https://teamapi.coros.com"
    assert api._base_url("eu") == "https://teameuapi.coros.com"


@pytest.mark.asyncio
async def test_ensure_mobile_token_returns_true_if_already_present():
    auth = StoredAuth(
        access_token="t", user_id="u", region="eu", timestamp=0, mobile_access_token="already-set"
    )
    assert await api._ensure_mobile_token(auth) is True


@pytest.mark.asyncio
async def test_ensure_mobile_token_returns_false_with_no_token_and_no_payload():
    auth = StoredAuth(access_token="t", user_id="u", region="eu", timestamp=0)
    assert await api._ensure_mobile_token(auth) is False
