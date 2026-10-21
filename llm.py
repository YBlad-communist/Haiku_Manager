# Клиент модели. Один вызов = один шаг агента.
# Считает токены и деньги, следит за лимитом на задачу.

import time
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
        )
        self.model = config.current_model()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0
        self.calls = 0
        self.last_prompt_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

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

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
                last_error = exc
                safety.log_event(
                    "llm_retry", attempt=attempt, error=type(exc).__name__
                )
                if attempt < 3:
                    time.sleep(2 * attempt)
            except APIError as exc:
                # Ошибки вида "нет доступа к модели" повторять бессмысленно.
                safety.log_event("llm_error", error=safety.redact(str(exc))[:500])
                raise
        else:
            raise RuntimeError(f"Модель недоступна после 3 попыток: {last_error}")

        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = float(getattr(usage, "cost", 0.0) or 0.0)

        self.calls += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost += cost
        self.last_prompt_tokens = prompt_tokens

        safety.log_event(
            "llm_call",
            call=self.calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=round(cost, 4),
            total_tokens=self.total_tokens,
            finish_reason=response.choices[0].finish_reason,
            max_tokens=config.MAX_TOKENS_PER_REPLY,
        )

        return response
