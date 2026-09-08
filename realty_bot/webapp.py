from __future__ import annotations

import asyncio
import html
import json
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse


PhoneSubmitter = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ListingReader = Callable[[str], Any]


class WebAppServer:
    """Small dependency-free Telegram Mini WebApp HTTP server."""

    def __init__(
        self,
        host: str,
        port: int,
        loop: asyncio.AbstractEventLoop,
        read_listing: ListingReader,
        submit_lead: PhoneSubmitter,
    ) -> None:
        self.loop = loop
        self.read_listing = read_listing
        self.submit_lead = submit_lead
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="realty-webapp",
            daemon=True,
        )

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "RealtyWebApp/1.0"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send(self, status: int, content_type: str, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send(HTTPStatus.OK, "application/json", '{"ok":true}')
                    return
                if parsed.path not in {"/", "/webapp"}:
                    self._send(HTTPStatus.NOT_FOUND, "text/plain", "Not found")
                    return

                listing_id = parse_qs(parsed.query).get("listing_id", [""])[0]
                listing = parent.read_listing(listing_id) if listing_id else None
                if not listing:
                    self._send(
                        HTTPStatus.NOT_FOUND,
                        "text/html",
                        "<h1>Объявление не найдено</h1>",
                    )
                    return
                self._send(HTTPStatus.OK, "text/html", _page(str(listing["title"]), listing_id))

            def do_POST(self) -> None:
                if urlparse(self.path).path != "/api/leads":
                    self._send(HTTPStatus.NOT_FOUND, "application/json", '{"ok":false}')
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 32_000)
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Invalid payload")
                    future = asyncio.run_coroutine_threadsafe(
                        parent.submit_lead(payload), parent.loop
                    )
                    result = future.result(timeout=20)
                    self._send(HTTPStatus.OK, "application/json", json.dumps(result))
                except (ValueError, json.JSONDecodeError) as error:
                    self._send(
                        HTTPStatus.BAD_REQUEST,
                        "application/json",
                        json.dumps({"ok": False, "error": str(error)}),
                    )
                except Exception:
                    self._send(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "application/json",
                        '{"ok":false,"error":"Не удалось отправить заявку"}',
                    )

        return Handler

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def _page(title: str, listing_id: str) -> str:
    safe_title = html.escape(title)
    safe_listing_id = html.escape(listing_id, quote=True)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Запись на просмотр</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {{ color-scheme: light dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 20px; font: 16px/1.45 system-ui, sans-serif;
      color: var(--tg-theme-text-color, #17212b);
      background: var(--tg-theme-bg-color, #fff); }}
    main {{ max-width: 520px; margin: 0 auto; }}
    h1 {{ font-size: 24px; line-height: 1.2; margin: 0 0 8px; }}
    .hint {{ color: var(--tg-theme-hint-color, #708090); margin: 0 0 24px; }}
    label {{ display: block; font-weight: 600; margin: 16px 0 7px; }}
    input {{ width: 100%; border: 1px solid var(--tg-theme-hint-color, #b7c0c8);
      border-radius: 12px; padding: 13px; font: inherit;
      color: var(--tg-theme-text-color, #17212b);
      background: var(--tg-theme-secondary-bg-color, #f2f2f2); }}
    button {{ width: 100%; margin-top: 24px; border: 0; border-radius: 12px;
      padding: 14px; font: 700 16px system-ui; color: #fff;
      background: var(--tg-theme-button-color, #2481cc); }}
    button:disabled {{ opacity: .6; }}
    #status {{ min-height: 24px; margin-top: 14px; color: #d14; }}
  </style>
</head>
<body>
<main>
  <h1>📅 Записаться на просмотр</h1>
  <p class="hint">{safe_title}</p>
  <form id="lead-form">
    <label for="name">Ваше имя</label>
    <input id="name" name="name" autocomplete="name" required>
    <label for="phone">Номер телефона</label>
    <input id="phone" name="phone" type="tel" inputmode="tel"
      autocomplete="tel" placeholder="+380 67 123 45 67" required>
    <button id="submit" type="submit">Передать номер телефона</button>
    <div id="status" role="status"></div>
  </form>
</main>
<script>
  const tg = window.Telegram?.WebApp;
  if (tg) {{ tg.ready(); tg.expand(); }}
  const user = tg?.initDataUnsafe?.user || {{}};
  const name = document.querySelector('#name');
  const phone = document.querySelector('#phone');
  if (user.first_name) name.value = [user.first_name, user.last_name].filter(Boolean).join(' ');
  const form = document.querySelector('#lead-form');
  const button = document.querySelector('#submit');
  const status = document.querySelector('#status');
  form.addEventListener('submit', async (event) => {{
    event.preventDefault();
    button.disabled = true;
    status.textContent = 'Отправляем заявку…';
    try {{
      const response = await fetch('/api/leads', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          listing_id: '{safe_listing_id}',
          full_name: name.value.trim(),
          phone: phone.value.trim(),
          username: user.username || '',
          telegram_user_id: user.id || null,
          init_data: tg?.initData || ''
        }})
      }});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Ошибка отправки');
      if (tg) tg.close();
      else document.body.innerHTML = '<main><h1>Заявка отправлена</h1><p>Спасибо! С вами свяжутся для согласования просмотра.</p></main>';
    }} catch (error) {{
      button.disabled = false;
      status.textContent = error.message || 'Не удалось отправить заявку';
    }}
  }});
</script>
</body>
</html>"""