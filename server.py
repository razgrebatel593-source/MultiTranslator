#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — локальный веб-сервер для mini_translator.py (только стандартная библиотека).

Раздаёт сайт (index.html, app.js, ...) и даёт API для перевода:
  GET  /api/health      -> {"ok": true, "model": "...", "loaded": false, "languages": [...]}
  POST /api/translate   -> {"text": "...", "src": "auto", "tgt": "en"}
                           <- {"translation": "...", "src": "ru"}

Запуск:
  pip install torch transformers sentencepiece
  python server.py                      # http://localhost:8000
  python server.py --port 9000 --model nllb-1.3b --offline
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mini_translator as mt

ROOT = Path(__file__).resolve().parent
STATIC = {"index.html", "style.css", "app.js", "worker.js", "favicon.ico"}
MAX_BODY = 5 * 1024 * 1024  # 5 МБ

TRANSLATOR = None
LOCK = threading.Lock()  # модель обрабатывает один запрос за раз


class Handler(BaseHTTPRequestHandler):
    server_version = "MiniTranslator/1.0"

    # -- вспомогательное ---------------------------------------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Чтобы сайт с GitHub Pages (https) мог обращаться к localhost
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # -- методы ------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            return self._json(200, {
                "ok": True,
                "model": TRANSLATOR.model_key,
                "loaded": TRANSLATOR.model is not None,
                "languages": list(mt.LANGS),
            })
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        if name not in STATIC or not (ROOT / name).is_file():
            return self._json(404, {"error": "Не найдено"})
        data = (ROOT / name).read_bytes()
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or name.endswith(".js"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/translate":
            return self._json(404, {"error": "Не найдено"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"error": "Пустой или слишком большой запрос (макс. 5 МБ)."})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            text = data.get("text", "")
            src = data.get("src") or "auto"
            tgt = data.get("tgt")
            if not isinstance(text, str):
                raise ValueError("Поле text должно быть строкой.")
        except (ValueError, UnicodeDecodeError, AttributeError) as e:
            return self._json(400, {"error": f"Некорректный запрос: {e}"})

        try:
            with LOCK:
                result, used = TRANSLATOR.translate(text, tgt, src)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except SystemExit as e:  # mini_translator вызывает sys.exit при сбое загрузки модели
            return self._json(500, {"error": str(e) or "Не удалось загрузить модель."})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"Ошибка перевода: {e}"})
        self._json(200, {"translation": result, "src": used})


def main():
    global TRANSLATOR
    p = argparse.ArgumentParser(description="Локальный сервер мини-переводчика")
    p.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("-m", "--model", default=mt.DEFAULT_MODEL, choices=mt.MODELS.keys())
    p.add_argument("--beams", type=int, default=4)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--device", choices=["cpu", "cuda", "mps"])
    p.add_argument("--offline", action="store_true", help="модель уже скачана, сеть не нужна")
    p.add_argument("--preload", action="store_true", help="загрузить модель сразу при старте")
    args = p.parse_args()

    TRANSLATOR = mt.Translator(args.model, args.device, args.beams, args.batch,
                               args.offline, verbose=True)
    if args.preload:
        TRANSLATOR.load()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Сайт и API: http://{args.host}:{args.port}  (Ctrl+C — остановить)")
    if not args.preload:
        print("Модель загрузится при первом переводе.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
