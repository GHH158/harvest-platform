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
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    direct_hls_compatible: bool = False


class VideoDownloader:
    """Download one user-supplied video URL into the local archive boundary."""

    def __init__(
        self,
        *,
        max_bytes: int,
        min_free_bytes: int,
        max_height: int = 720,
        max_fps: int = 30,
    ) -> None:
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.max_height = max_height
        self.max_fps = max_fps
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def download(self, url: str, destination_directory: Path) -> DownloadedVideo:
        destination_directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination_directory).free < self.min_free_bytes:
            raise RuntimeError("本机磁盘空间不足，暂不能下载视频。")
        video_filter = f"[height<=?{self.max_height}][fps<=?{self.max_fps}]"
        options: dict[str, Any] = {
            # The product keeps at most 720p. Restricting the source here avoids
            # downloading and software-decoding 4K AV1 only to discard 8/9 of it.
            # Unknown height/fps is accepted for extractors with incomplete metadata.
            "format": f"bestvideo*{video_filter}+bestaudio/best{video_filter}",
            "format_sort": [
                "vcodec:h264",
                f"res:{self.max_height}",
                f"fps:{self.max_fps}",
                "acodec:aac",
            ],
            "format_sort_force": True,
            "merge_output_format": "mp4",
            "outtmpl": str(destination_directory / "source.%(ext)s"),
            # noplaylist 保证 URL 即使指向播放列表也只处理第一个视频。
            # 不要设置 max_downloads:yt-dlp 达到上限后即使下载成功也会抛
            # DownloadCancelled("Maximum number of downloads reached"),会让所有链接都失败。
            "noplaylist": True,
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
        selected = self._selected_video_format(info)
        height = self._optional_int(selected.get("height"))
        fps = self._optional_float(selected.get("fps"))
        vcodec = str(selected.get("vcodec") or "").strip() or None
        normalized_vcodec = (vcodec or "").lower()
        direct_hls_compatible = (
            normalized_vcodec.startswith(("avc1", "h264"))
            and (height is None or height <= self.max_height)
            and (fps is None or fps <= self.max_fps)
        )
        return DownloadedVideo(
            path=source,
            title=title[:160],
            height=height,
            fps=fps,
            vcodec=vcodec,
            direct_hls_compatible=direct_hls_compatible,
        )

    @staticmethod
    def _selected_video_format(info: dict[str, Any]) -> dict[str, Any]:
        requested = info.get("requested_formats")
        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict) and str(item.get("vcodec", "none")) != "none":
                    return item
        return info

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class VideoProcessor:
    """Local P5 media boundary; cloud upload/ASR is deliberately separate."""

    segment_seconds = 6

    def __init__(self, *, max_threads: int = 2, max_height: int = 720) -> None:
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.max_threads = max_threads
        self.max_height = max_height

    def create_hls(
        self,
        source: Path,
        video_directory: Path,
        audio_directory: Path,
        *,
        direct_video_copy: bool = False,
    ) -> str:
        """Create independent 6-second VOD segments for watch and shadowing modes."""
        for directory in (video_directory, audio_directory):
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
        video_mode = self._video_hls(source, video_directory, direct_video_copy=direct_video_copy)
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
        return video_mode

    def create_thumbnail(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        arguments = (
            "-y",
            "-ss",
            "1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(640,iw)':-2",
            "-q:v",
            "3",
            str(destination),
        )
        try:
            self._run(*arguments)
        except RuntimeError:
            # Very short clips may not have a frame at one second.
            self._run(
                "-y",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(640,iw)':-2",
                "-q:v",
                "3",
                str(destination),
            )

    def _video_hls(self, source: Path, video_directory: Path, *, direct_video_copy: bool) -> str:
        """Encode the 720p video HLS using the hardware Media Engine (VideoToolbox),
        which is ~10x faster and uses far less CPU than software x264. Falls back to
        a fast software preset if the hardware encoder is unavailable."""
        if direct_video_copy:
            try:
                self._run_video_copy(source, video_directory)
                return "copy"
            except RuntimeError:
                self._reset_directory(video_directory)

        attempts = [
            (
                "videotoolbox",
                ["-hwaccel", "videotoolbox"],
                ["-c:v", "h264_videotoolbox"],
            ),
            (
                "videotoolbox-software-decode",
                ["-threads", str(self.max_threads)],
                ["-c:v", "h264_videotoolbox"],
            ),
            (
                "software",
                ["-threads", str(self.max_threads)],
                ["-c:v", "libx264", "-preset", "veryfast", "-threads", str(self.max_threads)],
            ),
        ]
        last_error: RuntimeError | None = None
        for mode, input_args, codec_args in attempts:
            try:
                self._run(
                    "-y",
                    *input_args,
                    "-i",
                    str(source),
                    "-filter_threads",
                    str(self.max_threads),
                    "-vf",
                    f"scale=-2:min({self.max_height}\\,ih)",
                    *codec_args,
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
                return mode
            except RuntimeError as error:
                last_error = error
                self._reset_directory(video_directory)
        assert last_error is not None
        raise last_error

    def _run_video_copy(self, source: Path, video_directory: Path) -> None:
        self._run(
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
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

    @staticmethod
    def _reset_directory(directory: Path) -> None:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    def extract_audio(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run("-y", "-i", str(source), "-vn", "-ac", "1", "-c:a", "aac", str(destination))

    def _run(self, *arguments: str) -> None:
        result = subprocess.run([self.ffmpeg, *arguments], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 处理失败: {result.stderr[-800:]}")
