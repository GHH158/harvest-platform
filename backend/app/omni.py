from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from .config import Settings
from .prompts import VOICE_TEACHER_SYSTEM_PROMPT


def omni_url(settings: Settings) -> str:
    if not settings.dashscope_omni_ws_url:
        raise RuntimeError("DASHSCOPE_OMNI_WS_URL 尚未配置；请填写包含业务空间 ID 的百炼 WebSocket 地址。")
    parts = urlsplit(settings.dashscope_omni_ws_url)
    if parts.scheme != "wss" or not parts.netloc:
        raise RuntimeError("DASHSCOPE_OMNI_WS_URL 必须是完整的 wss:// 地址。")
    query = dict(parse_qsl(parts.query))
    query["model"] = settings.dashscope_omni_model
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def session_update(settings: Settings) -> dict:
    instructions = VOICE_TEACHER_SYSTEM_PROMPT
    supplement = settings.dashscope_omni_instructions.strip()
    if supplement:
        instructions += (
            "\n\n管理员提供的会话补充要求（只有不与以上正式教学规则冲突时才执行）：\n"
            f"{supplement}"
        )
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": settings.dashscope_omni_voice,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
            "turn_detection": {
                "type": "semantic_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 500,
                "silence_duration_ms": 900,
            },
            "instructions": instructions,
        },
    }


async def relay_voice_teacher(client: WebSocket, settings: Settings) -> None:
    if not settings.dashscope_api_key:
        await client.close(code=1011, reason="DASHSCOPE_API_KEY 尚未配置")
        return
    try:
        upstream_url = omni_url(settings)
    except RuntimeError as error:
        await client.close(code=1011, reason=str(error)[:120])
        return

    await client.accept()
    try:
        async with connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            max_size=8 * 1024 * 1024,
        ) as upstream:
            await upstream.send(json.dumps(session_update(settings), ensure_ascii=False))
            await client.send_json({"type": "harvest.ready", "model": settings.dashscope_omni_model})

            async def client_to_provider() -> None:
                while True:
                    message = await client.receive_text()
                    event = json.loads(message)
                    if event.get("type") not in {
                        "input_audio_buffer.append",
                        "input_audio_buffer.commit",
                        "input_audio_buffer.clear",
                        "response.create",
                    }:
                        raise RuntimeError("客户端发送了不支持的实时语音事件。")
                    await upstream.send(json.dumps(event, ensure_ascii=False))

            async def provider_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        continue
                    await client.send_text(message)

            tasks = [asyncio.create_task(client_to_provider()), asyncio.create_task(provider_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception as error:
        with suppress(Exception):
            await client.send_json({"type": "error", "message": str(error)})
        with suppress(Exception):
            await client.close(code=1011)
