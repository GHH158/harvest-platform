from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg


class VideoProcessor:
    """Local P5 media boundary; cloud upload/ASR is deliberately separate."""

    def __init__(self) -> None:
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def transcode_delivery(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run("-y", "-i", str(source), "-vf", "scale=-2:720", "-b:v", "1500k", "-c:a", "aac", str(destination))

    def extract_audio(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run("-y", "-i", str(source), "-vn", "-ac", "1", "-c:a", "aac", str(destination))

    def _run(self, *arguments: str) -> None:
        result = subprocess.run([self.ffmpeg, *arguments], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 处理失败: {result.stderr[-800:]}")
