#!/usr/bin/env python3
"""Human-like auto typer for Linux (Wayland / X11).

Untuk testing/demo aplikasi sendiri. Jalan dengan `uv` tanpa dependency
Python tambahan — eksekusi ketik memakai tool native (wtype/xdotool/ydotool).

Contoh:
    uv run autotype.py --dry-run
    uv run autotype.py --text "halo dunia" --countdown 4
    uv run autotype.py --file naskah.txt --wpm-min 70 --wpm-max 110 --typo-rate 0.05

Edit TEXT di bawah kalau mau naskah permanen di code.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Naskah default — EDIT DI SINI (sesuai request: "nanti saya set di code")
# ---------------------------------------------------------------------------
TEXT = """
#include <iostream>
#include <vector>
#include <string>
using namespace std;
int main() {
ios_base::sync_with_stdio(false);
cin.tie(NULL);
int n, q;
if (!(cin >> n >> q)) return 0;
string s;
cin >> s;
vector<int> cnt1(n + 1, 0);
int current_parity = 0;
for (int i = 1; i <= n; i++) {
if (s[i - 1] == '1') {
current_parity ^= 1;
}
cnt1[i] = cnt1[i - 1] + current_parity;
}
while (q--) {
int l, r;
cin >> l >> r;
long long total_len = r - l + 2;
long long c1 = cnt1[r] - (l >= 2 ? cnt1[l - 2] : 0);
long long c0 = total_len - c1;
long long ans = (c0 * (c0 - 1)) / 2 + (c1 * (c1 - 1)) / 2;
cout << ans << "\n";
}
return 0;
}
 
"""

# QWERTY adjacency untuk typo yang realistis (huruf ketukar sebelahnya).
ADJACENT: dict[str, str] = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdfr",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "i": "ujklo", "j": "huiknm",
    "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp",
    "p": "ol", "q": "wsa", "r": "edfgt", "s": "awedxz", "t": "rfgyh",
    "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu",
    "z": "asx",
}

# Action = (kind, arg, sleep_before)
# kind: "type" -> ketik string, "key" -> BackSpace/Return, "pause" -> jeda saja
Action = tuple[str, str, float]


def typo_char(c: str, rng: random.Random) -> str:
    low = c.lower()
    candidates = ADJACENT.get(low, "asdf")
    wrong = rng.choice(candidates)
    return wrong.upper() if c.isupper() else wrong


def char_delay(c: str, wpm: float, rng: random.Random) -> float:
    """Delay dasar per karakter dari WPM (standar 5 char = 1 kata)."""
    cps = max(1.0, wpm * 5.0 / 60.0)
    base = 1.0 / cps
    d = rng.gauss(base, base * 0.35)
    d = max(0.015, min(d, base * 3.0))
    if c.isupper():
        d *= 1.35
    if c.isdigit():
        d *= 1.2
    if c in ",;:\"'()":
        d *= rng.uniform(1.4, 2.0)
    return max(0.012, d)


def plan_actions(
    text: str,
    rng: random.Random,
    typo_rate: float = 0.04,
    wpm_min: float = 70.0,
    wpm_max: float = 110.0,
) -> list[Action]:
    """Ubah teks jadi daftar aksi human-like (murni, testable, tanpa I/O)."""
    actions: list[Action] = []
    for c in text:
        wpm = rng.uniform(wpm_min, wpm_max)
        d = char_delay(c, wpm, rng)

        # --- typo + koreksi (kadang salah, hapus, ketik lagi) ---
        if c.isalpha() and rng.random() < typo_rate:
            wrong = typo_char(c, rng)
            actions.append(("type", wrong, d))
            actions.append(("pause", "", rng.uniform(0.15, 0.40)))  # sadar salah
            if rng.random() < 0.15:  # kadang salah 2x beruntun
                wrong2 = typo_char(c, rng)
                actions.append(("type", wrong2, rng.uniform(0.04, 0.12)))
                actions.append(("key", "BackSpace", rng.uniform(0.10, 0.22)))
            actions.append(("key", "BackSpace", rng.uniform(0.10, 0.24)))
            actions.append(("type", c, rng.uniform(0.08, 0.22)))
        elif c == "\n":
            actions.append(("key", "Return", d + rng.uniform(0.25, 0.70)))
        else:
            actions.append(("type", c, d))

        # --- jeda natural ---
        if c == " ":
            actions.append(("pause", "", rng.uniform(0.06, 0.22)))
            if rng.random() < 0.02:  # pause mikir
                actions.append(("pause", "", rng.uniform(0.80, 1.80)))
            elif rng.random() < 0.08:  # jeda burst
                actions.append(("pause", "", rng.uniform(0.25, 0.60)))
        elif c in ".!?":
            actions.append(("pause", "", rng.uniform(0.35, 0.90)))

    return actions


# ---------------------------------------------------------------------------
# Backend eksekusi (Wayland vs X11)
# ---------------------------------------------------------------------------
class Backend:
    name = "base"

    def emit_text(self, s: str) -> None:
        raise NotImplementedError

    def emit_key(self, keysym: str) -> None:
        raise NotImplementedError


def _run(cmd: list[str], env_extra: dict[str, str] | None = None) -> None:
    env = None
    if env_extra:
        env = dict(os.environ)
        env.update(env_extra)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:300]
        raise RuntimeError(f"{' '.join(cmd)} gagal: {err}")


def _ydotool_env() -> dict[str, str]:
    """Kembalikan env YDOTOOL_SOCKET jika perlu (daemon system vs user)."""
    if os.environ.get("YDOTOOL_SOCKET"):
        return {}
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    candidates = [
        f"/run/user/{uid}/.ydotool_socket",
        "/tmp/.ydotool_socket",
    ]
    for p in candidates:
        if os.path.exists(p):
            return {"YDOTOOL_SOCKET": p}
    return {}


class WtypeBackend(Backend):
    """Wayland native. Install: sudo dnf install wtype"""
    name = "wtype"

    def emit_text(self, s: str) -> None:
        _run(["wtype", "--", s])

    def emit_key(self, keysym: str) -> None:
        key = "BackSpace" if keysym == "BackSpace" else "Return"
        _run(["wtype", "-k", key])


class XdotoolBackend(Backend):
    """X11. Install: sudo dnf install xdotool"""
    name = "xdotool"

    def emit_text(self, s: str) -> None:
        _run(["xdotool", "type", "--delay", "0", "--", s])

    def emit_key(self, keysym: str) -> None:
        key = "BackSpace" if keysym == "BackSpace" else "Return"
        _run(["xdotool", "key", key])


class YdotoolBackend(Backend):
    """Universal via /dev/uinput. Butuh: sudo dnf install ydotool +
    sudo systemctl enable --now ydotoold (user harus di grup input)."""
    name = "ydotool"

    def emit_text(self, s: str) -> None:
        env = _ydotool_env()
        # Hindari "--" literal kalau tidak perlu (beberapa build mengetiknya).
        cmd = ["ydotool", "type", s] if not s.startswith("-") else ["ydotool", "type", "--", s]
        _run(cmd, env)

    def emit_key(self, keysym: str) -> None:
        # PENTING: `ydotool key` HANYA terima keycode (man ydotool:
        # "Non-interpretable values ... will only cause a delay").
        # Nama seperti "BackSpace" exit 0 tapi NO-OP -> huruf salah tidak
        # terhapus. Jadi langsung pakai keycode, tanpa coba nama dulu.
        # 14 = KEY_BACKSPACE, 28 = KEY_ENTER (linux/input-event-codes.h).
        code = "14:1 14:0" if keysym == "BackSpace" else "28:1 28:0"
        _run(["ydotool", "key"] + code.split(), _ydotool_env())


class PynputBackend(Backend):
    """Fallback Python (bagus di X11, sering diblokir di Wayland).
    Install: uv add pynput"""
    name = "pynput"

    def __init__(self) -> None:
        try:
            from pynput.keyboard import Controller, Key  # type: ignore
        except ImportError as e:
            raise RuntimeError("pynput belum terinstall. Jalan: uv add pynput") from e
        self._ctl = Controller()
        self._Key = Key

    def emit_text(self, s: str) -> None:
        self._ctl.type(s)

    def emit_key(self, keysym: str) -> None:
        k = self._Key.backspace if keysym == "BackSpace" else self._Key.enter
        self._ctl.press(k)
        self._ctl.release(k)


def detect_session() -> str:
    t = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if t:
        return t
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "unknown"


def pick_backend(prefer: str = "auto") -> Backend:
    if prefer != "auto":
        return _make(prefer)
    session = detect_session()
    order = (
        ["wtype", "ydotool", "pynput"]
        if session == "wayland"
        else ["xdotool", "ydotool", "wtype", "pynput"]
        if session == "x11"
        else ["wtype", "xdotool", "ydotool", "pynput"]
    )
    missing: list[str] = []
    for name in order:
        if name == "pynput" or shutil.which(name):
            try:
                return _make(name)
            except Exception as e:
                missing.append(f"{name} ({e})")
                continue
        else:
            missing.append(name)
    raise RuntimeError(
        "Tidak ada backend ketik yang tersedia.\n"
        f"Sesi: {session}. Dicoba: {', '.join(missing)}.\n"
        "Fedora: sudo dnf install wtype xdotool ydotool\n"
        "Untuk ydotool: sudo systemctl enable --now ydotoold"
    )


def _make(name: str) -> Backend:
    if name == "wtype":
        if not shutil.which("wtype"):
            raise RuntimeError("wtype tidak ditemukan (sudo dnf install wtype)")
        return WtypeBackend()
    if name == "xdotool":
        if not shutil.which("xdotool"):
            raise RuntimeError("xdotool tidak ditemukan (sudo dnf install xdotool)")
        return XdotoolBackend()
    if name == "ydotool":
        if not shutil.which("ydotool"):
            raise RuntimeError("ydotool tidak ditemukan (sudo dnf install ydotool)")
        return YdotoolBackend()
    if name == "pynput":
        return PynputBackend()
    raise ValueError(f"backend tidak dikenal: {name}")


def run_actions(actions: list[Action], backend: Backend) -> None:
    for kind, arg, delay in actions:
        time.sleep(max(0.0, delay))
        if kind == "type":
            backend.emit_text(arg)
        elif kind == "key":
            backend.emit_key(arg)
        # "pause" -> cukup sleep saja


def countdown(sec: int) -> None:
    print(f"Fokus ke window target! Mulai dalam {sec} detik (Ctrl+C batal)...")
    try:
        for i in range(sec, 0, -1):
            print(f"  {i}...", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDibatalkan.")
        sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Human-like auto typer (uv, Linux).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--text", help="teks langsung")
    src.add_argument("--file", help="path file teks")
    p.add_argument("--wpm-min", type=float, default=70, help="default 70")
    p.add_argument("--wpm-max", type=float, default=110, help="default 110")
    p.add_argument("--typo-rate", type=float, default=0.04, help="0.0-0.2, default 0.04")
    p.add_argument("--countdown", type=int, default=4, help="detik jeda fokus, default 4")
    p.add_argument("--seed", type=int, default=None, help="seed random biar reproducible")
    p.add_argument("--backend", default="auto",
                   choices=["auto", "wtype", "xdotool", "ydotool", "pynput"])
    p.add_argument("--dry-run", action="store_true", help="simulasi tanpa mengetik")
    p.add_argument("--show-n", type=int, default=25, help="baris aksi dry-run")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    elif args.text is not None:
        text = args.text
    else:
        text = TEXT

    if not text:
        print("Teks kosong.", file=sys.stderr)
        return 2
    if not (0.0 <= args.typo_rate <= 0.3):
        print("--typo-rate harus 0.0 - 0.3", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    actions = plan_actions(text, rng, args.typo_rate, args.wpm_min, args.wpm_max)
    total_sleep = sum(a[2] for a in actions)
    n_typos = sum(1 for a in actions if a[0] == "key" and a[1] == "BackSpace")

    print(f"Sesi: {detect_session()} | chars: {len(text)} | "
          f"aksi: {len(actions)} | typo dikoreksi: ~{n_typos} | "
          f"estimasi: {total_sleep:.1f}s")

    if args.dry_run:
        for kind, arg, delay in actions[: args.show_n]:
            print(f"  sleep {delay*1000:5.0f}ms  {kind:5s} {arg!r}")
        if len(actions) > args.show_n:
            print(f"  ... +{len(actions) - args.show_n} aksi")
        return 0

    try:
        backend = pick_backend(args.backend)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 3
    print(f"Backend: {backend.name}")
    countdown(args.countdown)
    print("Mengetik... (Ctrl+C untuk stop)")
    try:
        run_actions(actions, backend)
    except KeyboardInterrupt:
        print("\nDihentikan user.")
        return 130
    except RuntimeError as e:
        print(f"Gagal mengetik: {e}", file=sys.stderr)
        return 4
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
