import pytest
from app.config import Settings
from app.omni import omni_url, session_update


def test_omni_url_requires_workspace_websocket() -> None:
    with pytest.raises(RuntimeError, match="DASHSCOPE_OMNI_WS_URL"):
        omni_url(Settings(dashscope_omni_ws_url=None))


def test_omni_url_adds_the_selected_model() -> None:
    settings = Settings(
        dashscope_omni_ws_url="wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        dashscope_omni_model="qwen3.5-omni-flash-realtime",
    )

    assert omni_url(settings).endswith("?model=qwen3.5-omni-flash-realtime")


def test_omni_session_uses_pcm_and_semantic_vad() -> None:
    event = session_update(Settings())

    assert event["session"]["input_audio_format"] == "pcm"
    assert event["session"]["output_audio_format"] == "pcm"
    assert event["session"]["turn_detection"]["type"] == "semantic_vad"
    assert event["session"]["turn_detection"]["threshold"] == 0.5
    assert event["session"]["input_audio_transcription"]["model"] == "qwen3-asr-flash-realtime"
