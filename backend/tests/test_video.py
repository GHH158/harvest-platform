import subprocess
import tempfile
from pathlib import Path

import pytest
from app.video import VideoDownloader, VideoProcessor, _trim_arguments


def test_video_processor_uses_project_local_ffmpeg() -> None:
    assert VideoProcessor().ffmpeg


def test_video_processor_creates_six_second_hls_playlists(tmp_path: Path) -> None:
    processor = VideoProcessor()
    source = tmp_path / "source.mp4"
    generated = subprocess.run(
        [
            processor.ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "7",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr[-1_000:]

    video_directory = tmp_path / "video"
    audio_directory = tmp_path / "audio"
    processor.create_hls(source, video_directory, audio_directory)

    for directory in (video_directory, audio_directory):
        playlist = (directory / "index.m3u8").read_text()
        assert "#EXT-X-PLAYLIST-TYPE:VOD" in playlist
        assert "#EXT-X-ENDLIST" in playlist
        assert list(directory.glob("segment-*.ts"))

    stale = video_directory / "segment-99999.ts"
    stale.write_bytes(b"stale")
    processor.create_hls(source, video_directory, audio_directory)
    assert not stale.exists()


def test_video_downloader_uses_single_video_and_returns_downloaded_title(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def extract_info(self, url: str, download: bool) -> dict:
            (tmp_path / "source.mp4").write_bytes(b"video")
            return {
                "title": "雨の日",
                "requested_formats": [
                    {"height": 720, "fps": 30, "vcodec": "avc1.64001f"},
                    {"acodec": "mp4a.40.2", "vcodec": "none"},
                ],
            }

    monkeypatch.setattr("app.video.yt_dlp.YoutubeDL", FakeYoutubeDL)

    result = VideoDownloader(max_bytes=100, min_free_bytes=0).download(
        "https://example.com/video", tmp_path
    )

    assert result.path == tmp_path / "source.mp4"
    assert result.title == "雨の日"
    assert result.height == 720
    assert result.fps == 30
    assert result.vcodec == "avc1.64001f"
    assert result.direct_hls_compatible is True
    assert captured["noplaylist"] is True
    assert captured["max_filesize"] == 100
    assert "height<=?720" in captured["format"]
    assert "fps<=?30" in captured["format"]
    assert captured["format_sort"][:3] == ["vcodec:h264", "res:720", "fps:30"]
    assert captured["format_sort_force"] is True


def test_video_processor_directly_packages_compatible_h264(monkeypatch, tmp_path: Path) -> None:
    processor = VideoProcessor(max_threads=2)
    calls: list[tuple[str, ...]] = []

    def record(*arguments: str) -> None:
        calls.append(arguments)

    monkeypatch.setattr(processor, "_run", record)

    mode = processor._video_hls(
        tmp_path / "source.mp4",
        tmp_path / "video",
        direct_video_copy=True,
    )

    assert mode == "copy"
    assert "copy" in calls[0]
    assert "-vf" not in calls[0]


def test_video_processor_limits_software_fallback_threads(monkeypatch, tmp_path: Path) -> None:
    processor = VideoProcessor(max_threads=2)
    calls: list[tuple[str, ...]] = []

    def fail_hardware(*arguments: str) -> None:
        calls.append(arguments)
        if len(calls) < 3:
            raise RuntimeError("hardware unavailable")

    monkeypatch.setattr(processor, "_run", fail_hardware)

    mode = processor._video_hls(
        tmp_path / "source.mp4",
        tmp_path / "video",
        direct_video_copy=False,
    )

    assert mode == "software"
    assert "videotoolbox" in calls[0]
    assert calls[1][calls[1].index("-threads") + 1] == "2"
    assert calls[2].count("-threads") == 2
    assert all(calls[2][index + 1] == "2" for index, value in enumerate(calls[2]) if value == "-threads")


# --- §15: cutting one section out of a longer source ---


def test_trim_arguments_use_input_seek_and_duration() -> None:
    """§15.4 / `_trim_arguments`: `-ss` before `-i` and `-t` rather than `-to`.

    After an input seek the output timeline restarts at zero, so `-to` would be measured
    against the original clock and cut the wrong amount.
    """

    assert _trim_arguments(None, None) == ()
    assert _trim_arguments(0, 5_000) == ("-t", "5.000")
    assert _trim_arguments(304_000, 621_000) == ("-ss", "304.000", "-t", "317.000")
    # Open-ended last section: seek in, read to EOF.
    assert _trim_arguments(621_000, None) == ("-ss", "621.000")


def test_a_zero_or_negative_window_is_rejected_not_silently_encoded() -> None:
    with pytest.raises(ValueError, match="正的时长"):
        _trim_arguments(5_000, 5_000)
    with pytest.raises(ValueError, match="正的时长"):
        _trim_arguments(9_000, 5_000)


def test_a_windowed_cut_never_uses_stream_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """§15.4. Note the *reason*, which was corrected by measurement on 2026-08-11: with
    ffmpeg 7.1 an input-side `-ss` plus `-c copy` is already frame-accurate (a 13.5s cut of
    a 30s source gave exactly 16.50s), so the old "it slides to the nearest keyframe"
    justification does not hold. What does hold is that a copy cut starts on a non-keyframe
    (`iskey:0`), and HLS segments must start at keyframes — so packaging it needs a
    re-encode anyway. The guard below is what keeps that true.
    """

    transcoder = VideoProcessor()
    seen: list[dict[str, object]] = []

    def fake_video_hls(source, video_directory, *, direct_video_copy, window=()):
        seen.append({"direct_video_copy": direct_video_copy, "window": window})
        return "software"

    monkeypatch.setattr(transcoder, "_video_hls", fake_video_hls)
    monkeypatch.setattr(transcoder, "_run", lambda *arguments: None)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        transcoder.create_hls(
            root / "source.mp4",
            root / "video",
            root / "audio",
            direct_video_copy=True,
            start_ms=304_000,
            end_ms=621_000,
        )
    assert seen[0]["direct_video_copy"] is False
    assert seen[0]["window"] == ("-ss", "304.000", "-t", "317.000")


def test_without_a_window_stream_copy_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The link-download path must keep its fast no-re-encode packaging (§3.4)."""

    transcoder = VideoProcessor()
    seen: list[bool] = []
    monkeypatch.setattr(
        transcoder,
        "_video_hls",
        lambda source, directory, *, direct_video_copy, window=(): (
            seen.append(direct_video_copy) or "copy"
        ),
    )
    monkeypatch.setattr(transcoder, "_run", lambda *arguments: None)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        transcoder.create_hls(
            root / "source.mp4", root / "video", root / "audio", direct_video_copy=True
        )
    assert seen == [True]
