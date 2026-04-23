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
