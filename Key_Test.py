# Простая проверка связи с моделью.
# Ключ берётся только из .env / переменных окружения и на экран не выводится.

import config
from openai import OpenAI


def main() -> None:
    if not config.AITUNNEL_API_KEY:
        print("Не задан AITUNNEL_API_KEY. Впиши его в .env.")
        return

    client = OpenAI(api_key=config.AITUNNEL_API_KEY, base_url=config.BASE_URL)
    response = client.chat.completions.create(
        model=config.MODEL,
        max_tokens=50,
        messages=[{"role": "user", "content": "Ответь одним словом: работаешь?"}],
    )
    print("ОТВЕТ:", response.choices[0].message.content)
    print(
        "Токенов:",
        response.usage.prompt_tokens,
        "вход /",
        response.usage.completion_tokens,
        "выход",
    )


if __name__ == "__main__":
    main()
