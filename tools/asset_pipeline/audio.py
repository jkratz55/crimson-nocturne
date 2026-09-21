"""
Procedural gothic soundtrack + sound effects.

Music: "Nocturne of the Crimson Hall" — an original piece in D harmonic
minor at 138 BPM in the vein of 90s gothic action-game scores:
harpsichord lead, harpsichord arpeggios, church-organ pad, driving
octave bass in eighths, and a light rock kit, all sent through a long
cathedral reverb. The reverb tail is wrapped back onto the start of the
buffer so the OGG loops seamlessly.

SFX: short synthesized one-shots written as 16-bit WAV (best for
low-latency playback in Godot).
"""
from __future__ import annotations

import os
import subprocess
import wave

import numpy as np
from scipy.signal import fftconvolve, lfilter

from common import MUSIC, SFX

SR = 44100
RNG = np.random.default_rng(7)

NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name: str) -> int:
    """'C#5' / 'Bb4' -> MIDI note number."""
    letter, rest = name[0], name[1:]
    acc = 0
    if rest[0] in "#b":
        acc = 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + NOTE_INDEX[letter] + acc


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def one_pole_lp(x: np.ndarray, cutoff: float) -> np.ndarray:
    a = np.exp(-2 * np.pi * cutoff / SR)
    return lfilter([1 - a], [1, -a], x)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
def harpsichord(freq: float, dur: float) -> np.ndarray:
    t = t_axis(dur + 0.6)
    sig = np.zeros_like(t)
    for n in range(1, 12):
        sig += (1.0 / n ** 0.8) * np.sin(2 * np.pi * freq * n * (1 + 0.0004 * n) * t) * np.exp(-t * (2.2 + n * 1.1))
    pluck = RNG.standard_normal(len(t)) * np.exp(-t * 180) * 0.35
    sig += one_pole_lp(pluck, 4000)
    rel = np.clip((dur + 0.6 - t) / 0.08, 0, 1)
    return sig * rel * 0.32


def organ(freq: float, dur: float) -> np.ndarray:
    t = t_axis(dur)
    vib = 1 + 0.003 * np.sin(2 * np.pi * 5.3 * t)
    sig = np.zeros_like(t)
    for mult, amp in ((0.5, 0.5), (1, 1.0), (2, 0.55), (3, 0.35), (4, 0.25), (6, 0.12), (8, 0.08)):
        sig += amp * np.sin(2 * np.pi * freq * mult * vib * t)
    env = np.minimum(1, t / 0.04) * np.minimum(1, (dur - t) / 0.12)
    return sig * np.clip(env, 0, 1) * 0.06


def bass(freq: float, dur: float) -> np.ndarray:
    t = t_axis(dur)
    phase = (freq * t) % 1.0
    sig = np.where(phase < 0.3, 1.0, -1.0) + 0.6 * (2 * phase - 1)
    sig = one_pole_lp(sig, 900)
    env = np.exp(-t * 5) * 0.8 + 0.2
    env *= np.clip((dur - t) / 0.02, 0, 1)
    return sig * env * 0.22


def kick() -> np.ndarray:
    t = t_axis(0.35)
    f = 50 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * 0.55


def snare() -> np.ndarray:
    t = t_axis(0.25)
    noise = RNG.standard_normal(len(t))
    noise = noise - one_pole_lp(noise, 1200)
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
    return (noise * np.exp(-t * 18) * 0.35 + tone * 0.3)


def hat() -> np.ndarray:
    t = t_axis(0.06)
    noise = RNG.standard_normal(len(t))
    noise = noise - one_pole_lp(noise, 7000)
    return noise * np.exp(-t * 70) * 0.12


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------
BPM = 138
BEAT = 60 / BPM
BAR = 4 * BEAT

CHORDS = {
    "Dm": (50, (0, 3, 7)), "Bb": (46, (0, 4, 7)), "C": (48, (0, 4, 7)), "A": (45, (0, 4, 7)),
    "A7": (45, (0, 4, 7, 10)), "Gm": (43, (0, 3, 7)), "Edim": (52, (0, 3, 6)),
}

INTRO = ["Dm", "Bb", "C", "A"]
PROG_A = ["Dm", "Bb", "C", "A", "Dm", "Gm", "A", "A7"]
PROG_B = ["Gm", "Dm", "Bb", "A", "Gm", "Dm", "Edim", "A"]

MEL_A = [
    [("A4", 1), ("D5", .5), ("E5", .5), ("F5", 1), ("E5", .5), ("D5", .5)],
    [("F5", 1.5), ("E5", .5), ("D5", 1), ("Bb4", 1)],
    [("C5", 1), ("E5", 1), ("G5", 1), ("F5", .5), ("E5", .5)],
    [("E5", 2), ("C#5", 1), ("A4", 1)],
    [("D5", .5), ("F5", .5), ("A5", 1), ("G5", .5), ("F5", .5), ("E5", .5), ("F5", .5)],
    [("G5", 1.5), ("F5", .5), ("D5", 1), ("Bb4", 1)],
    [("C#5", 1), ("E5", 1), ("A5", 1), ("G5", .5), ("E5", .5)],
    [("F5", .5), ("E5", .5), ("D5", .5), ("C#5", .5), ("E5", 2)],
]
MEL_B = [
    [("Bb5", 1), ("A5", .5), ("G5", .5), ("D5", 1), ("G5", 1)],
    [("A5", 1.5), ("F5", .5), ("D5", 2)],
    [("D5", .5), ("F5", .5), ("Bb5", 1), ("A5", .5), ("G5", .5), ("F5", 1)],
    [("E5", 1), ("C#5", .5), ("E5", .5), ("A5", 2)],
    [("G5", .5), ("A5", .5), ("Bb5", 1), ("D6", 1), ("Bb5", 1)],
    [("A5", 1), ("F5", 1), ("D5", 1), ("F5", 1)],
    [("E5", 1), ("G5", 1), ("Bb5", 1), ("C#6", 1)],
    [("A5", 2), ("E5", 1), ("C#5", 1)],
]


def place(buf: np.ndarray, sig: np.ndarray, start: float, pan: float) -> None:
    """Mix a mono signal into the stereo buffer (pan -1..1, equal power)."""
    i = int(start * SR)
    j = min(len(buf), i + len(sig))
    if i >= len(buf):
        return
    l_gain = np.cos((pan + 1) * np.pi / 4)
    r_gain = np.sin((pan + 1) * np.pi / 4)
    buf[i:j, 0] += sig[: j - i] * l_gain
    buf[i:j, 1] += sig[: j - i] * r_gain


def render_music() -> None:
    sections: list[tuple[list[str], list | None, bool]] = [
        (INTRO, None, False), (PROG_A, MEL_A, False), (PROG_B, MEL_B, False), (PROG_A, MEL_A, True),
    ]
    total_bars = sum(len(p) for p, _, _ in sections)
    loop_len = total_bars * BAR
    tail = 3.0
    buf = np.zeros((int((loop_len + tail) * SR), 2))

    k, s, h = kick(), snare(), hat()
    bar_i = 0
    for prog, melody, doubled in sections:
        for b, chord in enumerate(prog):
            t0 = bar_i * BAR
            root, ivs = CHORDS[chord]
            # organ pad (whole bar)
            for iv in ivs[:3]:
                place(buf, organ(hz(root + iv), BAR), t0, 0.0)
            # bass: driving eighths, octave on the offbeats of 2 and 4
            broot = root - 12 if root >= 45 else root
            for e in range(8):
                m = broot + (12 if e in (2, 5, 7) else 0)
                place(buf, bass(hz(m - 12), BEAT / 2 * 0.95), t0 + e * BEAT / 2, 0.0)
            # drums (enter on intro bar 3)
            if bar_i >= 2:
                for beat in range(4):
                    bt = t0 + beat * BEAT
                    if beat in (0, 2):
                        place(buf, k, bt, 0.0)
                    if beat in (1, 3):
                        place(buf, s, bt, 0.1)
                    place(buf, h, bt, -0.3)
                    place(buf, h * 0.6, bt + BEAT / 2, -0.3)
                place(buf, k * 0.7, t0 + 2.5 * BEAT, 0.0)
            # harpsichord arpeggio in eighths
            if melody is not None:
                pattern = [0, 1, 2, 3, 2, 1, 2, 3]
                tones = [root + ivs[0], root + ivs[1 % len(ivs)], root + ivs[2 % len(ivs)], root + 12]
                for e, pi in enumerate(pattern):
                    place(buf, harpsichord(hz(tones[pi]), BEAT / 2) * 0.45, t0 + e * BEAT / 2, 0.45)
                # lead
                t = t0
                for note, beats in melody[b]:
                    f = hz(midi(note))
                    place(buf, harpsichord(f, beats * BEAT), t, -0.25)
                    if doubled:
                        place(buf, harpsichord(f * 2, beats * BEAT) * 0.35, t, 0.2)
                    t += beats * BEAT
            bar_i += 1

    # cathedral reverb (stereo decorrelated IRs)
    ir_t = t_axis(2.4)
    wet = np.zeros_like(buf)
    for ch in range(2):
        ir = RNG.standard_normal(len(ir_t)) * np.exp(-ir_t / 0.75)
        ir = one_pole_lp(ir, 3500)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet[:, ch] = fftconvolve(buf[:, ch], ir)[: len(buf)]
    mix = buf * 0.85 + wet * 0.45

    # wrap the tail into the head for a seamless loop
    n_loop = int(loop_len * SR)
    looped = mix[:n_loop].copy()
    looped[: len(mix) - n_loop] += mix[n_loop:]
    looped = np.tanh(looped * 1.2)
    looped /= np.max(np.abs(looped)) / 0.89

    wav_path = os.path.join(MUSIC, "_tmp_theme.wav")
    write_wav(wav_path, looped)
    ogg_path = os.path.join(MUSIC, "nocturne_of_the_crimson_hall.ogg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path, "-c:a", "libvorbis",
                    "-q:a", "5", ogg_path], check=True)
    os.remove(wav_path)
    print(f"music: {loop_len:.1f}s loop -> {ogg_path}")


# ---------------------------------------------------------------------------
# Sound effects
# ---------------------------------------------------------------------------
def write_wav(path: str, data: np.ndarray) -> None:
    if data.ndim == 1:
        data = data[:, None]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def sweep_noise(dur: float, f0: float, f1: float, decay: float) -> np.ndarray:
    t = t_axis(dur)
    noise = RNG.standard_normal(len(t))
    out = np.zeros_like(noise)
    state = 0.0
    cut = np.linspace(f0, f1, len(t))
    alpha = 1 - np.exp(-2 * np.pi * cut / SR)
    for i in range(len(t)):
        state += alpha[i] * (noise[i] - state)
        out[i] = state
    env = np.minimum(1, t / 0.01) * np.exp(-t * decay)
    return out * env


def tone(dur: float, f0: float, f1: float, decay: float, shape: str = "sine") -> np.ndarray:
    t = t_axis(dur)
    f = np.linspace(f0, f1, len(t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    sig = np.sin(ph) if shape == "sine" else np.sign(np.sin(ph))
    return sig * np.exp(-t * decay)


def mix(*xs: np.ndarray) -> np.ndarray:
    """Sum signals of different lengths (zero-padded)."""
    out = np.zeros(max(len(x) for x in xs))
    for x in xs:
        out[: len(x)] += x
    return out


def norm(x: np.ndarray, peak: float = 0.8) -> np.ndarray:
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def render_sfx() -> None:
    fx: dict[str, np.ndarray] = {
        "sword_swing": norm(sweep_noise(0.2, 600, 5000, 14), 0.6),
        "hit": norm(mix(sweep_noise(0.12, 4000, 800, 30), tone(0.12, 180, 60, 30) * 0.8), 0.8),
        "enemy_death": norm(mix(sweep_noise(0.55, 3000, 300, 6), tone(0.4, 220, 40, 8, "square") * 0.25), 0.75),
        "player_hurt": norm(mix(tone(0.3, 330, 110, 9, "square") * 0.5, sweep_noise(0.2, 2000, 400, 20)), 0.7),
        "jump": norm(sweep_noise(0.12, 300, 2200, 25), 0.35),
        "land": norm(mix(tone(0.08, 140, 60, 40), sweep_noise(0.06, 900, 200, 50) * 0.5), 0.45),
        "backdash": norm(sweep_noise(0.16, 3500, 700, 18), 0.4),
        "heart_pickup": norm(np.concatenate([tone(0.07, 1318, 1318, 10), tone(0.18, 1976, 1976, 14)]), 0.5),
        "dagger_throw": norm(mix(sweep_noise(0.12, 6000, 2500, 25), tone(0.1, 2400, 1800, 30) * 0.2), 0.5),
        "axe_throw": norm(sweep_noise(0.3, 900, 3000, 8), 0.5),
        "candle_break": norm(mix(tone(0.25, 2600, 2500, 16) * 0.4, tone(0.25, 3700, 3600, 22) * 0.3,
                                 sweep_noise(0.1, 6000, 3000, 40)), 0.55),
        "bone_throw": norm(mix(tone(0.06, 900, 600, 40, "square") * 0.3, sweep_noise(0.08, 2500, 1500, 40)), 0.4),
        "bat_screech": norm(mix(tone(0.18, 2400, 3200, 12, "square") * 0.2, sweep_noise(0.18, 5000, 7000, 12) * 0.4), 0.35),
        "player_death": norm(mix(tone(1.2, 220, 55, 2.5, "square") * 0.4, sweep_noise(1.2, 2000, 100, 3)), 0.7),
        "no_hearts": norm(tone(0.1, 180, 180, 20, "square"), 0.3),
    }
    for name, data in fx.items():
        write_wav(os.path.join(SFX, f"{name}.wav"), data)
    print(f"sfx: {len(fx)} files")


def build() -> None:
    render_sfx()
    render_music()


if __name__ == "__main__":
    build()
