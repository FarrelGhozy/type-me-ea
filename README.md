# type-me-ea

Auto-type human-like di Linux (Wayland / X11) berbasis `uv`, tanpa dependency Python tambahan.
Untuk testing/demo aplikasi sendiri.

## Fitur

- Delay acak per karakter (distribusi Gauss) dengan kontrol WPM (`--wpm-min`, `--wpm-max`)
- Jeda kata/kalimat, jeda burst, dan pause "mikir" acak
- Typo realistis (huruf ketukar sebelah QWERTY) yang **selalu dihapus pakai `BackSpace` lalu diketik ulang dengan benar**
- Auto-deteksi backend sesuai sesi: `wtype` (Wayland) / `xdotool` (X11) / `ydotool` (universal) / `pynput` (fallback)
- Mode `--dry-run` untuk simulasi tanpa mengetik beneran
- `--seed` biar hasil random reproducible

## Kebutuhan

- Linux (teruji di Fedora, sesi Wayland) + `uv` terinstall
- Salah satu tool backend:
  ```bash
  sudo dnf install ydotool   # rekomendasi / universal (butuh daemon)
  # atau: sudo dnf install wtype    # Wayland native
  # atau: sudo dnf install xdotool  # X11 saja
  ```

## Setup daemon `ydotool` (Fedora)

Nama unit yang benar adalah `ydotool.service` (bukan `ydotoold`):

```bash
sudo systemctl enable --now ydotool.service
```

Kalau muncul `Permission denied` pada socket, perbaiki izin socket-nya:

```bash
sudo mkdir -p /etc/systemd/system/ydotool.service.d
printf '[Service]\nExecStart=\nExecStart=/usr/bin/ydotoold --socket-path=/tmp/.ydotool_socket --socket-perm=0666\n' \
  | sudo tee /etc/systemd/system/ydotool.service.d/socket.conf
sudo systemctl daemon-reload
sudo systemctl restart ydotool.service
ls -l /tmp/.ydotool_socket   # harusnya srw-rw-rw-
```

## Cara pakai

Naskah default bisa diedit langsung di konstanta `TEXT` di `autotype.py`.

```bash
# Simulasi dulu (tidak mengetik beneran)
uv run autotype.py --dry-run --seed 7

# Ketik teks langsung (fokus ke window target saat countdown)
uv run autotype.py --text "halo dunia" --countdown 4

# Dari file + atur kecepatan dan typo
uv run autotype.py --file naskah.txt --wpm-min 70 --wpm-max 110 --typo-rate 0.05

# Paksa backend tertentu
uv run autotype.py --backend ydotool --text "tes 123" --countdown 4 --typo-rate 0
```

| Opsi | Default | Keterangan |
| --- | --- | --- |
| `--text` / `--file` | `TEXT` di code | Sumber naskah |
| `--wpm-min` / `--wpm-max` | 70 / 110 | Rentang kecepatan ketik |
| `--typo-rate` | 0.04 | Peluang typo per huruf (0.0–0.3) |
| `--countdown` | 4 | Detik jeda untuk fokus window (Ctrl+C batal) |
| `--seed` | acak | Seed random biar bisa diulang |
| `--backend` | auto | `auto`/`wtype`/`xdotool`/`ydotool`/`pynput` |
| `--dry-run` | off | Cetak rencana aksi tanpa mengetik |

## Cara kerja typo

Di `plan_actions` (`autotype.py`), tiap huruf punya peluang jadi typo (huruf QWERTY sebelahnya),
lalu urutannya selalu: ketik salah → jeda → `BackSpace` hapus → ketik yang benar.
Hasil akhir selalu sama persis dengan teks asli — sudah dibuktikan lewat reconstruct test
di beberapa seed. Catatan: `ydotool key` hanya menerima keycode (`14:1 14:0` untuk
BackSpace), nama key seperti `BackSpace` diabaikan diam-diam oleh ydotool.

## Troubleshooting

| Gejala | Solusi |
| --- | --- |
| `Unit ydotoold.service does not exist` | Pakai `ydotool.service` |
| `failed to connect socket ... Permission denied` | Terapkan override `--socket-perm=0666` di atas |
| Tidak mengetik di Wayland pakai `pynput`/`xdotool` | Wayland memblokirnya; pakai `wtype` atau `ydotool` |
| Ingin berhenti | `Ctrl+C` kapan saja |
