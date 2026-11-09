# Chibi Studio

Pipeline otomatis buat konten animasi chibi lucu: **naskah → gambar (Gemini) → animasi (Veo) → edit Short + Long (ffmpeg)**.

```
episodes/epXXX.json ──► frames/*.png ──► clips/*.mp4 ──► epXXX_short.mp4 (9:16 + subtitle)
                        (Gemini image)    (Veo i2v)          │
                                                             └─► long: TikTok 9:16 & YouTube 16:9
```

## Setup

```bash
pip install requests pillow          # ffmpeg harus terpasang
export GEMINI_API_KEY=...            # dari aistudio.google.com (perlu billing aktif untuk Veo)
python make.py models                # cek model image/video yang tersedia, update config.json kalau perlu
```

> Google Flow (labs.google/flow) tidak punya API. Model yang sama (Veo + Gemini image) dipakai
> lewat Gemini API, dan tagihannya terpisah dari langganan Google AI Pro/Ultra.

## Alur kerja

1. **Chibi lu**: taruh 2-4 foto wajah di `characters/me/photos/`, sesuaikan deskripsi di
   `characters/me/character.json`, lalu `python make.py character me`. Cek `sheet.png`, ulangi pakai `--force` kalau kurang mirip.
2. **Karakter lain**: `python make.py character raka` (atau bikin folder karakter baru).
3. **Episode**: `python make.py episode episodes/ep001.json`
   - scene yang jelek: `--redo s2` buat generate ulang
   - cuma edit ulang subtitle/timing: `--only assemble`
4. **Long**: `python make.py long ep001 ep002 ep003 --out kompilasi01 [--intro rekaman_gue.mp4]`
5. Hasil ada di `output/`, caption + hashtag di `output/epXXX/upload.txt`.

Tes semua tanpa API (visual placeholder): tambahkan `--mock`.

## Format episode

Tiap scene: `chars`, `image_prompt` (frame pertama), `motion_prompt` (gerakan), `audio`, `seconds` (4/6/8),
`subs` (`at`, `dur`, `text`, `speaker`: `me` = subtitle kuning). `"interrupt": true` kasih efek flash putih
pas chibi lu nongol. `"clip": "path.mp4"` buat pakai rekaman lu sendiri sebagai scene.

## Biar aman dimonetisasi

- Karakter utama **original** (bukan karakter game/anime orang). Fan-art boleh buat sesekali, risikonya klaim.
- Chibi lu + suara/celetukan lu = bukti konten lu bukan "AI doang" (kebijakan *inauthentic/reused content* YouTube).
- Centang label **AI-generated** saat upload (TikTok & YouTube).
- TikTok Creator Rewards butuh video > 1 menit → pakai output `long`.
