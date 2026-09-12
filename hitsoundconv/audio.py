"""Audio loading (via ffmpeg), mixing, rendering and WAV writing."""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from .paths import ffmpeg
from .samples import SampleEvent


def load_audio(path: Path, sample_rate: int) -> np.ndarray:
    """Any format ffmpeg reads -> float32 stereo array of shape (frames, 2)."""
    cmd = [ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(sample_rate), "-"]
    data = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(data, dtype="<f4").reshape(-1, 2).astype(np.float64)


OGG_LADDER = (4, 6, 8, 10)


def _encode_ogg(path: Path, data: np.ndarray, sample_rate: int, quality: float) -> None:
    raw = np.clip(data, -1.0, 1.0).astype("<f4").tobytes()
    cmd = [ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(sample_rate), "-ac", "2",
           "-i", "-", "-c:a", "libvorbis", "-q:a", str(quality), str(path)]
    subprocess.run(cmd, input=raw, check=True, capture_output=True)


def difference_db(original: np.ndarray, encoded: np.ndarray) -> float:
    """How far the encoded file sits below the original, in dB (lower is better)."""
    frames = max(len(original), len(encoded))
    a = np.pad(original, ((0, frames - len(original)), (0, 0)))
    b = np.pad(encoded, ((0, frames - len(encoded)), (0, 0)))
    level = np.sqrt(np.mean(a ** 2))
    if level <= 0:
        return -math.inf
    return float(20 * math.log10(np.sqrt(np.mean((b - a) ** 2)) / level + 1e-12))


def write_audio(path: Path, data: np.ndarray, sample_rate: int, quality: float | None = None,
                target_db: float = -28.0, form: str = "auto") -> Path:
    """Write one generated sample and return the file that was actually written.

    form="auto" writes Vorbis .ogg when it stays under target_db and is smaller than the raw .wav -
    for very short or silent samples the ogg header alone is bigger, so those stay .wav. osu! finds
    a sample by bank, sound and index, the extension does not matter to it.
    """
    wav_path, ogg_path = path.with_suffix(".wav"), path.with_suffix(".ogg")
    if form == "wav":
        ogg_path.unlink(missing_ok=True)
        write_wav(wav_path, data, sample_rate)
        return wav_path

    qualities = [quality] if quality is not None else list(OGG_LADDER)
    for used in qualities:
        _encode_ogg(ogg_path, data, sample_rate, used)
        if quality is not None or len(data) == 0:
            break
        if difference_db(data, load_audio(ogg_path, sample_rate)) <= target_db:
            break
    else:
        ogg_path.unlink(missing_ok=True)  # no setting was close enough: keep it lossless
        write_wav(wav_path, data, sample_rate)
        return wav_path

    if form == "auto" and ogg_path.stat().st_size >= 44 + len(data) * 4:  # wav would be smaller
        ogg_path.unlink(missing_ok=True)
        write_wav(wav_path, data, sample_rate)
        return wav_path
    wav_path.unlink(missing_ok=True)
    return ogg_path


def write_wav(path: Path, data: np.ndarray, sample_rate: int) -> None:
    pcm = (np.clip(data, -1.0, 1.0) * 32767).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def silence(sample_rate: int, ms: int = 10) -> np.ndarray:
    return np.zeros((max(1, sample_rate * ms // 1000), 2))


class AudioCache:
    def __init__(self, directory: str | Path, sample_rate: int = 44100):
        self.dir = Path(directory)
        self.sr = sample_rate
        self._audio: dict[str, np.ndarray] = {}
        self._peaks: dict[tuple, float] = {}

    def load(self, name: str) -> np.ndarray:
        if name not in self._audio:
            self._audio[name] = load_audio(self.dir / name, self.sr)
        return self._audio[name]

    def mix(self, content: tuple[tuple[str, float], ...]) -> np.ndarray:
        """Sum of (file, gain) pairs, all starting at 0."""
        parts = [(self.load(name), gain) for name, gain in content]
        out = np.zeros((max((len(a) for a, _ in parts), default=0), 2))
        for a, gain in parts:
            out[:len(a)] += a * gain
        return out

    def peak(self, content: tuple[tuple[str, float], ...]) -> float:
        if not content:
            return 0.0
        if content not in self._peaks:
            mixed = self.mix(content)
            self._peaks[content] = float(np.abs(mixed).max()) if len(mixed) else 0.0
        return self._peaks[content]

    def render(self, events: list[SampleEvent], frames: int = 0) -> np.ndarray:
        """Place every event on a timeline, like the game would play them."""
        starts = [round(e.time * self.sr / 1000) for e in events]
        end = max((s + len(self.load(e.file)) for s, e in zip(starts, events)), default=0)
        out = np.zeros((max(end, frames), 2))
        for s, e in zip(starts, events):
            a = self.load(e.file)
            out[s:s + len(a)] += a * (e.volume / 100)
        return out
