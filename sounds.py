"""Versi e rumori del cane, sintetizzati in Python (nessun file audio esterno) e suonati col player di sistema."""
import math
import random
import shutil
import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path

RATE = 22050
VERSION = 1  # cambiare se si modifica la sintesi: rigenera la cache

# altezza della voce per razza (Hz): il maremmano ha un vocione, lo shiba strilla
PITCH = dict(maremmano=230, golden=310, collie=400, dachshund=470, shiba=520)


# ------------------------------------------------------------------ mattoncini di sintesi
def bandpass(xs, f0, q):
    """Filtro passa-banda (biquad RBJ)."""
    w = 2 * math.pi * f0 / RATE
    alpha = math.sin(w) / (2 * q)
    b0, b2 = alpha, -alpha
    a0, a1, a2 = 1 + alpha, -2 * math.cos(w), 1 - alpha
    b0, b2, a1, a2 = b0 / a0, b2 / a0, a1 / a0, a2 / a0
    out, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for x in xs:
        y = b0 * x + b2 * x2 - a1 * y1 - a2 * y2
        out.append(y)
        x2, x1, y2, y1 = x1, x, y1, y
    return out


def lowpass(xs, k):
    out, y = [], 0.0
    for x in xs:
        y += k * (x - y)
        out.append(y)
    return out


def mix(*parts):
    n = max(len(p) for _, p in parts)
    out = [0.0] * n
    for gain, p in parts:
        for i, v in enumerate(p):
            out[i] += gain * v
    return out


def place(dst, src, at):
    i0 = int(at * RATE)
    if len(dst) < i0 + len(src):
        dst.extend([0.0] * (i0 + len(src) - len(dst)))
    for i, v in enumerate(src):
        dst[i0 + i] += v
    return dst


def voice(dur, freq, harmonics=8, breath=0.3, rng=None):
    """Sorgente vocale: armoniche della frequenza (funzione del tempo) più un po' di soffio."""
    rng = rng or random.Random(1)
    out, ph = [], 0.0
    for i in range(int(dur * RATE)):
        t = i / RATE
        ph += 2 * math.pi * freq(t) / RATE
        s = sum(math.sin(k * ph) / k ** 0.9 for k in range(1, harmonics + 1))
        out.append(s * 0.5 + breath * (rng.random() * 2 - 1))
    return out


def formants(src, fs, scale=1.0):
    return mix(*[(g, bandpass(src, f * scale, q)) for f, q, g in fs])


def envelope(xs, attack, decay=None, release=0.03):
    n = len(xs)
    out = []
    for i, x in enumerate(xs):
        t = i / RATE
        a = min(1.0, t / attack) if attack > 0 else 1.0
        d = math.exp(-t / decay) if decay else 1.0
        r = min(1.0, (n - i) / (release * RATE))
        out.append(x * a * d * r)
    return out


def noise(dur, rng):
    return [rng.random() * 2 - 1 for _ in range(int(dur * RATE))]


def bursts(count, every, length, band, q, rng, jitter=0.3):
    out = []
    for k in range(count):
        b = envelope(bandpass(noise(length, rng), band * rng.uniform(0.85, 1.15), q), 0.004, length / 3)
        place(out, b, k * every * rng.uniform(1 - jitter, 1 + jitter))
    return out


# ------------------------------------------------------------------ i suoni
def make(name, p):
    """Ritorna i campioni del suono `name` per una voce di altezza p (Hz)."""
    rng = random.Random(hash((name, p)) & 0xFFFF)
    fscale = (p / 330) ** 0.5  # cani piccoli: formanti più alte
    vow_a = [(700, 4, 1.0), (1250, 5, 0.6), (2600, 6, 0.25)]
    vow_u = [(380, 4, 1.0), (800, 5, 0.45), (2300, 7, 0.12)]

    def bark(pitch, dur=0.17):
        src = voice(dur, lambda t: pitch * (1.3 - 0.5 * t / dur), breath=0.45, rng=rng)
        return envelope(formants(src, vow_a, fscale), 0.006, 0.07)

    if name == "bark":
        out = place([], bark(p), 0.0)
        place(out, bark(p * 0.94), 0.26)
        if rng.random() < 0.6:
            place(out, bark(p * 0.9, 0.2), 0.52)
        return out
    if name == "yip":
        return place([], bark(p * 1.7, 0.1), 0.0)
    if name == "whine":
        src = voice(0.9, lambda t: p * 3.3 + 120 * math.sin(2 * math.pi * 1.6 * t) + 160 * t, 5, 0.08, rng)
        return envelope(formants(src, [(1800, 3, 1.0), (3200, 4, 0.4)], fscale), 0.08, None, 0.2)
    if name == "howl":
        src = voice(2.0, lambda t: p * (1.6 + 0.9 * min(t / 0.4, 1.0) - 0.25 * max(t - 1.3, 0)) * (1 + 0.025 * math.sin(2 * math.pi * 5.5 * t)), 7, 0.1, rng)
        return envelope(formants(src, vow_u, fscale), 0.25, None, 0.5)
    if name == "growl":
        src = voice(1.0, lambda t: p * 0.42 * (1 + 0.08 * math.sin(2 * math.pi * 23 * t)), 10, 0.6, rng)
        mod = [0.6 + 0.4 * math.sin(2 * math.pi * 26 * i / RATE + rng.random() * 0.4) for i in range(len(src))]
        return envelope(lowpass([a * b for a, b in zip(src, mod)], 0.12), 0.1, None, 0.25)
    if name == "pant":
        out = []
        for k in range(6):
            breath = bandpass(noise(0.13, rng), 1400 * fscale, 0.9)
            place(out, envelope(breath, 0.03, 0.05), k * 0.28)
            place(out, envelope([0.5 * v for v in bandpass(noise(0.1, rng), 1100 * fscale, 0.9)], 0.03, 0.04), k * 0.28 + 0.14)
        return out
    if name == "yawn":
        src = voice(1.3, lambda t: p * (1.0 + 0.6 * math.sin(math.pi * min(t / 1.1, 1.0))), 6, 0.35, rng)
        out = envelope(formants(src, vow_a, fscale), 0.2, None, 0.35)
        return place(out, envelope(bandpass(noise(0.03, rng), 1500, 2), 0.001, 0.008), 1.28)  # schiocco della mascella
    if name == "sniff":
        return bursts(4, 0.11, 0.07, 3200, 1.5, rng, 0.15)
    if name == "lick":
        return bursts(3, 0.16, 0.035, 2200, 3, rng)
    if name == "shake":
        n = noise(1.1, rng)
        flap = [v * (0.5 + 0.5 * math.sin(2 * math.pi * 11 * i / RATE)) ** 2 for i, v in enumerate(n)]
        return envelope(bandpass(flap, 900, 0.8), 0.05, 0.6)
    if name == "scratch":
        return bursts(16, 0.07, 0.04, 2600, 1.2, rng, 0.1)
    if name == "dig":
        return mix((1.0, bursts(10, 0.12, 0.07, 700, 1.0, rng)), (0.6, bursts(14, 0.09, 0.02, 3000, 2, rng)))
    if name == "crunch":
        out = []
        for k in range(5):
            crack = [(rng.random() * 2 - 1) if rng.random() < 0.25 else 0.0 for _ in range(int(0.11 * RATE))]
            place(out, envelope(bandpass(crack, 2800, 1.0), 0.003, 0.05), k * 0.24 + rng.uniform(0, 0.05))
        return out
    if name == "snore":
        n = noise(1.6, rng)
        flutter = [v * (0.6 + 0.4 * math.sin(2 * math.pi * 28 * i / RATE)) * math.sin(math.pi * i / len(n)) for i, v in enumerate(n)]
        return [0.6 * v for v in bandpass(flutter, 260, 1.2)]
    if name == "bounce":
        src = [math.sin(2 * math.pi * (170 - 300 * i / RATE) * i / RATE) for i in range(int(0.12 * RATE))]
        return envelope(mix((1.0, src), (0.3, bandpass(noise(0.12, rng), 1800, 2))), 0.002, 0.03)
    if name == "clack":
        src = [math.sin(2 * math.pi * 900 * i / RATE) + 0.7 * math.sin(2 * math.pi * 1350 * i / RATE) for i in range(int(0.09 * RATE))]
        return envelope(mix((0.6, src), (0.5, bandpass(noise(0.09, rng), 2500, 3))), 0.001, 0.02)
    if name == "thud":
        src = [math.sin(2 * math.pi * 85 * i / RATE) for i in range(int(0.14 * RATE))]
        return envelope(mix((1.0, src), (0.4, lowpass(noise(0.14, rng), 0.08))), 0.002, 0.04)
    raise KeyError(name)


NAMES = ["bark", "yip", "whine", "howl", "growl", "pant", "yawn", "sniff", "lick", "shake", "scratch", "dig",
         "crunch", "snore", "bounce", "clack", "thud"]
VOLUME = dict(snore=0.5, sniff=0.7, lick=0.6, pant=0.7, bounce=0.8, clack=0.8, thud=0.9)


def write_wav(path, samples, volume=0.55):
    peak = max((abs(s) for s in samples), default=1.0) or 1.0
    k = volume / peak
    data = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s * k)) * 32767)) for s in samples)
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    tmp.replace(path)


class Player:
    """Suona i versi in background. I file si generano la prima volta e restano in cache."""

    def __init__(self, cache_dir, breed, enabled=True):
        self.dir = Path(cache_dir) / f"v{VERSION}"
        self.enabled = enabled
        self.breed = None
        self.procs = []
        self.ready = set()
        self.cmd = self.backend()
        self.set_breed(breed)

    @staticmethod
    def backend():
        if sys.platform == "win32":
            return "winsound"
        if sys.platform == "darwin":
            return ["afplay"]
        for exe in ("pw-play", "paplay", "aplay"):
            if shutil.which(exe):
                return [exe]
        return None

    def set_breed(self, breed):
        if breed == self.breed:
            return
        self.breed = breed
        threading.Thread(target=self.prepare, args=(breed,), daemon=True).start()

    def path(self, name, breed):
        return self.dir / f"{name}_{breed}.wav"

    def prepare(self, breed):
        """Genera (una volta sola) tutti i suoni della razza: ~1 s di calcolo in un thread."""
        self.dir.mkdir(parents=True, exist_ok=True)
        p = PITCH.get(breed, 330)
        for name in NAMES:
            path = self.path(name, breed)
            if not path.exists():
                try:
                    write_wav(path, make(name, p), 0.55 * VOLUME.get(name, 1.0))
                except OSError:
                    return
            self.ready.add((name, breed))

    def play(self, name):
        if not self.enabled or self.cmd is None or (name, self.breed) not in self.ready:
            return
        path = str(self.path(name, self.breed))
        if self.cmd == "winsound":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return
        self.procs = [p for p in self.procs if p.poll() is None]
        if len(self.procs) >= 3:  # non accavallare troppi versi
            return
        try:
            self.procs.append(subprocess.Popen(self.cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            self.cmd = None
