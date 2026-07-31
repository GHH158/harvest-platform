from app.video import VideoProcessor


def test_video_processor_uses_project_local_ffmpeg() -> None:
    assert VideoProcessor().ffmpeg
