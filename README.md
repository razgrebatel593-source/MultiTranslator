# 🌐 Мини-переводчик

Нейросетевой машинный переводчик на **14 языков** (182 направления) на базе открытой модели
[NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M) от Meta. Без API-ключей и подписок.

**Языки:** русский, английский, немецкий, французский, итальянский, испанский, португальский,
нидерландский, арабский, хинди, китайский, корейский, японский, греческий.

Два режима работы в одном интерфейсе:

| Режим | Где считает | Что нужно |
|---|---|---|
| **В браузере** | прямо на вашем устройстве ([Transformers.js](https://huggingface.co/docs/transformers.js), WASM) | только браузер; ≈600 МБ скачиваются один раз и кэшируются |
| **Python-сервер** | ваш Python-скрипт `mini_translator.py` (CPU/GPU) | Python 3.9+, `torch`, `transformers` |

## Файлы

```
index.html, style.css, app.js   – сайт (интерфейс)
worker.js                       – запуск модели в браузере (Web Worker)
mini_translator.py              – Python-переводчик (CLI + библиотека)
server.py                       – локальный сервер: сайт + API поверх mini_translator.py
.github/workflows/pages.yml     – автодеплой сайта на GitHub Pages
```

## Быстрый старт

### Вариант 1. Через Python (быстрее, любые модели)

```bash
pip install -r requirements.txt
python server.py
```

Откройте <http://localhost:8000> — сайт сам подключится к серверу.
Модель скачается при первом переводе (дальше работает офлайн, флаг `--offline`).

Полезные флаги: `--model nllb-1.3b`, `--port 9000`, `--preload`, `--device cuda`, `--beams 2`.

### Вариант 2. Только браузер (GitHub Pages)

1. Создайте репозиторий на GitHub и загрузите проект (см. ниже).
2. В репозитории: **Settings → Pages → Source: GitHub Actions**.
3. После первого пуша сайт появится на `https://<ваш-логин>.github.io/<репозиторий>/`.

Первый перевод скачивает модель (≈600 МБ); на странице виден прогресс.
Работает в современных Chrome, Edge, Firefox, Safari. Локально — только через
`python server.py` или `python -m http.server` (модульные воркеры не работают с `file://`).

> Сайт с GitHub Pages тоже может использовать ваш локальный `server.py`:
> переключитесь на «Python-сервер» и оставьте адрес `http://localhost:8000`
> (Safari блокирует такие запросы к http из https-страницы).

## Загрузка в GitHub

Git-репозиторий уже инициализирован, первый коммит сделан.

```bash
git remote add origin https://github.com/<логин>/<репозиторий>.git
git push -u origin main
```

## Python-скрипт отдельно

```bash
python mini_translator.py "Привет, мир!" -t en
python mini_translator.py -f book.txt -t fr -o book_fr.txt
python mini_translator.py -i          # интерактивный режим
python mini_translator.py --list      # языки и модели
```

## Лицензия

Код — MIT. Модели NLLB-200 распространяются под CC-BY-NC 4.0 (некоммерческое использование):
проверьте условия, если планируете коммерческое применение.
