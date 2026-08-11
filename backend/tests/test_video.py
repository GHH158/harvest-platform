import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from app.video import (
    HLSBundleError,
    VideoDownloader,
    VideoProcessor,
    _trim_arguments,
    _trim_placement,
    is_hls_playlist,
    unpack_hls_bundle,
)


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

    def fake_video_hls(source, video_directory, *, direct_video_copy, window_in=(), window_out=()):
        seen.append(
            {"direct_video_copy": direct_video_copy, "window_in": window_in, "window_out": window_out}
        )
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
    # A real file trims on the input side.
    assert seen[0]["window_in"] == ("-ss", "304.000", "-t", "317.000")
    assert seen[0]["window_out"] == ()


def test_without_a_window_stream_copy_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The link-download path must keep its fast no-re-encode packaging (§3.4)."""

    transcoder = VideoProcessor()
    seen: list[bool] = []
    monkeypatch.setattr(
        transcoder,
        "_video_hls",
        lambda source, directory, *, direct_video_copy, window_in=(), window_out=(): (
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


def test_hls_sources_are_detected_by_content_not_extension(tmp_path: Path) -> None:
    """§15.10. A downloaded bundle may keep `.m3u8`/`.ts`, may have every extension
    stripped, or may just have iOS hiding them — the bytes are the only reliable signal."""

    playlist = tmp_path / "play"
    playlist.write_text("#EXTM3U\n#EXT-X-VERSION:3\n", encoding="utf-8")
    assert is_hls_playlist(playlist) is True

    named = tmp_path / "play.m3u8"
    named.write_text("#EXTM3U\n", encoding="utf-8")
    assert is_hls_playlist(named) is True

    movie = tmp_path / "clip.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert is_hls_playlist(movie) is False
    assert is_hls_playlist(tmp_path / "missing.mp4") is False


def test_hls_trims_on_the_output_side_and_plain_files_on_the_input_side(tmp_path: Path) -> None:
    """The measured difference (§15.10), and the reason this is not a stylistic choice.

    Input-side `-ss` on an HLS playlist seeks to the start of the segment containing the
    timestamp: a 13.5s cut came out the right length but starting at 0s. Moving `-ss` after
    `-i` made the same cut start exactly where it should.
    """

    playlist = tmp_path / "play"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")
    movie = tmp_path / "clip.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    hls_in, hls_out = _trim_placement(playlist, 13_500, 20_000)
    assert hls_in == ("-f", "hls", "-allowed_extensions", "ALL")
    assert hls_out == ("-ss", "13.500", "-t", "6.500")

    plain_in, plain_out = _trim_placement(movie, 13_500, 20_000)
    assert plain_in == ("-ss", "13.500", "-t", "6.500")
    assert plain_out == ()

    # No window at all stays untouched on both sides.
    assert _trim_placement(movie, None, None) == ((), ())


def test_thumbnail_fallback_keeps_the_hls_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real split left one section with no cover: the first attempt missed and the retry
    dropped `-f hls -allowed_extensions ALL`, so it could not open the playlist at all."""

    playlist = tmp_path / "play"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")
    processor = VideoProcessor()
    calls: list[tuple[str, ...]] = []

    def failing_run(*arguments: str) -> None:
        calls.append(arguments)
        if len(calls) == 1:
            raise RuntimeError("no frame there")

    monkeypatch.setattr(processor, "_run", failing_run)
    processor.create_thumbnail(playlist, tmp_path / "cover.jpg", at_ms=20_000)

    assert len(calls) == 2
    for arguments in calls:
        assert "-f" in arguments and "hls" in arguments
        assert "-allowed_extensions" in arguments
    # The retry drops only the seek, nothing else.
    assert "-ss" in calls[0]
    assert "-ss" not in calls[1]


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in members.items():
            bundle.writestr(name, content)
    return path


def test_unpack_hls_bundle_finds_the_playlist_by_content_not_extension(tmp_path: Path) -> None:
    # §15.10/§15.11: a downloader may strip every extension, so the playlist has to be
    # found by its first bytes (`#EXTM3U`), not by a `.m3u8` name.
    archive = _write_zip(
        tmp_path / "pending-abc.zip",
        {
            "play": b"#EXTM3U\n#EXTINF:6,\nTZhO-00000\n#EXT-X-ENDLIST\n",
            "TZhO-00000": b"segment-bytes",
        },
    )

    playlist = unpack_hls_bundle(archive)

    assert playlist.name == "play"
    assert playlist.read_text(encoding="utf-8").startswith("#EXTM3U")
    assert (playlist.parent / "TZhO-00000").read_bytes() == b"segment-bytes"


def test_unpack_hls_bundle_rejects_a_zip_slip_member(tmp_path: Path) -> None:
    # The zip is client-supplied input (directly, or relayed through OSS since §15.11) —
    # a `../` entry must not be able to write outside the extracted directory.
    archive = tmp_path / "pending-evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("play.m3u8", "#EXTM3U\n")
        bundle.writestr("../../etc/escape.ts", b"nope")

    with pytest.raises(HLSBundleError, match="结构不对"):
        unpack_hls_bundle(archive)


def test_unpack_hls_bundle_rejects_a_bundle_without_any_playlist(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "pending-noplaylist.zip", {"segment-00000.ts": b"not a playlist"})

    with pytest.raises(HLSBundleError, match="没有播放列表"):
        unpack_hls_bundle(archive)


def test_unpack_hls_bundle_rejects_a_corrupt_zip(tmp_path: Path) -> None:
    archive = tmp_path / "pending-corrupt.zip"
    archive.write_bytes(b"not actually a zip file")

    with pytest.raises(HLSBundleError, match="读不出来"):
        unpack_hls_bundle(archive)
