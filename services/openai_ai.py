"""Низкоуровневые вызовы OpenAI (чат + картинки). Смена провайдера — правки в этом модуле."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_async_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY не задан")
        _client = AsyncOpenAI(
            api_key=config.OPENAI_API_KEY,
            timeout=config.OPENAI_HTTP_TIMEOUT_SEC,
        )
    return _client


async def chat_json_object(
    system: str,
    user: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    client = get_async_client()
    payload: dict[str, Any] = {
        "model": config.OPENAI_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.65 if temperature is None else temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    resp = await client.chat.completions.create(**payload)
    raw = resp.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("chat_json_object: invalid JSON from model")
        return {}


async def complete_text(system: str, user: str, *, max_tokens: int = 220) -> str:
    client = get_async_client()
    resp = await client.chat.completions.create(
        model=config.OPENAI_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.45,
    )
    return (resp.choices[0].message.content or "").strip()


async def _download(url: str) -> bytes:
    timeout = httpx.Timeout(config.OPENAI_HTTP_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.get(url)
        r.raise_for_status()
        return r.content


async def generate_image_png_bytes(image_prompt: str) -> bytes:
    client = get_async_client()
    prompt = image_prompt.strip()[:4000]
    kwargs: dict[str, Any] = {
        "model": config.OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
    }
    if config.OPENAI_IMAGE_MODEL.startswith("dall-e-3"):
        kwargs["size"] = config.OPENAI_IMAGE_SIZE
        kwargs["quality"] = "standard"
    else:
        kwargs["size"] = "1024x1024"

    resp = await client.images.generate(**kwargs)
    item = resp.data[0]
    if getattr(item, "b64_json", None):
        return base64.b64decode(item.b64_json)
    if getattr(item, "url", None):
        return await _download(item.url)
    raise RuntimeError("images.generate: нет url и b64_json")
