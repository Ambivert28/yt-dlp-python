#!/usr/bin/env python3
"""
yt-dlp Python launcher
- GUI app to paste URLs, choose output format/dir, and track status
- auto-downloads yt-dlp.exe and ffmpeg if missing (bin/)
- runs several yt-dlp processes in parallel (one process per URL)
- streams output to GUI and writes logs (logs/)
- converts best audio -> selected format, embeds metadata & cover
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import sys
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Empty, Queue

# tkinter is only needed for the GUI; guard the import so the module (and its
# pure helpers) can be imported in headless environments and unit tests.
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except Exception:  # pragma: no cover - headless / tkinter missing
    tk = None
    filedialog = messagebox = ttk = None
    ScrolledText = None

from icon_data import ICO_BASE64, PNG_BASE64

# Application version. Kept in sync with the released tag by CI (the release
# workflow can override it via the APP_VERSION environment variable).
__version__ = os.environ.get("APP_VERSION", "1.3.0")

# ---------------- CONFIG ----------------
# When frozen by PyInstaller, __file__ points at a temporary extraction dir
# that is wiped on exit; use the executable's directory so bin/, logs/ and
# downloads/ persist next to the .exe.
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""

# default network timeout (seconds) for all HTTP requests
NETWORK_TIMEOUT = 60
# how many times to retry a failed binary download (with exponential backoff)
DOWNLOAD_RETRIES = 3

BIN = BASE / "bin"
ICON_CACHE_DIR = BASE / "cache"

def default_output_dir():
    date_folder = dt.date.today().isoformat()
    if sys.platform.startswith("win"):
        base_dir = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
    else:
        base_dir = BASE / "downloads"
    return base_dir / date_folder

OUT = default_output_dir()
LOGS = BASE / "logs"
YT_DLP_EXE = BIN / f"yt-dlp{EXE_SUFFIX}"
FFMPEG_EXE = BIN / f"ffmpeg{EXE_SUFFIX}"
FFPROBE_EXE = BIN / f"ffprobe{EXE_SUFFIX}"

URLS_FILE = BASE / "urls.txt"
LOG_FILE = LOGS / "yt-dlp.log"
ERR_LOG_FILE = LOGS / "yt-dlp-errors.log"

# parallelism: how many simultaneous URL processes
MAX_WORKERS = 4

# yt-dlp fragment parallelism (inside each process)
PARALLEL_FRAGMENTS = "16"
CONCURRENT_FRAGMENTS = "16"

# audio options
AUDIO_QUALITY = "0"  # best VBR

# download sources

def _ytdlp_asset_name():
    if IS_WINDOWS:
        return "yt-dlp.exe"
    if IS_MACOS:
        return "yt-dlp_macos"
    return "yt-dlp_linux"

YTDLP_ASSET_NAME = _ytdlp_asset_name()
YTDLP_RELEASE_URL = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{YTDLP_ASSET_NAME}"
# yt-dlp publishes a checksum manifest alongside every release; used to verify
# the downloaded binary before it is ever executed.
YTDLP_SHA_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
# Pin a specific ffmpeg build for reproducibility by setting FFMPEG_PINNED_VERSION
# (e.g. "7.1") via the environment; otherwise the latest "release-essentials"
# build is used. gyan.dev publishes a matching ".sha256" used for verification.
FFMPEG_PINNED_VERSION = os.environ.get("FFMPEG_PINNED_VERSION", "").strip()
if FFMPEG_PINNED_VERSION:
    FFMPEG_ZIP_URL = (
        "https://www.gyan.dev/ffmpeg/builds/packages/"
        f"ffmpeg-{FFMPEG_PINNED_VERSION}-essentials_build.zip"
    )
else:
    FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA_URL = FFMPEG_ZIP_URL + ".sha256"
FFMPEG_VERSION_FILE = BIN / "ffmpeg.version"
ICON_URL = "https://avatars.githubusercontent.com/u/79589310?v=4"

OUTPUT_FORMATS = [
    {"name": "MP3 320k", "format": "mp3", "bitrate": "320K", "video_only": False, "output_ext": "mp3"},
    {"name": "M4A 256k", "format": "m4a", "bitrate": "256K", "video_only": False, "output_ext": "m4a"},
    {
        "name": "AAC 256k",
        "format": "aac",
        "bitrate": "256K",
        "video_only": False,
        "output_ext": "m4a",
        "audio_codec": "aac",
    },
    {"name": "FLAC", "format": "flac", "bitrate": None, "video_only": False, "output_ext": "flac"},
    {"name": "WEBM Video", "format": "webm", "bitrate": None, "video_only": True, "output_ext": "webm"},
]
PLAYLIST_MODES = {"single": "Single file", "playlist": "Playlist (all items)"}
LOG_LOCK = threading.Lock()
# ----------------------------------------

def ensure_dirs():
    for d in (BIN, OUT, LOGS, ICON_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # ensure logs exist
    LOG_FILE.touch(exist_ok=True)
    ERR_LOG_FILE.touch(exist_ok=True)

def download_file(url: str, dest: Path, retries: int = DOWNLOAD_RETRIES):
    print(f"Downloading {url} -> {dest.name} ...")
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response, dest.open("wb") as handle:
                # stream in chunks instead of loading the whole file into memory
                shutil.copyfileobj(response, handle)
            return
        except Exception as e:
            last_error = e
            print(f"ERROR downloading {url} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s, ...
    raise last_error

def fetch_text(url: str) -> str | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def expected_sha256(sums_text: str, asset_name: str) -> str | None:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("*") == asset_name:
            return parts[0].lower()
    return None

def png_to_ico(png_data: bytes) -> bytes:
    if not png_data.startswith(b"\x89PNG"):
        raise ValueError("Icon data is not a PNG")
    width = int.from_bytes(png_data[16:20], "big")
    height = int.from_bytes(png_data[20:24], "big")
    w = width if width < 256 else 0
    h = height if height < 256 else 0
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png_data), 22)
    return header + entry + png_data

def ensure_icon_files():
    png_path = ICON_CACHE_DIR / "app.png"
    ico_path = ICON_CACHE_DIR / "app.ico"
    if png_path.exists() and ico_path.exists():
        return png_path, ico_path
    try:
        download_file(ICON_URL, png_path)
        ico_path.write_bytes(png_to_ico(png_path.read_bytes()))
    except Exception:
        return None, None
    return png_path, ico_path

def get_remote_last_modified(url: str):
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            return response.headers.get("Last-Modified")
    except Exception:
        return None

def read_version_stamp():
    if FFMPEG_VERSION_FILE.exists():
        return FFMPEG_VERSION_FILE.read_text(encoding="utf-8").strip()
    return None

def write_version_stamp(value: str | None):
    if value:
        FFMPEG_VERSION_FILE.write_text(value, encoding="utf-8")

def verify_yt_dlp(path: Path) -> bool:
    """Verify the downloaded binary against the published SHA2-256SUMS.

    Returns True when it matches; True as well if the manifest cannot be
    fetched (so an offline-ish environment is not fully blocked), and False
    only on a definite mismatch.
    """
    sums_text = fetch_text(YTDLP_SHA_URL)
    if not sums_text:
        print("WARNING: could not fetch yt-dlp checksums; skipping verification.")
        return True
    expected = expected_sha256(sums_text, YTDLP_ASSET_NAME)
    if not expected:
        print("WARNING: no checksum entry for", YTDLP_ASSET_NAME, "; skipping verification.")
        return True
    actual = sha256_of(path)
    if actual != expected:
        print(f"ERROR: yt-dlp checksum mismatch (expected {expected}, got {actual}).")
        return False
    return True

def ensure_yt_dlp():
    if not YT_DLP_EXE.exists():
        tmp = BIN / f"yt-dlp.tmp{EXE_SUFFIX}"
        download_file(YTDLP_RELEASE_URL, tmp)
        if not verify_yt_dlp(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError("yt-dlp checksum verification failed")
        if not IS_WINDOWS:
            tmp.chmod(0o755)
        tmp.replace(YT_DLP_EXE)
        print("yt-dlp downloaded.")
    else:
        # try to self-update via downloaded binary; ignore errors.
        # --update-to stable@latest is more reliable than -U for non-release builds.
        try:
            subprocess.run(
                [str(YT_DLP_EXE), "--update-to", "stable@latest"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )
        except Exception:
            pass

def ensure_ffmpeg():
    # The bundled ffmpeg build is Windows-only (gyan.dev). On macOS/Linux rely
    # on a system ffmpeg from PATH and only warn if it is missing.
    if not IS_WINDOWS:
        if FFMPEG_EXE.exists() or shutil.which("ffmpeg"):
            return
        print("WARNING: ffmpeg not found on PATH. Install it via your package "
              "manager (e.g. 'brew install ffmpeg' or 'apt install ffmpeg').")
        return

    remote_stamp = get_remote_last_modified(FFMPEG_ZIP_URL)
    local_stamp = read_version_stamp()
    needs_update = not FFMPEG_EXE.exists()
    if remote_stamp and remote_stamp != local_stamp:
        needs_update = True

    if needs_update:
        zpath = BIN / "ffmpeg.zip"
        download_file(FFMPEG_ZIP_URL, zpath)
        sha_text = fetch_text(FFMPEG_SHA_URL)
        if sha_text:
            expected = sha_text.split()[0].strip().lower() if sha_text.split() else None
            if expected and sha256_of(zpath) != expected:
                zpath.unlink(missing_ok=True)
                raise RuntimeError("ffmpeg archive checksum verification failed")
        else:
            print("WARNING: could not fetch ffmpeg checksum; skipping verification.")
        try:
            with zipfile.ZipFile(zpath, "r") as z:
                z.extractall(BIN)
            # find ffmpeg/ffprobe in extracted tree
            ffmpeg_src = None
            ffprobe_src = None
            for p in BIN.rglob("ffmpeg.exe"):
                ffmpeg_src = p
                break
            for p in BIN.rglob("ffprobe.exe"):
                ffprobe_src = p
                break
            if not ffmpeg_src:
                raise FileNotFoundError("ffmpeg.exe not found inside archive")
            shutil.copy2(ffmpeg_src, FFMPEG_EXE)
            if ffprobe_src:
                shutil.copy2(ffprobe_src, FFPROBE_EXE)
            write_version_stamp(remote_stamp)
            print("ffmpeg extracted.")
        finally:
            try:
                zpath.unlink()
            except Exception:
                pass

def read_urls_from_file():
    if not URLS_FILE.exists():
        print("No urls.txt found. Create the file and put one URL per line.")
        sys.exit(1)
    lines = []
    with URLS_FILE.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    if not lines:
        print("urls.txt is empty (or only comments).")
        sys.exit(1)
    return lines

def read_urls_from_text(text: str):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines

def build_command(url: str, output_dir: Path, output_format: dict, playlist_mode: str,
                  fragments: str = PARALLEL_FRAGMENTS):
    # include %(id)s so two videos sharing a title do not overwrite each other
    outtmpl = f"{output_dir / '%(title)s [%(id)s].%(ext)s'}"
    fragments = str(fragments)
    cmd = [
        str(YT_DLP_EXE),
        "--js-runtimes",
        "node",
        "-o",
        outtmpl,
        "-N",
        fragments,
        "--concurrent-fragments",
        fragments,
        "--embed-metadata",
        "--progress",
        "--newline",
        "--ignore-errors",
        "--no-mtime",
        "--restrict-filenames",
        # resume partially downloaded files and retry transient network errors
        "--continue",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
    ]
    # only point yt-dlp at our bundled ffmpeg when we actually have one;
    # otherwise let it find a system ffmpeg on PATH
    if FFMPEG_EXE.exists():
        cmd += ["--ffmpeg-location", str(BIN)]
    if output_format["video_only"]:
        cmd += ["-f", "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]"]
        cmd += ["--no-embed-thumbnail"]
    else:
        cmd += ["--embed-thumbnail"]
        cmd += [
            "-f",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            output_format["output_ext"],
        ]
        if output_format.get("bitrate"):
            cmd += ["--audio-quality", output_format["bitrate"]]
        else:
            cmd += ["--audio-quality", AUDIO_QUALITY]
        if output_format.get("audio_codec"):
            cmd += ["--postprocessor-args", f"ffmpeg:-c:a {output_format['audio_codec']}"]
    cmd.append(url)
    if playlist_mode == "single":
        cmd.insert(-1, "--no-playlist")
    return cmd

def infer_status(line: str):
    lowered = line.lower()
    if "extracting audio" in lowered or "post-process" in lowered or "ffmpeg" in lowered:
        return "converting"
    if "adding metadata" in lowered or "embedding" in lowered:
        return "tagging"
    if "deleting original" in lowered:
        return "cleanup"
    if "warning" in lowered:
        return "warning"
    if "error" in lowered:
        return "error"
    if "[download]" in lowered or "%" in lowered or "destination" in lowered:
        return "downloading"
    return None

def log_line(message: str, log_handle):
    with LOG_LOCK:
        log_handle.write(message + "\n")
        log_handle.flush()

def queue_event(event_queue: Queue | None, payload: dict):
    if event_queue is not None:
        event_queue.put(payload)

def run_yt_dlp_for_url(
    url: str,
    index: int,
    output_dir: Path,
    output_format: dict,
    playlist_mode: str,
    event_queue: Queue | None = None,
    cancel_event: threading.Event | None = None,
    proc_registry: set | None = None,
    registry_lock: threading.Lock | None = None,
    fragments: str = PARALLEL_FRAGMENTS,
):
    """
    Runs the yt-dlp binary as a subprocess for a single URL.
    Streams stdout/stderr to console/GUI with prefix and appends to log files.
    Honours cancel_event for cooperative stopping.
    Returns (url, returncode, last_error_line).
    """
    if cancel_event is not None and cancel_event.is_set():
        return (url, -2, "")

    cmd = build_command(url, output_dir, output_format, playlist_mode, fragments=fragments)
    prefix = f"[{index}] "
    last_error = ""

    creationflags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
        creationflags=creationflags,
    )
    if proc_registry is not None and registry_lock is not None:
        with registry_lock:
            proc_registry.add(proc)
    retcode = None
    try:
        with LOG_FILE.open("a", encoding="utf-8") as logf:
            log_line(f"\n\n=== START {time.strftime('%Y-%m-%d %H:%M:%S')} URL={url}", logf)
            for line in proc.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    break
                out_line = line.rstrip("\n")
                console_line = prefix + out_line
                print(console_line)
                log_line(console_line, logf)
                queue_event(event_queue, {"type": "log", "text": console_line})
                if "error" in out_line.lower():
                    last_error = out_line.strip()
                status = infer_status(out_line)
                if status:
                    queue_event(event_queue, {"type": "status", "index": index, "status": status})
            proc.wait()
            retcode = proc.returncode
            log_line(f"=== END returncode={retcode}", logf)
    except Exception as e:
        with ERR_LOG_FILE.open("a", encoding="utf-8") as ef:
            ef.write(f"ERROR for {url}: {e}\n")
        if proc and proc.poll() is None:
            proc.kill()
        retcode = -1
        last_error = str(e)
    finally:
        if proc_registry is not None and registry_lock is not None:
            with registry_lock:
                proc_registry.discard(proc)

    return (url, retcode, last_error)

def cleanup_partial_files(output_dir: Path):
    """Remove leftover yt-dlp partial files after a cancelled/failed run."""
    if not output_dir.exists():
        return
    removed = 0
    for pattern in ("*.part", "*.ytdl", "*.part-Frag*"):
        for leftover in output_dir.glob(pattern):
            try:
                leftover.unlink()
                removed += 1
            except Exception:
                pass
    return removed

def cli_main():
    print("=== yt-dlp Python downloader ===")
    ensure_dirs()
    print("Ensuring yt-dlp and ffmpeg binaries...")
    try:
        ensure_yt_dlp()
    except Exception as e:
        print("Failed to ensure yt-dlp:", e)
        sys.exit(1)
    try:
        ensure_ffmpeg()
    except Exception as e:
        print("Failed to ensure ffmpeg:", e)
        print("Warning: ffmpeg missing or failed to extract. Conversion may fail.")

    urls = read_urls_from_file()
    playlist_mode = "playlist" if "--playlist" in sys.argv else "single" if "--single" in sys.argv else "playlist"
    output_format = OUTPUT_FORMATS[0]
    print(f"Loaded {len(urls)} URLs. Starting up to {MAX_WORKERS} parallel downloads.")
    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {
            exe.submit(run_yt_dlp_for_url, url, i + 1, OUT, output_format, playlist_mode): url
            for i, url in enumerate(urls)
        }
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                if res[1] == 0:
                    print(f"[SUMMARY] {url} -> OK")
                else:
                    print(f"[SUMMARY] {url} -> FAILED (code {res[1]})")
            except Exception as e:
                print(f"[ERROR] {url} raised exception: {e}")
                with ERR_LOG_FILE.open("a", encoding="utf-8") as ef:
                    ef.write(f"Exception for {url}: {e}\n")

    elapsed = time.time() - start_time
    print("All done. Elapsed: {:.1f}s".format(elapsed))
    print("Logs:", LOG_FILE)
    print("Errors:", ERR_LOG_FILE)

PUBLISHER = "KENSAN LAB"


class DownloaderGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"YouTube Audio Downloader v{__version__} - {PUBLISHER}")
        self.event_queue = Queue()
        self.executor = None
        self.worker_thread = None
        self.cancel_event = threading.Event()
        self.active_procs = set()
        self.procs_lock = threading.Lock()

        self.urls_text = None
        self.log_text = None
        self.log_window = None
        self.log_buffer = []
        self.status_tree = None

        self.output_dir_var = tk.StringVar(value=str(OUT))
        self.format_var = tk.StringVar(value=OUTPUT_FORMATS[0]["name"])
        self.playlist_var = tk.StringVar(value="single")
        self.workers_var = tk.IntVar(value=MAX_WORKERS)
        self.fragments_var = tk.IntVar(value=int(PARALLEL_FRAGMENTS))

        self.start_button = None
        self.stop_button = None

        self.configure_theme()
        self.set_app_icon()
        self.build_ui()
        self.process_queue()

    def configure_theme(self):
        self.root.configure(bg="#1e1e1e")
        preferred_font = ("Segoe UI", 10) if sys.platform.startswith("win") else ("Arial", 10)
        self.root.option_add("*Font", preferred_font)
        self.download_font = (preferred_font[0], 12, "bold")
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabel", background="#1e1e1e", foreground="#e0e0e0")
        style.configure("TButton", background="#2b2b2b", foreground="#e0e0e0")
        style.map("TButton", background=[("active", "#3a3a3a")])
        style.configure("TEntry", fieldbackground="#2b2b2b", foreground="#e0e0e0")
        style.configure("TCombobox", fieldbackground="#2b2b2b", foreground="#e0e0e0")
        style.map("TCombobox", fieldbackground=[("readonly", "#2b2b2b")])
        style.configure("TRadiobutton", background="#1e1e1e", foreground="#e0e0e0")
        style.configure("Treeview", background="#2b2b2b", foreground="#e0e0e0", fieldbackground="#2b2b2b")
        style.configure("Treeview.Heading", background="#1e1e1e", foreground="#e0e0e0")

    def set_app_icon(self):
        icon_loaded = False
        png_path, ico_path = ensure_icon_files()
        if sys.platform.startswith("win"):
            try:
                if ico_path and ico_path.exists():
                    self.root.iconbitmap(default=str(ico_path))
                    icon_loaded = True
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                        tmp.write(base64.b64decode(ICO_BASE64))
                        self._icon_temp_path = tmp.name
                    self.root.iconbitmap(default=self._icon_temp_path)
                    icon_loaded = True
            except Exception:
                pass
        try:
            if png_path and png_path.exists():
                icon_image = tk.PhotoImage(file=str(png_path))
            else:
                icon_image = tk.PhotoImage(data=PNG_BASE64)
            self.root.iconphoto(True, icon_image)
            self._icon_image = icon_image
            icon_loaded = True
        except Exception:
            pass
        if not icon_loaded:
            fallback_ico = Path("app.ico")
            if fallback_ico.exists():
                try:
                    self.root.iconbitmap(default=str(fallback_ico))
                except Exception:
                    pass

    def build_ui(self):
        self.root.geometry("820x640")
        self.root.minsize(780, 560)

        header = ttk.Label(self.root, text="YouTube Audio Downloader", font=("Segoe UI", 14, "bold"))
        header.pack(anchor="w", padx=16, pady=(12, 4))

        urls_header = ttk.Frame(self.root)
        urls_header.pack(fill="x", padx=16)

        urls_label = ttk.Label(urls_header, text="Paste URLs (one per line):")
        urls_label.pack(side="left")

        clear_button = ttk.Button(urls_header, text="Clear list", command=self.clear_urls)
        clear_button.pack(side="right")

        self.urls_text = ScrolledText(
            self.root,
            height=10,
            wrap=tk.WORD,
            background="#2b2b2b",
            foreground="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        self.urls_text.pack(fill="x", padx=16, pady=(4, 12))
        self.bind_text_context_menu()

        options_frame = ttk.Frame(self.root)
        options_frame.pack(fill="x", padx=16)

        playlist_label = ttk.Label(options_frame, text="Playlist mode:")
        playlist_label.grid(row=0, column=0, sticky="ew")

        playlist_single = tk.Radiobutton(
            options_frame,
            text=PLAYLIST_MODES["single"],
            variable=self.playlist_var,
            value="single",
            indicatoron=0,
            background="#2b2b2b",
            foreground="#ffffff",
            activebackground="#1db954",
            activeforeground="#ffffff",
            selectcolor="#1db954",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=4,
        )
        playlist_single.grid(row=0, column=1, sticky="ew")

        playlist_all = tk.Radiobutton(
            options_frame,
            text=PLAYLIST_MODES["playlist"],
            variable=self.playlist_var,
            value="playlist",
            indicatoron=0,
            background="#2b2b2b",
            foreground="#ffffff",
            activebackground="#1db954",
            activeforeground="#ffffff",
            selectcolor="#1db954",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=4,
        )
        playlist_all.grid(row=0, column=2, sticky="ew")

        format_label = ttk.Label(options_frame, text="Output format:")
        format_label.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        format_menu = ttk.Combobox(
            options_frame,
            textvariable=self.format_var,
            values=[fmt["name"] for fmt in OUTPUT_FORMATS],
            state="readonly",
            width=14,
        )
        format_menu.grid(row=0, column=4, padx=(6, 0), sticky="ew")

        output_label = ttk.Label(options_frame, text="Output directory:")
        output_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        output_entry = ttk.Entry(options_frame, textvariable=self.output_dir_var, width=50)
        output_entry.grid(row=1, column=1, columnspan=3, padx=(8, 8), pady=(8, 0), sticky="ew")

        browse_button = ttk.Button(options_frame, text="Browse", command=self.choose_output_dir)
        browse_button.grid(row=1, column=4, pady=(8, 0), sticky="ew")

        workers_label = ttk.Label(options_frame, text="Parallel downloads:")
        workers_label.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        workers_spin = ttk.Spinbox(
            options_frame, from_=1, to=16, textvariable=self.workers_var, width=6
        )
        workers_spin.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        fragments_label = ttk.Label(options_frame, text="Concurrent fragments:")
        fragments_label.grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=(8, 0))
        fragments_spin = ttk.Spinbox(
            options_frame, from_=1, to=64, textvariable=self.fragments_var, width=6
        )
        fragments_spin.grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        self.start_button = tk.Button(
            options_frame,
            text="Download",
            command=self.start_downloads,
            background="#1db954",
            foreground="#ffffff",
            activebackground="#1ed760",
            activeforeground="#ffffff",
            font=self.download_font,
            padx=14,
            pady=8,
            borderwidth=0,
            highlightthickness=0,
        )
        self.start_button.grid(row=3, column=0, columnspan=4, pady=(12, 0), sticky="ew")

        self.stop_button = tk.Button(
            options_frame,
            text="Stop",
            command=self.stop_downloads,
            background="#b3261e",
            foreground="#ffffff",
            activebackground="#d13b32",
            activeforeground="#ffffff",
            font=self.download_font,
            padx=14,
            pady=8,
            borderwidth=0,
            highlightthickness=0,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=3, column=4, pady=(12, 0), padx=(8, 0), sticky="ew")

        for col in range(5):
            options_frame.columnconfigure(col, weight=1, uniform="options")

        spacer = ttk.Frame(self.root)
        spacer.pack(fill="x", padx=16, pady=(10, 6))

        status_header = ttk.Frame(self.root)
        status_header.pack(fill="x", padx=16, pady=(8, 2))

        status_label = ttk.Label(status_header, text="Current downloads:")
        status_label.pack(side="left")

        logs_button = ttk.Button(status_header, text="Show logs", command=self.open_logs_window)
        logs_button.pack(side="right")

        self.status_tree = ttk.Treeview(self.root, columns=("status", "url"), show="headings", height=8)
        self.status_tree.heading("status", text="Status")
        self.status_tree.heading("url", text="URL")
        self.status_tree.column("status", width=120, anchor="w")
        self.status_tree.column("url", width=640, anchor="w")
        self.status_tree.pack(fill="both", padx=16, pady=(0, 10), expand=True)

        self.log_text = None

    def choose_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(OUT))
        if path:
            self.output_dir_var.set(path)

    def clear_urls(self):
        if self.urls_text:
            self.urls_text.delete("1.0", tk.END)

    def set_controls_state(self, enabled: bool):
        self.start_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)
        if self.stop_button is not None:
            self.stop_button.configure(state=tk.DISABLED if enabled else tk.NORMAL)

    def stop_downloads(self):
        self.cancel_event.set()
        with self.procs_lock:
            for proc in list(self.active_procs):
                try:
                    proc.terminate()
                except Exception:
                    pass
        self.append_log("=== Stop requested; cancelling downloads... ===")
        if self.stop_button is not None:
            self.stop_button.configure(state=tk.DISABLED)

    def bind_text_context_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Cut", command=lambda: self.urls_text.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self.urls_text.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self.urls_text.event_generate("<<Paste>>"))

        def show_menu(event):
            menu.tk_popup(event.x_root, event.y_root)

        self.urls_text.bind("<Button-3>", show_menu)
        self.urls_text.bind("<Control-Button-1>", show_menu)

    def open_logs_window(self):
        if self.log_window and tk.Toplevel.winfo_exists(self.log_window):
            self.log_window.lift()
            return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Download logs")
        self.log_window.geometry("820x480")
        self.log_window.configure(bg="#1e1e1e")
        if getattr(self, "_icon_image", None) is not None:
            try:
                self.log_window.iconphoto(True, self._icon_image)
            except Exception:
                pass
        if getattr(self, "_icon_temp_path", None):
            try:
                self.log_window.iconbitmap(default=self._icon_temp_path)
            except Exception:
                pass

        log_text = ScrolledText(
            self.log_window,
            height=10,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#2b2b2b",
            foreground="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        log_text.pack(fill="both", padx=12, pady=12, expand=True)
        self.log_text = log_text
        self.log_text.configure(state=tk.NORMAL)
        for line in self.log_buffer:
            self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def start_downloads(self):
        urls = read_urls_from_text(self.urls_text.get("1.0", tk.END))
        if not urls:
            messagebox.showwarning("No URLs", "Please paste at least one URL.")
            return
        output_dir = Path(self.output_dir_var.get()).expanduser()
        format_name = self.format_var.get()
        playlist_mode = self.playlist_var.get()
        output_format = next((fmt for fmt in OUTPUT_FORMATS if fmt["name"] == format_name), None)
        if output_format is None:
            messagebox.showerror("Invalid format", "Select a valid output format.")
            return
        if playlist_mode not in PLAYLIST_MODES:
            messagebox.showerror("Invalid mode", "Select a playlist mode.")
            return

        self.status_tree.delete(*self.status_tree.get_children())
        for i, url in enumerate(urls, start=1):
            self.status_tree.insert("", "end", iid=str(i), values=("queued", url))

        self.append_log("=== Start ===")
        self.cancel_event.clear()
        self.set_controls_state(False)

        self.worker_thread = threading.Thread(
            target=self.run_downloads,
            args=(urls, output_dir, output_format, playlist_mode),
            daemon=True,
        )
        self.worker_thread.start()

    def run_downloads(self, urls, output_dir: Path, output_format: dict, playlist_mode: str):
        ensure_dirs()
        try:
            ensure_yt_dlp()
        except Exception as e:
            queue_event(self.event_queue, {"type": "log", "text": f"Failed to ensure yt-dlp: {e}"})
            queue_event(self.event_queue, {"type": "done"})
            return
        try:
            ensure_ffmpeg()
        except Exception as e:
            queue_event(self.event_queue, {"type": "log", "text": f"Failed to ensure ffmpeg: {e}"})
            queue_event(self.event_queue, {"type": "log", "text": "Warning: ffmpeg missing or failed to extract. Conversion may fail."})

        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        try:
            workers = max(1, int(self.workers_var.get()))
        except Exception:
            workers = MAX_WORKERS
        try:
            fragments = str(max(1, int(self.fragments_var.get())))
        except Exception:
            fragments = PARALLEL_FRAGMENTS

        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = {
                exe.submit(
                    run_yt_dlp_for_url,
                    url,
                    i + 1,
                    output_dir,
                    output_format,
                    playlist_mode,
                    self.event_queue,
                    self.cancel_event,
                    self.active_procs,
                    self.procs_lock,
                    fragments,
                ): (url, i + 1)
                for i, url in enumerate(urls)
            }
            for fut in as_completed(futures):
                url, index = futures[fut]
                try:
                    _, code, err = fut.result()
                    if code == 0:
                        status = "done"
                    elif code == -2:
                        status = "cancelled"
                    elif err:
                        status = f"failed ({code}): {err[:80]}"
                    else:
                        status = f"failed ({code})"
                    queue_event(self.event_queue, {"type": "status", "index": index, "status": status})
                except Exception as e:
                    queue_event(self.event_queue, {"type": "log", "text": f"[ERROR] {url} raised exception: {e}"})
                    queue_event(self.event_queue, {"type": "status", "index": index, "status": "error"})

        if self.cancel_event.is_set():
            cleanup_partial_files(output_dir)
            queue_event(self.event_queue, {"type": "log", "text": "Removed partial files from cancelled downloads."})

        elapsed = time.time() - start_time
        queue_event(self.event_queue, {"type": "log", "text": f"All done. Elapsed: {elapsed:.1f}s"})
        queue_event(self.event_queue, {"type": "done"})

    def append_log(self, text: str):
        self.log_buffer.append(text)
        if not self.log_text:
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def process_queue(self):
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            if event.get("type") == "log":
                self.append_log(event.get("text", ""))
            elif event.get("type") == "status":
                index = str(event.get("index"))
                status = event.get("status")
                if self.status_tree.exists(index):
                    current = self.status_tree.item(index, "values")
                    self.status_tree.item(index, values=(status, current[1]))
            elif event.get("type") == "done":
                self.set_controls_state(True)
        self.root.after(200, self.process_queue)


def main():
    if "--cli" in sys.argv:
        cli_main()
        return
    if tk is None:
        print("tkinter is not available; run with --cli for the command-line mode.")
        sys.exit(1)
    root = tk.Tk()
    DownloaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
