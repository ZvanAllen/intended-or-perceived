"""Prepare the pinned CREMA-D audio sample and verify its provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

REVISION = "1658cd342dff90010aa843eaeebd53610a08b1dc"
REPOSITORY = f"CheyneyComputerScience/CREMA-D/{REVISION}"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}"
MEDIA = f"https://media.githubusercontent.com/media/{REPOSITORY}"
SEED = 20261111
SOURCE_HASHES = {
    "SentenceFilenames.csv": "d88cb50e84bbc30b2e159cdfc25e1cf87777ad97c7c41d6ab8f75d3383b8f740",
    "finishedResponses.csv": "5eab9668f6adc2666b0179ae80553a50a5172dbc9812e582cd0ffa7bc0dd237e",
    "finishedEmoResponses.csv": "e6d44cbbf1dca05746c789f87ecdbf975e01cb142bba88266f23189a47bb4667",
    "processedResults/tabulatedVotes.csv": "774d9d759cb5caf2542758a39eca8c0f1d2777f9987ff5d5adf8066d192f377b",
    "processedResults/summaryTable.csv": "fb0e382700d32c0d9adc0c6815292215a36bcf912f2657048862c91e3bd2b317",
}
EMOTIONS = {
    "ANG": "Anger",
    "DIS": "Disgust",
    "FEA": "Fear",
    "HAP": "Happy",
    "NEU": "Neutral",
    "SAD": "Sad",
}
VOTE_LABELS = dict(zip("ADFHNS", EMOTIONS.values(), strict=True))
STRATA = ("low", "middle", "high")
MODALITIES = {1: "voice", 2: "face", 3: "av"}
EXCLUSIONS = {
    "1076_MTI_NEU_XX": "very short and no audio",
    "1076_MTI_SAD_XX": "very short and no audio",
    "1064_TIE_SAD_XX": "no duration",
    "1064_IEO_DIS_MD": "contains around one minute of multiple emotional displays",
}
QUALITY_EXCLUSIONS = {"1046_TIE_HAP_XX": "2.247 s of digital silence in the pinned MP3"}
FILENAME_PATTERN = re.compile(
    r"(\d{4})_([A-Z]{3})_(ANG|DIS|FEA|HAP|NEU|SAD)_(LO|MD|HI|XX)"
)
LFS_POINTER = re.compile(
    rb"version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize (\d+)\n"
)


@dataclass(frozen=True)
class Clip:
    stem: str
    actor: str
    sentence: str
    emotion: str
    intensity: str
    stratum: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("Public download retry loop did not return or raise")


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def cached_source(path: Path, url: str, digest: str, *, online: bool) -> bytes:
    if path.is_file():
        content = path.read_bytes()
    elif not online:
        raise FileNotFoundError(
            f"Missing {path}. Run data preparation with --download first."
        )
    else:
        content = fetch(url)
    if sha256(content) != digest:
        raise ValueError(f"SHA-256 mismatch for {path}")
    if not path.is_file():
        write_atomic(path, content)
    return content


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def vote_tuple(votes: Counter[str]) -> tuple[int, ...]:
    return tuple(votes[label] for label in VOTE_LABELS)


def plurality(votes: tuple[int, ...]) -> tuple[str, ...]:
    if not any(votes):
        return ()
    most_votes = max(votes)
    return tuple(
        label
        for label, count in zip(VOTE_LABELS, votes, strict=True)
        if count == most_votes
    )


def agreement_stratum(votes: tuple[int, ...]) -> str:
    count, total = max(votes), sum(votes)
    if total == 0:
        raise ValueError("Cannot stratify a clip without voice ratings")
    if count * 2 < total:
        return "low"
    if count * 5 >= total * 4:
        return "high"
    return "middle"


def response_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["sessionNums"], row["queryType"], row["questNum"]


def audit_ratings(metadata: Path):
    """Reconstruct the pinned tables using the authors' first-click exclusion."""
    names = {
        int(row["Stimulus_Number"]): row["Filename"]
        for row in rows(metadata / "SentenceFilenames.csv")
    }
    slow = {
        response_key(row)
        for row in rows(metadata / "finishedEmoResponses.csv")
        if row["ttr"] != "NULL" and int(row["ttr"]) > 10_000
    }
    raw_final = removed = 0
    ballots = defaultdict(Counter)
    listeners = Counter()
    for record in rows(metadata / "finishedResponses.csv"):
        raw_final += 1
        if response_key(record) in slow:
            removed += 1
            continue
        clip_num = int(record["clipNum"])
        modality = int(record["queryType"])
        label = record["respEmo"]
        if names[clip_num] != record["clipName"] or label not in VOTE_LABELS:
            raise ValueError("Unexpected retained response in pinned CREMA-D")
        ballots[clip_num, modality][label] += 1
        listeners[record["localid"], clip_num, modality] += 1

    votes = {
        (names[num], modal): vote_tuple(counts)
        for (num, modal), counts in ballots.items()
    }
    published = set()
    for record in rows(metadata / "processedResults/tabulatedVotes.csv"):
        modality, clip_num = divmod(int(record[""]), 100_000)
        key = (names[clip_num], modality)
        counts = votes[key]
        if (
            key in published
            or key[0] != record["fileName"]
            or counts != tuple(int(record[code]) for code in VOTE_LABELS)
            or sum(counts) != int(record["numResponses"])
            or not math.isclose(
                max(counts) / sum(counts), float(record["agreement"]), abs_tol=1e-8
            )
            or plurality(counts) != tuple(record["emoVote"].split(":"))
        ):
            raise ValueError(
                f"Rebuilt votes disagree with the published tabulation for {key}"
            )
        published.add(key)
    if votes.keys() != published:
        raise ValueError("Published tabulation and rebuilt response keys differ")

    summary = set()
    for record in rows(metadata / "processedResults/summaryTable.csv"):
        stem = record["FileName"]
        for modality, field in enumerate(
            ("VoiceVote", "FaceVote", "MultiModalVote"), 1
        ):
            if plurality(votes[stem, modality]) != tuple(record[field].split(":")):
                raise ValueError(
                    f"Rebuilt votes disagree with the published summary for {stem}"
                )
        summary.add(stem)
    if summary != set(names.values()):
        raise ValueError("Published summary and stimulus names differ")

    duplicates = [
        (names[num], modality, count)
        for (_, num, modality), count in listeners.items()
        if count > 1
    ]
    stats = {
        "final_responses": raw_final,
        "excluded_slow_responses": removed,
        "retained_responses": raw_final - removed,
        "clip_modality_rows": len(votes),
        "stimulus_names": len(names),
        "duplicate_listener_clip_modality": duplicates,
    }
    return votes, stats


def eligible_clips(votes: dict[tuple[str, int], tuple[int, ...]]) -> list[Clip]:
    result = []
    for (stem, modality), counts in votes.items():
        if modality != 1 or sum(counts) < 6 or stem in EXCLUSIONS:
            continue
        match = FILENAME_PATTERN.fullmatch(stem)
        if match is None:
            raise ValueError(f"Invalid CREMA-D filename {stem}")
        actor, sentence, emotion, intensity = match.groups()
        result.append(
            Clip(
                stem,
                actor,
                sentence,
                EMOTIONS[emotion],
                intensity,
                agreement_stratum(counts),
            )
        )
    return result


def spread(
    candidates: list[Clip], selected: list[Clip], generator: random.Random
) -> Clip:
    actors = Counter(clip.actor for clip in selected)
    sentences = Counter(clip.sentence for clip in selected)
    ranked = sorted(candidates, key=lambda clip: clip.stem)
    generator.shuffle(ranked)
    return min(ranked, key=lambda clip: (actors[clip.actor], sentences[clip.sentence]))


def sample_clips(
    clips: list[Clip], seed: int = SEED
) -> tuple[list[Clip], set[str], list[dict]]:
    """Rotate the 16/17 quotas and use seeded ties when spreading actors and sentences."""
    generator = random.Random(seed)
    groups = defaultdict(list)
    for clip in clips:
        groups[clip.emotion, clip.stratum].append(clip)
    selected: list[Clip] = []
    transfers = []
    for stratum_index in range(len(STRATA)):
        for emotion_index, emotion in enumerate(EMOTIONS.values()):
            stratum = STRATA[stratum_index]
            quota = 16 if (emotion_index + stratum_index) % len(STRATA) == 0 else 17
            neighbors = sorted(
                STRATA, key=lambda name: abs(STRATA.index(name) - stratum_index)
            )
            for _ in range(quota):
                available = next(
                    (name for name in neighbors if groups[emotion, name]), None
                )
                if available is None:
                    raise ValueError(f"Insufficient eligible clips for {emotion}")
                clip = spread(groups[emotion, available], selected, generator)
                groups[emotion, available].remove(clip)
                selected.append(clip)
                if available != stratum:
                    transfers.append(
                        {"emotion": emotion, "from": stratum, "to": available}
                    )

    pilot: list[Clip] = []
    for emotion_index, emotion in enumerate(EMOTIONS.values()):
        candidates = [clip for clip in selected if clip.emotion == emotion]
        for stratum_index, stratum in enumerate(STRATA):
            quota = 2 if emotion_index % len(STRATA) == stratum_index else 1
            for _ in range(quota):
                group = [
                    clip for clip in candidates if clip.stratum == stratum
                ] or candidates
                clip = spread(group, pilot, generator)
                candidates.remove(clip)
                pilot.append(clip)
    generator.shuffle(selected)
    return selected, {clip.stem for clip in pilot}, transfers


def replace_unusable(
    eligible: list[Clip], selected: list[Clip], pilot: set[str]
) -> list[dict[str, str]]:
    """Replace a failed stimulus within its stratum while preserving other assignments."""
    generator = random.Random(SEED)
    taken = {clip.stem for clip in selected}
    replacements = []
    for index, clip in enumerate(selected):
        if clip.stem not in QUALITY_EXCLUSIONS:
            continue
        remaining = [member for member in selected if member.stem != clip.stem]
        candidates = [
            member
            for member in eligible
            if member.emotion == clip.emotion
            and member.stratum == clip.stratum
            and member.stem not in taken
            and member.stem not in QUALITY_EXCLUSIONS
        ]
        replacement = spread(candidates, remaining, generator)
        selected[index] = replacement
        taken.add(replacement.stem)
        if clip.stem in pilot:
            pilot.remove(clip.stem)
            pilot.add(replacement.stem)
        replacements.append({"excluded": clip.stem, "replacement": replacement.stem})
    return replacements


def source_audio(clip: Clip, local: Path, *, online: bool) -> tuple[Path, str]:
    filename = f"{clip.stem}.mp3"
    pointer = local / "pointers" / filename
    if not pointer.is_file() and online:
        received = fetch(f"{RAW}/AudioMP3/{filename}")
        if not LFS_POINTER.fullmatch(received):
            raise ValueError(f"Invalid pinned Git LFS pointer for {filename}")
        write_atomic(pointer, received)
    match = LFS_POINTER.fullmatch(pointer.read_bytes())
    if match is None:
        raise ValueError(f"Invalid cached Git LFS pointer for {filename}")
    digest, size = match.groups()
    source = local / "originals" / filename
    payload = cached_source(
        source, f"{MEDIA}/AudioMP3/{filename}", digest.decode(), online=online
    )
    if len(payload) != int(size):
        raise ValueError(f"Git LFS size mismatch for {filename}")
    return source, digest.decode()


def ffmpeg_call(executable: str, *args: str) -> bytes:
    result = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-xerror",
            *args,
        ],
        capture_output=True,
        check=False,
        timeout=25,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def ffmpeg_executable(requested: str | None) -> str:
    if requested:
        return requested
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError as error:
        raise RuntimeError(
            "Install ffmpeg or imageio-ffmpeg==0.6.0, or pass --ffmpeg."
        ) from error
    return get_ffmpeg_exe()


def strip_id3(payload: bytes) -> bytes:
    """Remove ID3 tags while preserving the original MPEG frame bytes."""
    if payload.startswith(b"ID3"):
        if len(payload) < 10 or payload[3] not in {2, 3, 4}:
            raise ValueError("Unrecognized ID3v2 header")
        size_bytes = payload[6:10]
        if any(byte >= 128 for byte in size_bytes):
            raise ValueError("Invalid ID3v2 synchsafe tag size")
        size = sum(
            byte << shift
            for byte, shift in zip(size_bytes, (21, 14, 7, 0), strict=True)
        )
        tag_length = 10 + size
        if payload[3] == 4 and payload[5] & 0x10:
            tag_length += 10
        if tag_length >= len(payload):
            raise ValueError(f"ID3v2 tag extends beyond the audio bytes ({size})")
        payload = payload[tag_length:]
    if len(payload) >= 128 and payload[-128:-125] == b"TAG":
        payload = payload[:-128]
    if len(payload) < 2 or payload[0] != 0xFF or payload[1] & 0xE0 != 0xE0:
        raise ValueError("Expected an MP3 frame immediately after the tags")
    return payload


def decode_audio(executable: str, path: Path) -> bytes:
    return ffmpeg_call(
        executable,
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "s16le",
        "pipe:1",
    )


def prepare_audio(executable: str, source: Path, staging: Path) -> tuple[bytes, float]:
    """Strip tags and confirm decoded samples are identical to the pinned original."""
    try:
        payload = strip_id3(source.read_bytes())
        staging.write_bytes(payload)
        tags = ffmpeg_call(
            executable,
            "-i",
            str(staging),
            "-map_metadata",
            "0",
            "-fflags",
            "+bitexact",
            "-f",
            "ffmetadata",
            "pipe:1",
        )
        if tags.splitlines() != [b";FFMETADATA1"]:
            raise ValueError("Unexpected tags in the rendered stimulus")
        decoded = decode_audio(executable, staging)
        if decoded != decode_audio(executable, source):
            raise ValueError("Decoded waveform changed after removing the tags")
        duration = len(decoded) / 32_000
        if not 0.5 <= duration <= 10 or not any(decoded):
            raise ValueError(
                f"Silence or unexpected decoded duration ({duration:.3f} s)"
            )
        return payload, duration
    except ValueError as error:
        raise ValueError(f"Invalid stimulus for {source.stem}: {error}") from error
    finally:
        staging.unlink(missing_ok=True)


def clip_fields(clip: Clip, votes: dict[tuple[str, int], tuple[int, ...]]) -> dict:
    fields = {
        "filename": f"{clip.stem}.mp3",
        "intended_emotion": clip.emotion,
        "intensity": clip.intensity,
        "actor": clip.actor,
        "sentence": clip.sentence,
        "stratum": clip.stratum,
    }
    for number, modality in MODALITIES.items():
        counts = votes[clip.stem, number]
        labels = plurality(counts)
        fields.update(
            {
                f"{modality}_{code}": count
                for code, count in zip(VOTE_LABELS, counts, strict=True)
            }
        )
        fields[f"{modality}_n"] = sum(counts)
        fields[f"{modality}_agreement"] = f"{max(counts) / sum(counts):.12f}"
        fields[f"{modality}_majority"] = ":".join(
            VOTE_LABELS[label] for label in labels
        )
        fields[f"{modality}_tie"] = int(len(labels) > 1)
    return fields


def csv_bytes(records: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(records[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode()


def prepare(root: Path, executable: str | None, *, download: bool) -> None:
    local = root / "data/local"
    metadata = local / "metadata"
    for relative, digest in SOURCE_HASHES.items():
        cached_source(metadata / relative, f"{RAW}/{relative}", digest, online=download)
    votes, audit = audit_ratings(metadata)
    eligible = eligible_clips(votes)
    selected, pilot, transfers = sample_clips(eligible)
    replacements = replace_unusable(eligible, selected, pilot)

    def fetch_selected(clip: Clip) -> tuple[Path, str]:
        return source_audio(clip, local, online=download)

    with ThreadPoolExecutor(max_workers=12) as pool:
        originals = list(pool.map(fetch_selected, selected))
    if download:
        print(
            f"Verified {len(originals)} pinned public audio objects and their Git LFS hashes."
        )
        return

    ffmpeg = ffmpeg_executable(executable)
    manifest_path = root / "data/manifest.csv"
    frozen = list(rows(manifest_path)) if manifest_path.is_file() else []
    if frozen and len(frozen) != len(selected):
        raise ValueError("The existing manifest has a different number of clips")
    stimuli = local / "stimuli"
    stimuli.mkdir(parents=True, exist_ok=True)

    def render(item: tuple[int, Clip, tuple[Path, str]]) -> dict:
        index, clip, (source, source_digest) = item
        sample_id = f"clip{index:03d}"
        path = stimuli / f"{sample_id}.mp3"
        payload, duration = prepare_audio(
            ffmpeg, source, path.with_suffix(".staging.mp3")
        )
        record = {
            "sample_id": sample_id,
            **clip_fields(clip, votes),
            "pilot": int(clip.stem in pilot),
            "media_sha256": sha256(payload),
            "source_sha256": source_digest,
            "media_path": path.relative_to(root).as_posix(),
            "duration_seconds": f"{duration:.6f}",
        }
        if frozen and frozen[index - 1] != {
            key: str(value) for key, value in record.items()
        }:
            raise ValueError(
                f"Prepared record would alter the frozen manifest for {sample_id}"
            )
        write_atomic(path, payload)
        return record

    numbered = (
        (index, clip, source)
        for index, (clip, source) in enumerate(zip(selected, originals, strict=True), 1)
    )
    with ThreadPoolExecutor(max_workers=6) as pool:
        manifest = list(pool.map(render, numbered))
    audit.update(
        seed=SEED,
        exclusions=EXCLUSIONS,
        quality_exclusions=QUALITY_EXCLUSIONS,
        quality_replacements=replacements,
        eligible=len(eligible),
        sample=len(manifest),
        pilot=len(pilot),
        quota_transfers=transfers,
        sample_actors=len({clip.actor for clip in selected}),
        sample_sentences=len({clip.sentence for clip in selected}),
        pilot_actors=len({clip.actor for clip in selected if clip.stem in pilot}),
        pilot_sentences=len({clip.sentence for clip in selected if clip.stem in pilot}),
        sample_voice_ties=sum(int(record["voice_tie"]) for record in manifest),
        pilot_voice_ties=sum(
            int(record["voice_tie"]) for record in manifest if record["pilot"]
        ),
        min_duration_seconds=min(
            float(record["duration_seconds"]) for record in manifest
        ),
        max_duration_seconds=max(
            float(record["duration_seconds"]) for record in manifest
        ),
        manifest_sha256=sha256(csv_bytes(manifest)),
    )
    if frozen and manifest_path.read_bytes() != csv_bytes(manifest):
        raise ValueError("Prepared CSV bytes differ from the frozen manifest")
    if not frozen:
        write_atomic(manifest_path, csv_bytes(manifest))
    write_atomic(local / "audit.json", json.dumps(audit, indent=2).encode() + b"\n")
    print(json.dumps(audit, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Workspace containing data/."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Fetch and hash public source files only.",
    )
    parser.add_argument(
        "--ffmpeg", help="Path to ffmpeg for offline manifest and media preparation."
    )
    arguments = parser.parse_args()
    prepare(arguments.root.resolve(), arguments.ffmpeg, download=arguments.download)


if __name__ == "__main__":
    main()
