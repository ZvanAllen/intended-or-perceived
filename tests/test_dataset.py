from collections import Counter
from itertools import product

import pytest

from intended_or_perceived.dataset import (
    EMOTIONS,
    STRATA,
    Clip,
    agreement_stratum,
    eligible_clips,
    plurality,
    replace_unusable,
    sample_clips,
    strip_id3,
)


def test_sample_is_seeded_balanced_and_stable_under_input_order():
    eligible = [
        Clip(
            f"synthetic-{index:04d}",
            f"actor-{index % 48}",
            f"sentence-{index % 12}",
            emotion,
            "XX",
            stratum,
        )
        for index, (emotion, stratum, _) in enumerate(
            product(EMOTIONS.values(), STRATA, range(25))
        )
    ]
    sample, pilot, transfers = sample_clips(eligible)

    assert (sample, pilot, transfers) == sample_clips(eligible[::-1])
    assert (sample, pilot) != sample_clips(eligible, seed=1)[:2]
    assert len({clip.stem for clip in sample}) == 300
    assert Counter(clip.emotion for clip in sample) == dict.fromkeys(
        EMOTIONS.values(), 50
    )
    assert Counter(clip.stratum for clip in sample) == dict.fromkeys(STRATA, 100)
    assert not transfers

    pilot_clips = [clip for clip in sample if clip.stem in pilot]
    assert Counter(clip.emotion for clip in pilot_clips) == dict.fromkeys(
        EMOTIONS.values(), 4
    )
    assert Counter(clip.stratum for clip in pilot_clips) == dict.fromkeys(STRATA, 8)


def test_consensus_thresholds_and_ties():
    assert agreement_stratum((4, 5, 1, 0, 0, 0)) == "middle"
    assert agreement_stratum((4, 4, 2, 0, 0, 0)) == "low"
    assert agreement_stratum((8, 2, 0, 0, 0, 0)) == "high"
    assert plurality((4, 4, 2, 0, 0, 0)) == ("A", "D")


def test_eligibility_requires_six_voice_ratings_and_excludes_broken_mp3s():
    votes = {
        ("1001_IEO_ANG_HI", 1): (6, 0, 0, 0, 0, 0),
        ("1001_IEO_ANG_LO", 1): (5, 0, 0, 0, 0, 0),
        ("1001_IEO_ANG_MD", 2): (6, 0, 0, 0, 0, 0),
        ("1064_IEO_DIS_MD", 1): (0, 6, 0, 0, 0, 0),
    }
    assert [clip.stem for clip in eligible_clips(votes)] == ["1001_IEO_ANG_HI"]


def test_id3_removal_preserves_the_frame_and_rejects_invalid_tags():
    frame = b"\xff\xfb\x52\xc4" + b"audio bytes"
    tag = b"ID3\x04\x00\x00\x00\x00\x01\x00" + b"x" * 128
    trailer = b"TAG" + b"x" * 125

    assert strip_id3(tag + frame + trailer) == strip_id3(frame) == frame
    with pytest.raises(ValueError, match="extends beyond"):
        strip_id3(tag[:10] + frame)


def test_silent_source_replacement_preserves_stratum_and_pilot_assignment():
    silent = Clip("1046_TIE_HAP_XX", "1046", "TIE", "Happy", "XX", "low")
    replacement = Clip("1046_WSI_HAP_XX", "1046", "WSI", "Happy", "XX", "low")
    wrong_stratum = Clip("1001_WSI_HAP_XX", "1001", "WSI", "Happy", "XX", "high")
    selected, pilot = [silent], {silent.stem}
    changed = replace_unusable([silent, replacement, wrong_stratum], selected, pilot)

    assert selected == [replacement]
    assert pilot == {replacement.stem}
    assert changed == [{"excluded": silent.stem, "replacement": replacement.stem}]
