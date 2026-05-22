"""Низкоуровневые вызовы OpenAI (чат + картинки). Смена провайдера — правки в этом модуле."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI, BadRequestError

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


def image_model_candidates() -> list[str]:
    """Уникальный список моделей для images.generate (основная + fallback)."""
    seen: set[str] = set()
    out: list[str] = []
    for name in (config.OPENAI_IMAGE_MODEL, *config.OPENAI_IMAGE_FALLBACK_MODELS):
        n = (name or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _image_generate_kwargs(model: str, prompt: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }
    if model.startswith("dall-e-3"):
        kwargs["size"] = config.OPENAI_IMAGE_SIZE
        kwargs["quality"] = "standard"
    else:
        kwargs["size"] = "1024x1024"
    return kwargs


def _is_model_unavailable_error(exc: BaseException) -> bool:
    if not isinstance(exc, BadRequestError):
        return False
    msg = str(exc).lower()
    return (
        "does not exist" in msg
        or "invalid_value" in msg
        or "model" in msg and "not found" in msg
    )


async def _generate_with_model(client: AsyncOpenAI, model: str, prompt: str) -> bytes:
    resp = await client.images.generate(**_image_generate_kwargs(model, prompt))
    item = resp.data[0]
    if getattr(item, "b64_json", None):
        return base64.b64decode(item.b64_json)
    if getattr(item, "url", None):
        return await _download(item.url)
    raise RuntimeError("images.generate: нет url и b64_json")


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
    models = image_model_candidates()
    if not models:
        raise RuntimeError("не задана ни одна модель для images.generate")

    last_exc: BaseException | None = None
    for model in models:
        try:
            return await _generate_with_model(client, model, prompt)
        except BadRequestError as exc:
            last_exc = exc
            if _is_model_unavailable_error(exc):
                logger.warning(
                    "images.generate: модель %s недоступна (%s), пробуем следующую",
                    model,
                    exc,
                )
                continue
            raise
        except Exception as exc:
            last_exc = exc
            raise

    raise RuntimeError(
        f"images.generate: ни одна модель не сработала ({', '.join(models)}): {last_exc}"
    )


async def probe_image_models_at_startup() -> str | None:
    """
    Короткая проверка доступности image API при старте.
    Возвращает имя рабочей модели или None.
    """
    if not config.OPENAI_API_KEY:
        return None
    client = get_async_client()
    probe_prompt = "A simple white plate on a wooden table, food photography."
    for model in image_model_candidates():
        try:
            await _generate_with_model(client, model, probe_prompt)
            logger.info("OpenAI images: рабочая модель %s", model)
            return model
        except BadRequestError as exc:
            if _is_model_unavailable_error(exc):
                logger.warning("OpenAI images: модель %s недоступна при старте: %s", model, exc)
                continue
            logger.warning("OpenAI images: probe %s failed: %s", model, exc)
        except Exception as exc:
            logger.warning("OpenAI images: probe %s failed: %s", model, exc)
    logger.warning(
        "OpenAI images: ни одна модель из %s не прошла проверку — "
        "«Рецепт дня» и картинки блюд будут без фото. "
        "Задайте OPENAI_IMAGE_MODEL=gpt-image-1 (или dall-e-2) в .env и перезапустите сервис.",
        ", ".join(image_model_candidates()),
    )
    return None
