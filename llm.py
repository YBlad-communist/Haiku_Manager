# Клиент модели. Один вызов = один шаг агента.
# Считает токены и деньги, следит за лимитом на задачу.

import time
from types import SimpleNamespace
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

import config
import safety


class BudgetExceeded(Exception):
    """Закончился лимит токенов на задачу."""


class LLM:
    def __init__(self) -> None:
        if not config.AITUNNEL_API_KEY:
            raise RuntimeError(
                "Не задан AITUNNEL_API_KEY. Впиши ключ в .env (файл в .gitignore)."
            )
        self.client = OpenAI(
            api_key=config.AITUNNEL_API_KEY,
            base_url=config.BASE_URL,
            timeout=config.current_model_timeout(),
            max_retries=0,
        )
        self.model = config.current_model()
        self.on_delta = None
        self.streamed = False
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0
        self.calls = 0
        self.last_prompt_tokens = 0
        self.used_fallback = False
        self.tools_unavailable = False

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def _create(self, kwargs: dict[str, Any]) -> Any:
        """Один вызов API без повторов: без инструментов и без смены модели."""
        return self.client.chat.completions.create(**kwargs)

    def _stream(self, kwargs: dict[str, Any]) -> Any:
        """Потоковый ответ: текст отдаётся по кусочкам, инструменты собираются."""
        params = dict(kwargs)
        params["stream"] = True
        params["stream_options"] = {"include_usage": True}
        content: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage = None
        received = 0
        for chunk in self.client.chat.completions.create(**params):
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            text = getattr(delta, "content", None)
            if text:
                content.append(text)
                received += 1
                if self.on_delta is not None:
                    with_delta = self.on_delta
                    try:
                        with_delta(text)
                    except Exception:  # noqa: BLE001 — сбой окна не должен рвать ответ
                        pass
            for call in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(call, "index", 0) or 0)
                slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(call, "id", None):
                    slot["id"] = call.id
                function = getattr(call, "function", None)
                if function is not None:
                    if getattr(function, "name", None):
                        slot["name"] = function.name
                    if getattr(function, "arguments", None):
                        slot["arguments"] += function.arguments
        self.streamed = received > 0
        tool_calls = [
            SimpleNamespace(
                id=slot["id"] or f"call_{index}",
                type="function",
                function=SimpleNamespace(
                    name=slot["name"], arguments=slot["arguments"] or "{}"
                ),
            )
            for index, slot in sorted(calls.items())
        ]
        message = SimpleNamespace(
            content="".join(content) or None,
            tool_calls=tool_calls or None,
        )
        choice = SimpleNamespace(message=message, finish_reason=finish_reason)
        if usage is None:
            usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)
        return SimpleNamespace(choices=[choice], usage=usage)

    def _send(self, kwargs: dict[str, Any], tools: bool, stream: bool = False) -> Any:
        """Отправляет запрос с повторами, откатом на простой запрос и запасной моделью."""
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return self._stream(kwargs) if stream else self._create(kwargs)
            except APITimeoutError as exc:
                last_error = exc
                safety.log_event("llm_timeout", attempt=attempt)
                if attempt < 3:
                    time.sleep(2 * attempt)
            except (APIConnectionError, RateLimitError) as exc:
                last_error = exc
                safety.log_event(
                    "llm_retry", attempt=attempt, error=type(exc).__name__
                )
                if attempt < 3:
                    time.sleep(2 * attempt)
            except APIError as exc:
                text = str(exc).lower()
                unsupported_tools = (
                    tools
                    and "tool" in text
                    and any(
                        word in text
                        for word in (
                            "not support",
                            "unsupported",
                            "does not support",
                            "unknown parameter",
                            "not allowed",
                        )
                    )
                )
                if unsupported_tools:
                    # Модель не умеет инструменты: отвечаем без них и честно предупреждаем.
                    self.tools_unavailable = True
                    safety.log_event("llm_no_tools", error=safety.redact(str(exc))[:300])
                    plain = {
                        key: value
                        for key, value in kwargs.items()
                        if key not in ("tools", "tool_choice")
                    }
                    return self._create(plain)
                # Ошибки вида "нет доступа к модели" повторять бессмысленно.
                safety.log_event("llm_error", error=safety.redact(str(exc))[:500])
                raise
        if isinstance(last_error, APITimeoutError):
            raise RuntimeError(
                f"Модель не ответила за {config.current_model_timeout()} секунд. "
                "Проверь интернет и нажми «Повторить»."
            )
        raise RuntimeError(
            "Не удалось связаться с моделью после трёх попыток. "
            "Проверь интернет и попробуй ещё раз."
        )

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None):
        """Отправляет сообщения модели. Повторяет при сетевых ошибках."""
        if self.total_tokens + self.last_prompt_tokens >= config.MAX_TASK_TOKENS:
            raise BudgetExceeded(
                f"Лимит {config.MAX_TASK_TOKENS} токенов на задачу исчерпан."
            )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": config.MAX_TOKENS_PER_REPLY,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = config.current_stream_enabled() and bool(
            config.model_info(self.model).get("stream")
        )

        def attempt(use_stream: bool) -> Any:
            self.streamed = False
            try:
                return self._send(kwargs, bool(tools), use_stream)
            except RuntimeError as exc:
                if self.model == config.FALLBACK_MODEL:
                    raise
                # Модель не отвечает: пробуем запасную и честно помечаем это.
                previous = self.model
                self.model = config.FALLBACK_MODEL
                self.used_fallback = True
                safety.log_event(
                    "llm_fallback",
                    failed=previous,
                    used=self.model,
                    error=str(exc)[:200],
                )
                kwargs["model"] = self.model
                try:
                    return self._send(kwargs, bool(tools), use_stream)
                except Exception:
                    self.model = previous
                    raise

        try:
            response = attempt(stream)
        except Exception:
            if not stream or self.streamed:
                raise
            # Поток не поддержался до первого куска текста: обычный запрос.
            safety.log_event("llm_stream_fallback")
            response = attempt(False)

        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = float(
            getattr(usage, "cost_rub", 0.0) or getattr(usage, "cost", 0.0) or 0.0
        )

        self.calls += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost += cost
        self.last_prompt_tokens = prompt_tokens

        safety.log_event(
            "llm_call",
            call=self.calls,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=round(cost, 4),
            total_tokens=self.total_tokens,
            finish_reason=response.choices[0].finish_reason,
            max_tokens=config.MAX_TOKENS_PER_REPLY,
        )

        return response
