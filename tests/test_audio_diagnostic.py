import io
import struct
import wave
from array import array

import pytest

from intended_or_perceived.audio_diagnostic import (
    PCM16_FULL_SCALE,
    dbfs,
    mono_au_pcm,
    normalized_words,
    peak_adjusted_wav,
    source_levels,
)


def test_transcription_normalization_ignores_punctuation_case_and_spacing():
    assert normalized_words("  I THINK I’ve seen this before!\n") == normalized_words(
        "I think I've seen this before."
    )
    assert normalized_words("That is exactly what happened.") != normalized_words(
        "That's exactly what happened."
    )


def test_float_pcm_preserves_native_rate_and_rejects_stereo():
    frames = struct.pack(">4f", 0.0, -0.1, 0.05, 0.1)
    mono = struct.pack(">4s5I", b".snd", 24, 0xFFFFFFFF, 6, 44100, 1) + frames
    rate, samples = mono_au_pcm(mono)
    assert rate == 44100
    assert samples.tolist() == pytest.approx([0.0, -0.1, 0.05, 0.1])
    assert source_levels(samples) == pytest.approx((0.075, 0.1))

    stereo = struct.pack(">4s5I", b".snd", 24, 0xFFFFFFFF, 6, 44100, 2) + frames
    with pytest.raises(ValueError, match="mono float32"):
        mono_au_pcm(stereo)
    with pytest.raises(ValueError, match="nonsilent"):
        source_levels(array("f", [0.0] * 4))


def test_adjustment_applies_one_gain_without_resampling_or_trimming():
    samples = array("f", [0, -0.125, 0.25, 0.0625, 0])
    _, peak = source_levels(samples)
    data, gain, achieved_peak = peak_adjusted_wav(samples, 22050, peak)
    assert dbfs(achieved_peak) == pytest.approx(-1.0, abs=0.0003)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22050
        assert wav.getnframes() == len(samples)
        assert struct.unpack("<5h", wav.readframes(wav.getnframes())) == tuple(
            round(sample * gain * PCM16_FULL_SCALE) for sample in samples
        )
