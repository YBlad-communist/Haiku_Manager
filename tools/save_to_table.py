# Запись результатов в CSV. Файлы кладём только в папку data/.
# Имя файла очищается, чтобы нельзя было выйти за пределы папки.

import csv
import json
import re
from pathlib import Path

import config


# Удобный порядок колонок; остальные добавляются после них.
PREFERRED_COLUMNS = [
    "name", "category", "city", "address", "phone", "website",
    "has_website", "rating", "reviews_count", "source_url", "note",
]

MAX_ROWS_PER_CALL = 15


def _safe_filename(filename: str) -> str:
    name = Path(str(filename)).name
    name = re.sub(r"[^A-Za-zА-Яа-я0-9_.\- ]+", "_", name).strip(" .")
    if not name:
        name = "results.csv"
    if not name.lower().endswith(".csv"):
        name += ".csv"
    return name


def _row_key(row: dict) -> str:
    """Ключ для проверки повторов: название + адрес, иначе вся строка."""
    name = str(row.get("name", "")).strip().lower()
    address = str(row.get("address", "")).strip().lower()
    if name or address:
        return f"{name}|{address}"
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _ordered_columns(columns: set[str]) -> list[str]:
    first = [col for col in PREFERRED_COLUMNS if col in columns]
    rest = sorted(columns - set(first))
    return first + rest


def save_to_table(filename: str, rows: list[dict]) -> dict:
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except json.JSONDecodeError:
            return {"error": "rows пришёл строкой, но это не валидный JSON-массив."}
    if not isinstance(rows, list) or not rows:
        return {"error": "rows должен быть непустым списком объектов."}
    if len(rows) > MAX_ROWS_PER_CALL:
        return {
            "error": (
                f"За один вызов можно сохранить не больше {MAX_ROWS_PER_CALL} строк. "
                "Сохрани частями: сначала 10, потом остальные."
            )
        }

    clean_rows = []
    for row in rows:
        if not isinstance(row, dict):
            return {"error": "Каждая строка должна быть объектом (словарём)."}
        clean_row = {}
        for key, value in row.items():
            column = str(key).strip()
            if not column:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            clean_row[column] = value
        if clean_row:
            clean_rows.append(clean_row)
    if not clean_rows:
        return {"error": "Все строки пустые."}

    path = config.DATA_DIR / _safe_filename(filename)
    columns = set()
    for row in clean_rows:
        columns.update(row.keys())
    ordered = _ordered_columns(columns)

    existing_rows: list[dict] = []
    if path.exists():
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            existing_header = reader.fieldnames or []
            existing_rows = list(reader)
        extra = set(ordered) - set(existing_header)
        if extra:
            return {
                "error": (
                    "В файле уже другие колонки. Новые: "
                    + ", ".join(sorted(extra))
                    + ". Укажи другое имя файла."
                ),
                "file": str(path),
            }
        ordered = existing_header

    seen = {_row_key(row) for row in existing_rows}
    added_rows = []
    skipped = 0
    for row in clean_rows:
        key = _row_key(row)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        added_rows.append(row)

    if not added_rows:
        return {
            "file": str(path),
            "added": 0,
            "skipped_duplicates": skipped,
            "total_rows": len(existing_rows),
        }

    is_new = not path.exists()
    with open(path, "a" if not is_new else "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ordered, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        for row in added_rows:
            writer.writerow({col: row.get(col, "") for col in ordered})

    return {
        "file": str(path),
        "added": len(added_rows),
        "skipped_duplicates": skipped,
        "total_rows": len(existing_rows) + len(added_rows),
        "columns": ordered,
    }
