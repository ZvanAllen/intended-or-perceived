"""Audit frozen MP3 levels and prepare separate peak-adjusted pilot WAVs."""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import struct
import sys
import unicodedata
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from .dataset import (
    csv_bytes,
    ffmpeg_call,
    ffmpeg_executable,
    rows,
    sha256,
    write_atomic,
)

# CREMA-D README, pinned dataset revision: filename labeling conventions.
SENTENCES = {
    "IEO": "It's eleven o'clock.",
    "TIE": "That is exactly what happened.",
    "IOM": "I'm on my way to the meeting.",
    "IWW": "I wonder what this is about.",
    "TAI": "The airplane is almost full.",
    "MTI": "Maybe tomorrow it will be cold.",
    "IWL": "I would like a new alarm clock.",
    "ITH": "I think I have a doctor's appointment.",
    "DFA": "Don't forget a jacket.",
    "ITS": "I think I've seen this before.",
    "TSI": "The surface is slick.",
    "WSI": "We'll stop in a couple of minutes.",
}
TARGET_PEAK_DBFS = -1.0
PCM16_FULL_SCALE = 32768
AU_HEADER = struct.Struct(">4s5I")


def normalized_words(text: str) -> str:
    """Ignore case, punctuation and spacing when comparing transcriptions."""
    unpunctuated = "".join(
        char for char in text.lower() if not unicodedata.category(char).startswith("P")
    )
    return " ".join(unpunctuated.split())


def mono_au_pcm(payload: bytes) -> tuple[int, array]:
    """Read float32 samples and native rate from ffmpeg's AU pipe output."""
    if len(payload) < AU_HEADER.size:
        raise ValueError("Missing float PCM header")
    magic, offset, length, encoding, rate, channels = AU_HEADER.unpack_from(payload)
    frames = payload[offset:]
    if (
        magic != b".snd"
        or offset < AU_HEADER.size
        or length not in {len(frames), 0xFFFFFFFF}
        or encoding != 6
        or rate == 0
        or channels != 1
        or not frames
        or len(frames) % 4
    ):
        raise ValueError("Expected nonempty native-rate mono float32 PCM")
    samples = array("f")
    samples.frombytes(frames)
    if sys.byteorder == "little":
        samples.byteswap()
    return rate, samples


def decode_native(executable: str, mp3: Path) -> tuple[int, array]:
    payload = ffmpeg_call(
        executable,
        "-f",
        "mp3",
        "-i",
        str(mp3),
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-c:a",
        "pcm_f32be",
        "-f",
        "au",
        "pipe:1",
    )
    return mono_au_pcm(payload)


def dbfs(amplitude: float) -> float:
    return 20 * math.log10(amplitude)


def source_levels(samples: array) -> tuple[float, float]:
    peak = max(map(abs, samples), default=0.0)
    energy = math.fsum(sample**2 for sample in samples)
    if not math.isfinite(energy) or energy <= 0:
        raise ValueError("Expected finite, nonsilent audio")
    return math.sqrt(energy / len(samples)), peak


def peak_adjusted_wav(
    samples: array, rate: int, peak: float
) -> tuple[bytes, float, float]:
    """Apply one scalar, then quantize to signed 16-bit little-endian PCM."""
    gain = 10 ** (TARGET_PEAK_DBFS / 20) / peak
    frames = array("h", (round(sample * gain * PCM16_FULL_SCALE) for sample in samples))
    adjusted_peak = max(map(abs, frames)) / PCM16_FULL_SCALE
    if sys.byteorder == "big":
        frames.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames.tobytes())
    return output.getvalue(), gain, adjusted_peak


def prepare(root: Path, executable: str | None = None) -> dict:
    manifest = root / "data/manifest.csv"
    destination = root / "data/local/diagnostic"
    ffmpeg = ffmpeg_executable(executable)
    manifest_hash = sha256(manifest.read_bytes())
    clips = list(rows(manifest))
    sample_ids = [clip["sample_id"] for clip in clips]
    pilot_ids = {clip["sample_id"] for clip in clips if clip["pilot"] == "1"}
    if (
        len(clips) != 300
        or len(set(sample_ids)) != len(clips)
        or any(not re.fullmatch(r"clip\d{3}", sample_id) for sample_id in sample_ids)
        or len(pilot_ids) != 24
    ):
        raise ValueError(
            "Expected a frozen 300-clip manifest with 24 pilot assignments"
        )

    def examine(clip: dict[str, str]) -> tuple[dict, tuple[dict, bytes] | None]:
        sample_id = clip["sample_id"]
        stimulus = root / clip["media_path"]
        if stimulus != root / "data/local/stimuli" / f"{sample_id}.mp3":
            raise ValueError(f"Unexpected frozen MP3 path for {sample_id}")
        if sha256(stimulus.read_bytes()) != clip["media_sha256"]:
            raise ValueError(f"Frozen MP3 hash mismatch for {sample_id}")
        rate, samples = decode_native(ffmpeg, stimulus)
        rms, peak = source_levels(samples)
        levels = {
            "sample_id": sample_id,
            "native_sample_rate": rate,
            "duration_seconds": len(samples) / rate,
            "source_rms_dbfs": dbfs(rms),
            "source_peak_dbfs": dbfs(peak),
            "source_peak": peak,
        }
        if sample_id not in pilot_ids:
            return levels, None
        wav_bytes, gain, adjusted_peak = peak_adjusted_wav(samples, rate, peak)
        media_path = destination / f"{sample_id}.wav"
        record = {
            "sample_id": sample_id,
            "media_path": media_path.relative_to(root).as_posix(),
            "media_sha256": sha256(wav_bytes),
            "source_media_sha256": clip["media_sha256"],
            **levels,
            "applied_gain_db": dbfs(gain),
            "linear_gain": gain,
            "adjusted_peak_dbfs": dbfs(adjusted_peak),
            "expected_words": SENTENCES[clip["sentence"]],
        }
        return levels, (record, wav_bytes)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(examine, clips))
    source = [levels for levels, _ in results]
    diagnostic = [output for _, output in results if output is not None]
    maximum = max(source, key=lambda row: row["source_peak"])
    rms_values = [row["source_rms_dbfs"] for row in source]
    stats = {
        "source_manifest_sha256": manifest_hash,
        "clips": len(source),
        "pilot_clips": len(diagnostic),
        "source_rms_min_dbfs": min(rms_values),
        "source_rms_median_dbfs": median(rms_values),
        "source_rms_max_dbfs": max(rms_values),
        "source_peak_max": maximum["source_peak"],
        "source_peak_max_dbfs": maximum["source_peak_dbfs"],
        "source_peak_max_sample_id": maximum["sample_id"],
        "target_peak_dbfs": TARGET_PEAK_DBFS,
    }
    for record, wav_bytes in diagnostic:
        write_atomic(root / record["media_path"], wav_bytes)
    write_atomic(destination / "source_levels.csv", csv_bytes(source))
    write_atomic(
        destination / "levels.json", (json.dumps(stats, indent=2) + "\n").encode()
    )
    write_atomic(
        destination / "manifest.csv", csv_bytes([record for record, _ in diagnostic])
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ffmpeg")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root.resolve(), args.ffmpeg), indent=2))


if __name__ == "__main__":
    main()
