"""Cost recorder + stima USD."""

from datetime import UTC, datetime

from media_advisor.config import Settings
from media_advisor.costs import CostRecorder, format_cost_report_telegram_html


def test_cost_recorder_openai_and_transcript() -> None:
    r = CostRecorder()
    r.record_openai_tokens("gpt-4.1-mini", 1_000_000, 500_000)
    r.record_transcript_paid("/youtube/transcript")
    r.record_transcript_free("/youtube/channel/latest")

    s = Settings(
        MEDIA_ADVISOR_OPENAI_INPUT_USD_PER_1M="0.40",
        MEDIA_ADVISOR_OPENAI_OUTPUT_USD_PER_1M="1.60",
        MEDIA_ADVISOR_TRANSCRIPT_API_USD_PER_CALL="0.01",
    )
    d = r.to_result_dict(s)
    assert d["openai"]["total_input_tokens"] == 1_000_000
    assert d["openai"]["total_output_tokens"] == 500_000
    assert d["transcript_api"]["paid_calls"] == 1
    assert d["transcript_api"]["free_calls"] == 1
    assert d["openai"]["estimated_usd"] is not None
    assert abs(d["openai"]["estimated_usd"] - 1.2) < 1e-6  # 0.4 + 0.8
    assert d["transcript_api"]["estimated_usd"] == 0.01
    assert d["estimated_total_usd"] is not None
    assert abs(d["estimated_total_usd"] - 1.21) < 1e-6


def test_format_cost_report_html_escapes() -> None:
    r = CostRecorder()
    r.record_openai_request_missing_usage("m")
    s = Settings()
    started = datetime(2026, 5, 4, 10, 0, 0, tzinfo=UTC)
    finished = datetime(2026, 5, 4, 10, 1, 30, tzinfo=UTC)
    html = format_cost_report_telegram_html(
        sync_kind="test<script>",
        started_at=started,
        finished_at=finished,
        recorder=r,
        settings=s,
        status="done",
        error='bad "quote" & amp',
    )
    assert "<script>" not in html
    assert "script" in html  # escaped


def test_cost_recorder_direct_tokens() -> None:
    r = CostRecorder()
    r.record_openai_tokens("m", 10, 20)
    d = r.to_result_dict(Settings())
    assert d["openai"]["total_input_tokens"] == 10
    assert d["openai"]["total_output_tokens"] == 20
