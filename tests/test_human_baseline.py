from pathlib import Path

import pytest

from intended_or_perceived import human_baseline
from intended_or_perceived.dataset import sha256
from intended_or_perceived.human_baseline import listener_baselines


@pytest.fixture
def voice_clip(tmp_path, monkeypatch):
    sources = {
        "SentenceFilenames.csv": "Stimulus_Number,Filename\n1,1001_IEO_ANG_XX\n",
        "finishedEmoResponses.csv": (
            "sessionNums,queryType,questNum,ttr\n"
            "1,1,1,NULL\n2,1,1,10000\n6,1,1,10001\n2,2,1,15000\n"
        ),
        "finishedResponses.csv": (
            "queryType,sessionNums,questNum,clipNum,clipName,localid,respEmo\n"
            "1,1,1,1,1001_IEO_ANG_XX,listener-1,A\n"
            "1,1,2,1,1001_IEO_ANG_XX,listener-1,A\n"
            "1,2,1,1,1001_IEO_ANG_XX,listener-2,A\n"
            "1,3,1,1,1001_IEO_ANG_XX,listener-3,D\n"
            "1,4,1,1,1001_IEO_ANG_XX,listener-4,D\n"
            "1,5,1,1,1001_IEO_ANG_XX,listener-5,N\n"
            "1,6,1,1,1001_IEO_ANG_XX,listener-6,S\n"
            "2,7,1,1,1001_IEO_ANG_XX,listener-7,H\n"
        ),
        "processedResults/tabulatedVotes.csv": (
            ",fileName,A,D,F,H,N,S,numResponses\n"
            "100001,1001_IEO_ANG_XX,3,2,0,0,1,0,6\n"
            "200001,1001_IEO_ANG_XX,0,0,0,1,0,0,1\n"
        ),
    }
    hashes = {}
    for source, text in sources.items():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        hashes[source] = sha256(path.read_bytes())
    monkeypatch.setattr(human_baseline, "SOURCE_HASHES", hashes)
    return tmp_path, {
        "sample_id": "clip001",
        "filename": "1001_IEO_ANG_XX.mp3",
        "actor": "1001",
        "sentence": "IEO",
        "intended_emotion": "Anger",
        "intensity": "XX",
        "stratum": "middle",
        "voice_A": "3",
        "voice_D": "2",
        "voice_F": "0",
        "voice_H": "0",
        "voice_N": "1",
        "voice_S": "0",
        "voice_n": "6",
        "voice_agreement": "0.5",
        "voice_majority": "Anger",
        "voice_tie": "0",
    }


def test_leave_out_all_responses_by_rater_and_credit_ties(voice_clip):
    metadata, row = voice_clip
    baseline = listener_baselines([row], metadata)

    # Intended: listeners 1 and 2 match. Perceived: listener 1's two Anger
    # votes are both held out, leaving Disgust as the plurality. Listener 2
    # matches the remaining Anger/Disgust tie. Listeners 3–5 match neither.
    assert baseline == {
        "clip001": {
            "listener_intended": pytest.approx(2 / 5),
            "listener_perceived": pytest.approx(1 / 5),
            "listener_count": 5,
            "listener_response_count": 6,
        }
    }


def test_manifest_join_requires_exact_counts_and_unique_stimuli(voice_clip):
    metadata, row = voice_clip
    with pytest.raises(ValueError, match="Voice votes disagree"):
        listener_baselines([dict(row, voice_A="2", voice_D="3")], metadata)
    with pytest.raises(ValueError, match="Inconsistent manifest identity"):
        listener_baselines([row, dict(row, sample_id="clip002")], metadata)


def test_metadata_must_match_pinned_hash(voice_clip):
    metadata, row = voice_clip
    source: Path = metadata / "finishedResponses.csv"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        listener_baselines([row], metadata)
