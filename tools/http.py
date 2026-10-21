# Общие функции для HTTP-запросов.
# Только стандартная библиотека, чтобы ничего не устанавливать.
# Честный User-Agent, без имитации браузера.

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import config


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Не даём urllib самому ходить по редиректам: проверяем каждый адрес."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass
class Download:
    url: str
    status: int
    headers: Any
    body: bytes
    truncated: bool


def _is_public_host(host: str) -> bool:
    """Запрещаем localhost и внутренние адреса (защита от SSRF)."""
    if not host:
        return False
    host = host.lower().strip("[]")
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return False
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for family, _, _, _, sockaddr in addresses:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HttpError(f"Разрешены только http и https, а не {parsed.scheme!r}.")
    if not parsed.hostname:
        raise HttpError("В адресе нет имени сайта.")
    if not _is_public_host(parsed.hostname):
        raise HttpError("Адрес ведёт на локальную или внутреннюю сеть — запрещено.")


def download(
    url: str,
    timeout: float = config.HTTP_TIMEOUT,
    max_bytes: int = config.MAX_PAGE_BYTES,
) -> Download:
    """Скачивает страницу, проверяя каждый редирект. Отдаёт не больше max_bytes."""
    current = url
    for _ in range(5):
        _validate_url(current)
        request = urllib.request.Request(
            current,
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        try:
            response = _OPENER.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in (301, 302, 303, 307, 308) and location:
                current = urllib.parse.urljoin(current, location)
                continue
            raise HttpError(f"Сайт ответил ошибкой {exc.code}.", status=exc.code)
        except urllib.error.URLError as exc:
            raise HttpError(f"Не удалось скачать страницу: {exc.reason}")
        except socket.timeout:
            raise HttpError("Сайт не ответил вовремя.")

        with response:
            body = response.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            return Download(
                url=current,
                status=getattr(response, "status", 200),
                headers=response.headers,
                body=body[:max_bytes],
                truncated=truncated,
            )

    raise HttpError("Слишком много перенаправлений.")


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: float = config.HTTP_TIMEOUT,
) -> dict:
    """GET-запрос с JSON-ответом (официальные API)."""
    if params:
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "")}
        )
        url = f"{url}?{query}"
    _validate_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(config.MAX_PAGE_BYTES)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", errors="replace")
        except Exception:
            pass
        raise HttpError(
            f"API ответил ошибкой {exc.code}. {detail}".strip(), status=exc.code
        )
    except urllib.error.URLError as exc:
        raise HttpError(f"Нет связи с API: {exc.reason}")

    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        raise HttpError("API вернул не JSON.")


def post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: float = config.HTTP_TIMEOUT,
) -> dict:
    """POST-запрос с JSON. Заголовки авторизации передаются снаружи."""
    _validate_url(url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(config.MAX_PAGE_BYTES)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", errors="replace")
        except Exception:
            pass
        raise HttpError(
            f"API ответил ошибкой {exc.code}. {detail}".strip(), status=exc.code
        )
    except urllib.error.URLError as exc:
        raise HttpError(f"Нет связи с API: {exc.reason}")

    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        raise HttpError("API вернул не JSON.")

