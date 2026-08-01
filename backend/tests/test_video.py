import subprocess
from pathlib import Path

from app.video import VideoDownloader, VideoProcessor


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
            return {"title": "雨の日"}

    monkeypatch.setattr("app.video.yt_dlp.YoutubeDL", FakeYoutubeDL)

    result = VideoDownloader(max_bytes=100, min_free_bytes=0).download(
        "https://example.com/video", tmp_path
    )

    assert result.path == tmp_path / "source.mp4"
    assert result.title == "雨の日"
    assert captured["noplaylist"] is True
    assert captured["max_filesize"] == 100
