# Запуск из консоли:
#   python main.py "найди кофейни в Казани без сайта и сохрани в таблицу"
#
# Первая версия ничего не отправляет: только поиск, чтение страниц, 2ГИС и CSV.

import argparse
import sys

# Чтобы русский текст нормально печатался в консоли Windows.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import agent
import config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ИИ-помощник: клиенты, цены, информация, черновики предложений."
    )
    parser.add_argument(
        "task",
        nargs="+",
        help="Задача обычными словами, в кавычках",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=config.MAX_STEPS,
        help=f"Максимум шагов (по умолчанию {config.MAX_STEPS})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Показывать только итоговый ответ",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task = " ".join(args.task).strip()

    if not config.AITUNNEL_API_KEY:
        print("Не задан AITUNNEL_API_KEY.")
        print("Впиши ключ в файл .env в папке проекта (он в .gitignore) и запусти снова.")
        return 1

    result = agent.run(task, verbose=not args.quiet, max_steps=args.steps)

    if not args.quiet:
        print()
    print(result["answer"])
    print()
    print(
        f"[шагов: {result['steps']} | токенов: {result['tokens']} | "
        f"цена: ~{result['cost']:.2f} ₽ | статус: {result['stopped_reason']}]"
    )
    print(f"[журнал: {config.LOGS_DIR / 'agent.log'}]")

    return 0 if result["stopped_reason"] in ("done", "max_steps") else 1


if __name__ == "__main__":
    raise SystemExit(main())
