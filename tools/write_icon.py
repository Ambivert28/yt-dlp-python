"""Utility to generate app.ico from embedded base64 icon data or a URL."""
from pathlib import Path
import base64
import struct
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icon_data import ICO_BASE64, PNG_BASE64  # noqa: E402

OUTPUT = Path("app.ico")
PNG_OUTPUT = Path("app.png")
ICON_URL = "https://avatars.githubusercontent.com/u/79589310?v=4"

def download_png(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        return response.read()

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

if __name__ == "__main__":
    try:
        png_data = download_png(ICON_URL)
        PNG_OUTPUT.write_bytes(png_data)
        OUTPUT.write_bytes(png_to_ico(png_data))
        print(f"Wrote {OUTPUT} from {ICON_URL}")
    except Exception:
        data = base64.b64decode(ICO_BASE64)
        OUTPUT.write_bytes(data)
        PNG_OUTPUT.write_bytes(base64.b64decode(PNG_BASE64))
        print(f"Wrote {OUTPUT} from embedded data")
