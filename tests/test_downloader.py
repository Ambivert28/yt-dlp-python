"""Unit tests for the pure (non-GUI) helpers in downloader.py."""
import base64
from pathlib import Path

import pytest

import downloader as d


def test_read_urls_from_text_filters_blanks_and_comments():
    text = "https://a\n\n  # comment\nhttps://b  \n#another\n"
    assert d.read_urls_from_text(text) == ["https://a", "https://b"]


def test_build_command_audio_defaults():
    fmt = d.OUTPUT_FORMATS[0]  # MP3 320k
    cmd = d.build_command("https://x", Path("/out"), fmt, "playlist")
    assert cmd[-1] == "https://x"
    assert "--extract-audio" in cmd
    assert "--continue" in cmd
    assert "--retries" in cmd
    # output template avoids same-title overwrites
    assert any("%(id)s" in part for part in cmd)
    # bitrate from preset is applied
    assert "320K" in cmd


def test_build_command_single_adds_no_playlist():
    fmt = d.OUTPUT_FORMATS[0]
    cmd = d.build_command("https://x", Path("/out"), fmt, "single")
    assert "--no-playlist" in cmd
    assert cmd[-1] == "https://x"


def test_build_command_video_only():
    fmt = next(f for f in d.OUTPUT_FORMATS if f["video_only"])
    cmd = d.build_command("https://x", Path("/out"), fmt, "playlist")
    assert "--no-embed-thumbnail" in cmd
    assert "--extract-audio" not in cmd


def test_build_command_custom_fragments():
    fmt = d.OUTPUT_FORMATS[0]
    cmd = d.build_command("https://x", Path("/out"), fmt, "playlist", fragments=8)
    # -N and --concurrent-fragments both use the requested value
    assert cmd[cmd.index("-N") + 1] == "8"
    assert cmd[cmd.index("--concurrent-fragments") + 1] == "8"


def test_expected_sha256_parses_starred_and_plain():
    text = (
        "aaaa1111  yt-dlp\n"
        "bbbb2222 *yt-dlp.exe\n"
        "cccc3333  yt-dlp_macos\n"
    )
    assert d.expected_sha256(text, "yt-dlp.exe") == "bbbb2222"
    assert d.expected_sha256(text, "yt-dlp_macos") == "cccc3333"
    assert d.expected_sha256(text, "missing") is None


def test_png_to_ico_roundtrip_and_validation():
    png = base64.b64decode(d.PNG_BASE64)
    ico = d.png_to_ico(png)
    # ICO header: reserved=0, type=1 (icon)
    assert ico[0:4] == b"\x00\x00\x01\x00"
    # embedded PNG payload is preserved at the documented offset
    assert ico[22:].startswith(b"\x89PNG")
    with pytest.raises(ValueError):
        d.png_to_ico(b"not-a-png")
