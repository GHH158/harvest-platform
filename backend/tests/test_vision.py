import pytest
from app.config import Settings
from app.vision import VisionService


def test_vision_requires_dashscope_key(tmp_path) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"not-an-image")
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        VisionService(Settings(dashscope_api_key=None)).extract_japanese(image)
