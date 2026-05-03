from media_advisor.mercato.models import MercatoTip
from media_advisor.mercato.quote_timing import (
    align_quote_to_transcript_segments,
    refined_start_sec_for_digest,
    try_align_mercato_tip,
)
from media_advisor.models.transcript import TranscriptSegment, TranscriptResponse


def test_align_quote_finds_segment_start() -> None:
    segs = [
        TranscriptSegment(text="intro bla", start=0.0, duration=2.0),
        TranscriptSegment(text="Pulisic rinnova con clausola", start=10.0, duration=4.0),
        TranscriptSegment(text="fine", start=20.0, duration=1.0),
    ]
    st, en = align_quote_to_transcript_segments(segs, "Pulisic rinnova con clausola")
    assert st == 10.0
    assert en == 14.0


def test_align_quote_fuzzy_whitespace() -> None:
    segs = [
        TranscriptSegment(text="uno due", start=1.0, duration=1.0),
        TranscriptSegment(text="tre quattro", start=2.5, duration=1.0),
    ]
    st, en = align_quote_to_transcript_segments(segs, "due tre")
    assert st is not None
    assert st <= 2.5


def test_refined_prefers_alignment_over_bad_model_time(tmp_path, monkeypatch) -> None:
    db = tmp_path / "t.sqlite"
    monkeypatch.setenv("MEDIA_ADVISOR_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    tr = TranscriptResponse(
        video_id="v1",
        transcript=[
            TranscriptSegment(text="aaa", start=0.0, duration=1.0),
            TranscriptSegment(text="notizia su Gila al Milan", start=100.0, duration=5.0),
        ],
    )
    from media_advisor.io.transcript_storage import save_transcript_to_store

    save_transcript_to_store(tmp_path, "ch1", "vid1", tr.model_dump(mode="json"))

    tip = MercatoTip(
        tip_id="x",
        video_id="vid1",
        channel_id="ch1",
        extracted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        player_name="Gila",
        from_club="Lazio",
        to_club="Milan",
        tip_text="test",
        quote_text="notizia su Gila al Milan",
        quote_start_sec=14.0,
    )
    st, src = refined_start_sec_for_digest(tmp_path, tip)
    assert src == "aligned"
    assert st == 100.0


def test_try_align_returns_none_when_quote_missing(tmp_path, monkeypatch) -> None:
    db = tmp_path / "t.sqlite"
    monkeypatch.setenv("MEDIA_ADVISOR_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    tr = TranscriptResponse(
        video_id="v1",
        transcript=[TranscriptSegment(text="solo questo", start=1.0, duration=1.0)],
    )
    from media_advisor.io.transcript_storage import save_transcript_to_store

    save_transcript_to_store(tmp_path, "ch1", "vid1", tr.model_dump(mode="json"))
    tip = MercatoTip(
        tip_id="x",
        video_id="vid1",
        channel_id="ch1",
        extracted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        player_name="X",
        from_club="A",
        to_club="B",
        tip_text="t",
        quote_text="testo che non c'è nel file",
        quote_start_sec=5.0,
    )
    st, en = try_align_mercato_tip(tmp_path, tip)
    assert st is None and en is None
