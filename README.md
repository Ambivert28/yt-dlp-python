# yt-dlp Python downloader

## Download (Windows)
The prebuilt `yt-dlp-downloader.exe` is published on the
[Releases](../../releases) page (built automatically by GitHub Actions).
Download the latest `.exe` and run it — yt-dlp and ffmpeg are fetched on first
run. The binary is no longer committed to the repository.

## Roadmap
Planned but not-yet-done items for upcoming releases are tracked in
[`ROADMAP.md`](ROADMAP.md).

## Requirements (run from source)
- Python 3.10 or newer (the code uses PEP 604 `X | None` type hints).
- Tkinter (ships with the official CPython installers on Windows/macOS; on
  Linux install e.g. `python3-tk`).
- Node.js is recommended for YouTube JS runtime support.
- ffmpeg: bundled automatically on Windows; on macOS/Linux install a system
  ffmpeg (`brew install ffmpeg` / `apt install ffmpeg`).

## How to
How to run (Windows):
1. Run `run.bat` (double-click) or in terminal:
   `python downloader.py`
2. Paste URLs (one per line) into the app.
3. Pick output format (MP3 320k, M4A 256k, AAC 256k, FLAC, WEBM Video) and output directory.
4. Choose playlist mode: single file or full playlist.
5. Optionally tune **Parallel downloads** and **Concurrent fragments**.
6. Click **Download** and watch the status; logs are available via the **Show logs** button.
   Use **Stop** to cancel; partial `.part` files are cleaned up afterwards.
7. Files appear in the selected output directory (default: `Downloads/YYYY-MM-DD`).

CLI mode (optional):
1. Copy `urls.example.txt` to `urls.txt` (not included in the repo) and put your URLs (one per line) inside
2. Run `python downloader.py --cli` (optional: `--single` or `--playlist`)
3. Watch console output (progress). Logs are written to `logs/yt-dlp.log` and `logs/yt-dlp-errors.log`
4. Files appear in the default output directory (Downloads or `downloads/` with a `YYYY-MM-DD` subfolder)

Notes:
- Binaries (yt-dlp.exe and ffmpeg.exe) will be downloaded to `bin/` automatically on first run, verified against published SHA-256 checksums, with retries on transient network errors.
- yt-dlp self-updates on each run (`--update-to stable@latest`); ffmpeg is refreshed when a new release ZIP is detected. Pin a specific ffmpeg build with the `FFMPEG_PINNED_VERSION` env var.
- App icon is embedded in `icon_data.py` and the app will try to fetch the GitHub avatar at first run and cache it in `cache/` for the title bar.
- Output formats include MP3 320k, M4A 256k, AAC 256k, FLAC, and WEBM Video.
- Publisher: KENSAN LAB.
- If you see JS runtime warnings for YouTube, install Node.js (recommended).
- Public hosting of this service is discouraged due to policy/abuse risk; run locally or in a secured private environment.

> [!IMPORTANT]
> Software used:
> * Python
> * Node.js
> * yt-dlp
> * ffmpeg

## Build EXE (Windows)
Releases are built automatically by the `Build and Release` GitHub Actions
workflow when a `v*` tag is pushed (or via manual *Run workflow*). To build
locally, use PyInstaller. The EXE will still download yt-dlp/ffmpeg on first run.

```bash
pip install pyinstaller
python tools/write_icon.py
python -m PyInstaller --onefile --windowed --icon app.ico --name yt-dlp-downloader downloader.py
```

## Directory structure
```
yt-dlp-python/
│
├── downloader.py        # main Python script (run this)
├── run.bat              # Windows launcher (runs python)
├── urls.example.txt     # sample URL list (copy to urls.txt for CLI mode)
├── icon_data.py         # embedded icon (base64)
├── pyproject.toml       # project metadata + Python version requirement
├── requirements-dev.txt # build/lint/test tooling
├── tests/               # unit tests (pytest)
├── ROADMAP.md           # planned / outstanding work
├── README.md
├── .gitignore
│
├── downloads/           # output (non-Windows; YYYY-MM-DD subfolders)
├── logs/
│   ├── yt-dlp.log
│   └── yt-dlp-errors.log
├── cache/               # icon cache (fetched from URL)
├── tools/
│   └── write_icon.py    # generates app.ico locally for the EXE build
└── bin/
    ├── yt-dlp(.exe)     # downloaded automatically on first run (verified via SHA-256)
    └── ffmpeg(.exe)     # downloaded automatically on first run (Windows)
```
