# Чтение документов: общий код для инструментов и вложений.
# Форматы: .docx, .xlsx (openpyxl/python-docx) и .pdf (pypdf).
# Макросы и старые форматы (.doc, .xlsm) запрещены — проверка в policy.py.

from pathlib import Path

import policy


MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_SHEETS = 20
MAX_ROWS = 2000
MAX_COLUMNS = 30
MAX_CHARS = 20_000
MAX_PDF_PAGES = 100

ALLOWED_EXTENSIONS = (".docx", ".xlsx", ".pdf")


def library_missing(package: str, version: str) -> str:
    return (
        f"Нужен пакет {package}=={version}. Он ещё не установлен — "
        "скажи Омеге, и мы поставим его с твоего подтверждения."
    )


def check_file(target: Path) -> str:
    """Проверяет расширение, размер и доступность файла. Пусто — всё в порядке."""
    suffix = target.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return "Поддерживаются только .docx, .xlsx и .pdf."
    if not target.exists():
        return "Такого файла нет."
    if not target.is_file():
        return "Это не файл."
    try:
        size = target.stat().st_size
    except OSError as exc:
        return f"Не удалось проверить файл: {exc}"
    if size > MAX_FILE_BYTES:
        return (
            f"Файл слишком большой: {policy.human_size(size)}. "
            f"Максимум {policy.human_size(MAX_FILE_BYTES)}."
        )
    return ""


def read_docx(target: Path) -> dict:
    """Читает Word-документ: абзацы и таблицы."""
    try:
        import docx  # noqa: PLC0415
    except ImportError:
        return {"error": library_missing("python-docx", "1.2.0")}
    try:
        document = docx.Document(str(target))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Не удалось прочитать документ: {exc}"}

    paragraphs: list[str] = []
    total = 0
    truncated = False
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        paragraphs.append(text)
        total += len(text)
        if total > MAX_CHARS:
            truncated = True
            break

    tables = []
    for table in document.tables[:MAX_SHEETS]:
        rows = []
        for row in table.rows[:MAX_ROWS]:
            rows.append([(cell.text or "").strip() for cell in row.cells])
        tables.append(rows)

    return {
        "path": str(target),
        "type": "docx",
        "paragraphs": len(paragraphs),
        "tables": len(tables),
        "text": "\n".join(paragraphs)[:MAX_CHARS],
        "table_rows": tables,
        "truncated": truncated,
    }


def read_xlsx(target: Path) -> dict:
    """Читает книгу Excel: листы и строки."""
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        return {"error": library_missing("openpyxl", "3.1.5")}
    try:
        workbook = openpyxl.load_workbook(str(target), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Не удалось прочитать книгу: {exc}"}

    sheets = []
    truncated = False
    try:
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [
                    "" if value is None else str(value) for value in row[:MAX_COLUMNS]
                ]
                rows.append(cells)
                if len(rows) >= MAX_ROWS:
                    truncated = True
                    break
            sheets.append({"name": sheet.title, "rows": rows})
    finally:
        workbook.close()

    lines = []
    for sheet in sheets:
        lines.append(f"[лист {sheet['name']}]")
        for row in sheet["rows"][:50]:
            lines.append(" | ".join(row))
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[текст обрезан]"
        truncated = True

    return {
        "path": str(target),
        "type": "xlsx",
        "sheets": [sheet["name"] for sheet in sheets],
        "sheet_count": len(sheets),
        "rows": sum(len(sheet["rows"]) for sheet in sheets),
        "text": text,
        "table_rows": sheets,
        "truncated": truncated,
    }


def read_pdf(target: Path) -> dict:
    """Читает PDF как текст: без картинок и вёрстки."""
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError:
        return {"error": library_missing("pypdf", "6.21.2")}
    try:
        reader = PdfReader(str(target))
        if reader.is_encrypted:
            return {"error": "PDF защищён паролем — не открыть."}
        pages = []
        truncated = False
        for index, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                text = ""
            pages.append(f"[страница {index + 1}]\n{text.strip()}")
            if sum(len(item) for item in pages) > MAX_CHARS:
                truncated = True
                break
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Не удалось прочитать PDF: {exc}"}

    text = "\n\n".join(pages)[:MAX_CHARS]
    return {
        "path": str(target),
        "type": "pdf",
        "pages": len(pages),
        "text": text,
        "truncated": truncated,
    }


def read_any(target: Path) -> dict:
    """Читает документ по расширению."""
    suffix = target.suffix.lower()
    if suffix == ".docx":
        return read_docx(target)
    if suffix == ".xlsx":
        return read_xlsx(target)
    if suffix == ".pdf":
        return read_pdf(target)
    return {"error": "Поддерживаются только .docx, .xlsx и .pdf."}
