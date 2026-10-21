import os
from openai import OpenAI

BASE_URL = "https://api.aitunnel.ru/v1/"
MODEL = "claude-haiku-5.5"

client = OpenAI(api_key=os.environ["AITUNNEL_API_KEY"], base_url=BASE_URL)

RULES = """Ты менеджер веб-разработчика Влада. Клиенты пишут тебе, когда им нужен сайт или приложение.
Твоя задача: вежливо выяснить, что нужно клиенту (тип сайта, примеры, сроки, есть ли дизайн).
Жёсткие правила:
- Никогда не называй цену, сроки и условия. Если спрашивают, отвечай: "Сейчас уточню у Влада и вернусь".
- Не придумывай факты о работах Влада.
- Пиши коротко, по-человечески, без канцелярита.
- Если клиент злится или просит человека, скажи, что передаёшь Владу."""

# Типичные вопросы клиентов (все выдуманные)
QUESTIONS = [
    "Здравствуйте, нужен сайт для кофейни. Сколько стоит?",
    "А за 3 дня успеете?",
    "Вы точно всё сделаете? Гарантии есть?",
    "Какой-то вы дорогой, давайте скидку",
    "Дайте мне живого человека, вы бот!",
    "Нужен сайт",
]

def ask(text):
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=[
            {"role": "system", "content": RULES},
            {"role": "user", "content": text},
        ],
    )
    return response.choices[0].message.content, response.usage

for q in QUESTIONS:
    answer, usage = ask(q)
    # Предупреждение, если в ответе появились цифры (возможно, цена или срок)
    warn = " <-- ПРОВЕРЬ: есть цифры" if any(ch.isdigit() for ch in answer) else ""
    print(f"КЛИЕНТ: {q}\nБОТ: {answer}{warn}")
    print(f"(токенов: {usage.prompt_tokens} вход / {usage.completion_tokens} выход)\n")