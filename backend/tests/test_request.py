import pytest
from app.main import MaterialCreate
from pydantic import ValidationError


def test_material_request_requires_one_source() -> None:
    with pytest.raises(ValidationError, match="二选一"):
        MaterialCreate()

    with pytest.raises(ValidationError, match="二选一"):
        MaterialCreate(text="本文。", url="https://example.com")

    assert MaterialCreate(text="本文。").text == "本文。"
