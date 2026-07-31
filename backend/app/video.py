from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg


class VideoProcessor:
    """Local P5 media boundary; cloud upload/ASR is deliberately separate."""

    segment_seconds = 6

    def __init__(self) -> None:
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def create_hls(self, source: Path, video_directory: Path, audio_directory: Path) -> None:
        """Create independent 6-second VOD segments for watch and shadowing modes."""
        for directory in (video_directory, audio_directory):
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
        self._run(
            "-y",
            "-i",
            str(source),
            "-vf",
            "scale=-2:720",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-b:v",
            "1500k",
            "-maxrate",
            "1800k",
            "-bufsize",
            "3000k",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-force_key_frames",
            f"expr:gte(t,n_forced*{self.segment_seconds})",
            "-f",
            "hls",
            "-hls_time",
            str(self.segment_seconds),
            "-hls_playlist_type",
            "vod",
            "-hls_flags",
            "independent_segments",
            "-hls_segment_filename",
            str(video_directory / "segment-%05d.ts"),
            str(video_directory / "index.m3u8"),
        )
        self._run(
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-f",
            "hls",
            "-hls_time",
            str(self.segment_seconds),
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            str(audio_directory / "segment-%05d.ts"),
            str(audio_directory / "index.m3u8"),
        )

    def extract_audio(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run("-y", "-i", str(source), "-vn", "-ac", "1", "-c:a", "aac", str(destination))

    def _run(self, *arguments: str) -> None:
        result = subprocess.run([self.ffmpeg, *arguments], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 处理失败: {result.stderr[-800:]}")
