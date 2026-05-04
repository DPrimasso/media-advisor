import pytest
from pydantic import ValidationError

from media_advisor.config import Settings


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("", None),
        ("   ", None),
        ("123", 123),
    ],
)
def test_settings_parses_telegram_thread_id(raw_value: str, expected: int | None) -> None:
    settings = Settings(TELEGRAM_THREAD_ID=raw_value)
    assert settings.telegram_thread_id == expected


def test_settings_rejects_invalid_telegram_thread_id() -> None:
    with pytest.raises(ValidationError):
        Settings(TELEGRAM_THREAD_ID="abc")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("", None),
        ("   ", None),
        ("123", 123),
    ],
)
def test_settings_parses_telegram_personal_thread_id(raw_value: str, expected: int | None) -> None:
    settings = Settings(TELEGRAM_PERSONAL_THREAD_ID=raw_value)
    assert settings.telegram_personal_thread_id == expected


def test_settings_pricing_empty_string_becomes_none() -> None:
    s = Settings(
        MEDIA_ADVISOR_OPENAI_INPUT_USD_PER_1M="",
        MEDIA_ADVISOR_TRANSCRIPT_API_USD_PER_CALL="",
    )
    assert s.openai_input_usd_per_1m is None
    assert s.transcript_api_usd_per_paid_call is None


def test_settings_pricing_coerces_float() -> None:
    s = Settings(
        MEDIA_ADVISOR_OPENAI_INPUT_USD_PER_1M="0.15",
        MEDIA_ADVISOR_OPENAI_OUTPUT_USD_PER_1M="0.60",
        MEDIA_ADVISOR_TRANSCRIPT_API_USD_PER_CALL="0.005",
    )
    assert s.openai_input_usd_per_1m == 0.15
    assert s.openai_output_usd_per_1m == 0.60
    assert s.transcript_api_usd_per_paid_call == 0.005
