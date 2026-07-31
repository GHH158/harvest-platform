import subprocess
from pathlib import Path

from app.video import VideoProcessor


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
