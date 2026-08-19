import asyncio
import re

from podimo.utils import (
    async_wrap,
    generateHeaders,
    is_correct_email_address,
    randomFlyerId,
    randomHexId,
    token_key,
)


def test_random_hex_id_length_and_charset():
    value = randomHexId(16)
    assert len(value) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", value)


def test_random_flyer_id_format():
    assert re.fullmatch(r"\d{13}-\d{13}", randomFlyerId())


def test_token_key_is_deterministic():
    assert token_key("user@example.com", "hunter2") == token_key("user@example.com", "hunter2")
    assert token_key("user@example.com", "hunter2") != token_key("user@example.com", "other")


def test_is_correct_email_address():
    assert is_correct_email_address("user@example.com")
    assert not is_correct_email_address("not-an-email")


def test_generate_headers_includes_authorization_only_when_given():
    without = generateHeaders(None, "nl-NL")
    assert "authorization" not in without
    assert without["user-locale"] == "nl-NL"

    with_auth = generateHeaders("token123", "nl-NL")
    assert with_auth["authorization"] == "token123"


def test_async_wrap_runs_sync_function():
    def add(a, b):
        return a + b

    result = asyncio.run(async_wrap(add)(2, 3))
    assert result == 5
