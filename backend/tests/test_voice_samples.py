import io
import wave
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.voice_samples_routes import validate_wav, SampleEdit, edit_sample, owned
from app.voice.scheduling import SpeechScheduler, SpeechBusy


def wav(frames=16000, rate=16000, channels=1):
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * frames * channels)
    return result.getvalue()


@pytest.mark.parametrize("audio", [b"invalid", wav(100), wav(240001), wav(rate=8000), wav(channels=2), wav()[:-10]],
                         ids=["invalid", "short", "long", "rate", "stereo", "truncated"])
def test_training_rejects_short_long_wrong_format_and_truncated_audio(audio):
    with pytest.raises(HTTPException) as error:
        validate_wav(audio)
    assert error.value.status_code == 400


def test_training_accepts_boundary_durations():
    assert validate_wav(wav()) == 1000
    assert validate_wav(wav(240000)) == 15000


def test_other_owner_gets_no_sample_or_audio():
    class Cursor:
        def execute(self, sql, args):
            assert "sample_id=%s AND user_id=%s" in sql
            assert args == ("sample", "other")
        def fetchone(self): return None
    with pytest.raises(HTTPException) as error:
        owned(Cursor(), "sample", "other", audio=True)
    assert error.value.status_code == 404


def test_blank_confirmation_cannot_be_saved():
    with patch("app.api.voice_samples_routes.get_connection_pool", side_effect=AssertionError("No DB needed")):
        with pytest.raises(HTTPException) as error:
            edit_sample("sample", SampleEdit(transcript="  ", status="confirmed", revision=1), {"user_id": "u"})
    assert error.value.status_code == 400


def test_optional_sample_does_not_queue_ahead_of_calls_and_releases_after_error():
    scheduler = SpeechScheduler()
    with scheduler.slot("caller", False):
        with pytest.raises(SpeechBusy):
            with scheduler.sample_slot("sample"): pass
        assert not scheduler.drafts and not scheduler.finals
    with pytest.raises(RuntimeError):
        with scheduler.sample_slot("sample"):
            raise RuntimeError("Decoder failed")
    with scheduler.slot("caller", False):
        assert scheduler.active.user == "caller"
    # Even a not-yet-running queued call prevents optional work.
    scheduler.finals["waiting"] = object()
    with pytest.raises(SpeechBusy):
        with scheduler.sample_slot("sample"): pass
