from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import yt_dlp


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    title: str


class VideoDownloader:
    """Download one user-supplied video URL into the local archive boundary."""

    def __init__(self, *, max_bytes: int, min_free_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def download(self, url: str, destination_directory: Path) -> DownloadedVideo:
        destination_directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination_directory).free < self.min_free_bytes:
            raise RuntimeError("本机磁盘空间不足，暂不能下载视频。")
        options: dict[str, Any] = {
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": str(destination_directory / "source.%(ext)s"),
            "noplaylist": True,
            "max_downloads": 1,
            "max_filesize": self.max_bytes,
            "continuedl": True,
            "overwrites": False,
            "quiet": True,
            "no_warnings": True,
            "ffmpeg_location": self.ffmpeg,
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp 没有返回视频信息。")
        candidates = [
            path
            for path in destination_directory.iterdir()
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise RuntimeError("yt-dlp 没有生成可处理的视频文件。")
        source = max(candidates, key=lambda item: item.stat().st_mtime_ns)
        if source.stat().st_size > self.max_bytes:
            source.unlink(missing_ok=True)
            raise RuntimeError("下载的视频超过允许的大小。")
        if shutil.disk_usage(destination_directory).free < self.min_free_bytes:
            source.unlink(missing_ok=True)
            raise RuntimeError("下载后本机剩余磁盘空间低于保护阈值，文件已移除。")
        title = str(info.get("title") or source.stem).strip()
        return DownloadedVideo(path=source, title=title[:160])


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
