import pytest
from app.config import Settings
from app.omni import omni_url, session_update
from app.prompts import INTERACTIVE_TEACHING_CORE_PROMPT, VOICE_TEACHER_SYSTEM_PROMPT


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
    event = session_update(Settings(dashscope_omni_instructions=""))

    assert event["session"]["input_audio_format"] == "pcm"
    assert event["session"]["output_audio_format"] == "pcm"
    assert event["session"]["turn_detection"]["type"] == "semantic_vad"
    assert event["session"]["turn_detection"]["threshold"] == 0.5
    assert event["session"]["input_audio_transcription"]["model"] == "qwen3-asr-flash-realtime"
    assert event["session"]["instructions"] == VOICE_TEACHER_SYSTEM_PROMPT
    assert event["session"]["instructions"].startswith(INTERACTIVE_TEACHING_CORE_PROMPT)
    assert "为什么这样说 → 关键规则 → 自然说法" in event["session"]["instructions"]
    assert "不要朗读三段式课程" in event["session"]["instructions"]


def test_omni_supplement_cannot_replace_the_formal_prompt() -> None:
    event = session_update(Settings(dashscope_omni_instructions="只聊旅行。"))
    instructions = event["session"]["instructions"]

    assert instructions.startswith(VOICE_TEACHER_SYSTEM_PROMPT)
    assert "只有不与以上正式教学规则冲突时才执行" in instructions
    assert instructions.endswith("只聊旅行。")
