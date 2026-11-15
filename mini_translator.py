#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mini_translator.py — мини-ИИ для машинного перевода (без API-ключей).

Работает на открытых нейросетевых моделях (NLLB-200 / M2M-100 от Meta) через
библиотеку transformers. Модель один раз скачивается с Hugging Face Hub
(без регистрации и ключей), после чего работает полностью офлайн.

Языки (любое направление, 14 x 13 = 182 пары):
  ru en de fr it es pt nl ar hi zh ko ja el

Установка:
  pip install torch transformers sentencepiece
  pip install langdetect        # необязательно: точнее автоопределение языка

Примеры:
  python mini_translator.py "Привет, мир!" -t en
  python mini_translator.py "Guten Morgen" -s de -t ja
  python mini_translator.py -f book.txt -t fr -o book_fr.txt
  python mini_translator.py -i                      # интерактивный режим
  echo "Hello" | python mini_translator.py -t el    # из stdin
  python mini_translator.py --list                  # список языков/моделей
"""

import argparse
import os
import re
import sys
import time
import unicodedata

# --------------------------------------------------------------------------
# Языки: ISO-код -> (название по-русски, родное название, код NLLB)
# --------------------------------------------------------------------------
LANGS = {
    "ru": ("русский", "Русский", "rus_Cyrl"),
    "en": ("английский", "English", "eng_Latn"),
    "de": ("немецкий", "Deutsch", "deu_Latn"),
    "fr": ("французский", "Français", "fra_Latn"),
    "it": ("итальянский", "Italiano", "ita_Latn"),
    "es": ("испанский", "Español", "spa_Latn"),
    "pt": ("португальский", "Português", "por_Latn"),
    "nl": ("нидерландский", "Nederlands", "nld_Latn"),
    "ar": ("арабский", "العربية", "arb_Arab"),
    "hi": ("хинди", "हिन्दी", "hin_Deva"),
    "zh": ("китайский", "中文", "zho_Hans"),
    "ko": ("корейский", "한국어", "kor_Hang"),
    "ja": ("японский", "日本語", "jpn_Jpan"),
    "el": ("греческий", "Ελληνικά", "ell_Grek"),
}

# Дополнительные псевдонимы для ввода языка пользователем
ALIASES = {
    "russian": "ru", "english": "en", "german": "de", "french": "fr",
    "italian": "it", "spanish": "es", "portuguese": "pt", "dutch": "nl",
    "arabic": "ar", "hindi": "hi", "chinese": "zh", "korean": "ko",
    "japanese": "ja", "greek": "el", "zh-cn": "zh", "zh-tw": "zh",
    "нидерландский": "nl", "голландский": "nl", "китайский": "zh",
    "русский": "ru", "английский": "en", "немецкий": "de",
    "французский": "fr", "итальянский": "it", "испанский": "es",
    "португальский": "pt", "арабский": "ar", "хинди": "hi",
    "корейский": "ko", "японский": "ja", "греческий": "el",
}
for _c, (_ru, _nat, _n) in LANGS.items():
    ALIASES[_ru.lower()] = _c
    ALIASES[_nat.lower()] = _c

# Модели: ключ -> (репозиторий HF, семейство, ~размер)
MODELS = {
    "nllb-600m": ("facebook/nllb-200-distilled-600M", "nllb", "~2.4 ГБ, быстрая, хорошее качество (по умолчанию)"),
    "nllb-1.3b": ("facebook/nllb-200-distilled-1.3B", "nllb", "~5.5 ГБ, лучше качество"),
    "nllb-3.3b": ("facebook/nllb-200-3.3B", "nllb", "~17 ГБ, максимальное качество, нужна мощная машина"),
    "m2m-418m": ("facebook/m2m100_418M", "m2m", "~1.9 ГБ, самая лёгкая"),
    "m2m-1.2b": ("facebook/m2m100_1.2B", "m2m", "~5 ГБ, средняя"),
}
DEFAULT_MODEL = "nllb-600m"


def resolve_lang(value):
    """Приводит ввод пользователя ('RU', 'русский', 'English') к ISO-коду."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("auto", "авто", ""):
        return None
    if v in LANGS:
        return v
    if v in ALIASES:
        return ALIASES[v]
    raise ValueError(
        f"Неизвестный язык: «{value}». Доступно: {', '.join(LANGS)} (или 'auto')."
    )


# --------------------------------------------------------------------------
# Автоопределение языка
# --------------------------------------------------------------------------
_STOPWORDS = {
    "en": "the and is are of to in that it for with as was on be this you not have at by".split(),
    "de": "der die das und ist nicht ich ein eine zu mit den von sie auf für auch dem".split(),
    "fr": "le la les et est un une des du de que pour pas dans qui sur avec ce vous nous".split(),
    "it": "il lo la gli le e è un una di che per non con sono del della mi ho anche questo".split(),
    "es": "el la los las y es un una de que por no con para se del en su lo como más".split(),
    "pt": "o a os as e é um uma de que para não com em do da no na por mais está você".split(),
    "nl": "de het een en is van dat niet ik te voor met zijn op ze er maar ook aan als".split(),
}
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _script_of(ch):
    cp = ord(ch)
    if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
        return "kana"
    if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
        return "hangul"
    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
        return "han"
    if 0x0900 <= cp <= 0x097F:
        return "deva"
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
        return "arab"
    if 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
        return "greek"
    if 0x0400 <= cp <= 0x04FF:
        return "cyr"
    if ch.isalpha():
        try:
            if unicodedata.name(ch).startswith("LATIN"):
                return "latin"
        except ValueError:
            pass
    return None


def detect_language(text):
    """Возвращает ISO-код из LANGS (по умолчанию 'en')."""
    counts = {}
    for ch in text:
        s = _script_of(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return "en"

    if counts.get("kana"):
        return "ja"
    if counts.get("hangul", 0) >= counts.get("han", 0) and counts.get("hangul"):
        return "ko"
    total = sum(counts.values())
    top = max(counts, key=counts.get)
    simple = {"han": "zh", "deva": "hi", "arab": "ar", "greek": "el", "cyr": "ru"}
    if top in simple and counts[top] / total > 0.3:
        return simple[top]

    # Латиница: пробуем langdetect, затем эвристика по стоп-словам
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        for cand in detect_langs(text):
            code = cand.lang.lower().split("-")[0]
            if code in LANGS:
                return code
    except Exception:
        pass

    words = [w.lower() for w in _WORD_RE.findall(text)]
    scores = {l: sum(1 for w in words if w in set(sw)) for l, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


# --------------------------------------------------------------------------
# Разбиение текста на фрагменты
# --------------------------------------------------------------------------
_SENT_SPLIT = re.compile(r"(?<=[.!?…؟।])\s+|(?<=[。！？])")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:，、；：])\s*")


def split_into_chunks(line, max_chars=280):
    """Делит строку на предложения и склеивает их в куски до max_chars."""
    sentences = [s for s in _SENT_SPLIT.split(line) if s and s.strip()]
    pieces = []
    for s in sentences:
        if len(s) <= max_chars * 1.5:
            pieces.append(s.strip())
        else:  # очень длинное предложение — режем по запятым
            buf = ""
            for part in _CLAUSE_SPLIT.split(s):
                if len(buf) + len(part) > max_chars and buf:
                    pieces.append(buf.strip())
                    buf = ""
                buf += part + " "
            if buf.strip():
                pieces.append(buf.strip())

    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 1 > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip() if cur else p
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------
# Переводчик
# --------------------------------------------------------------------------
class Translator:
    def __init__(self, model_key=DEFAULT_MODEL, device=None, beams=4,
                 batch_size=8, offline=False, verbose=True):
        if model_key not in MODELS:
            raise ValueError(f"Неизвестная модель {model_key}. Доступно: {', '.join(MODELS)}")
        self.model_key = model_key
        self.repo, self.family, _ = MODELS[model_key]
        self.beams = beams
        self.batch_size = batch_size
        self.offline = offline
        self.verbose = verbose
        self.device = device
        self.tokenizer = None
        self.model = None
        self.cache = {}

    # -- загрузка модели (лениво, при первом переводе) ----------------------
    def load(self):
        if self.model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError:
            sys.exit(
                "Не хватает библиотек. Установите:\n"
                "  pip install torch transformers sentencepiece"
            )

        self._torch = torch
        if self.device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        if self.device == "cpu":
            torch.set_num_threads(max(1, (os.cpu_count() or 2)))

        if self.verbose:
            print(f"[загрузка модели {self.repo} на {self.device}; "
                  f"при первом запуске идёт скачивание...]", file=sys.stderr)
        t0 = time.time()
        kw = {"local_files_only": True} if self.offline else {}
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.repo, **kw)
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                self.repo, torch_dtype=dtype, **kw
            )
        except Exception as e:
            sys.exit(
                f"Не удалось загрузить модель: {e}\n"
                "Проверьте интернет при первом запуске (ключи не нужны) "
                "или уберите флаг --offline."
            )
        self.model.to(self.device).eval()
        if self.verbose:
            print(f"[модель готова за {time.time() - t0:.1f} c]", file=sys.stderr)

    def _code(self, lang):
        return LANGS[lang][2] if self.family == "nllb" else lang

    def _target_id(self, lang):
        if self.family == "nllb":
            return self.tokenizer.convert_tokens_to_ids(self._code(lang))
        return self.tokenizer.get_lang_id(lang)

    # -- перевод списка кусков ---------------------------------------------
    def _translate_chunks(self, chunks, src, tgt):
        self.load()
        torch = self._torch
        self.tokenizer.src_lang = self._code(src)
        forced = self._target_id(tgt)

        results = {}
        todo = []
        for i, c in enumerate(chunks):
            key = (src, tgt, c)
            if key in self.cache:
                results[i] = self.cache[key]
            else:
                todo.append(i)
        # сортировка по длине ускоряет батчи
        todo.sort(key=lambda i: len(chunks[i]))

        for b in range(0, len(todo), self.batch_size):
            idxs = todo[b:b + self.batch_size]
            batch = [chunks[i] for i in idxs]
            enc = self.tokenizer(batch, return_tensors="pt", padding=True,
                                 truncation=True, max_length=256).to(self.device)
            with torch.inference_mode():
                out = self.model.generate(
                    **enc,
                    forced_bos_token_id=forced,
                    num_beams=self.beams,
                    max_new_tokens=int(enc["input_ids"].shape[1] * 1.6) + 16,
                    no_repeat_ngram_size=4,
                    early_stopping=True,
                )
            decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)
            for i, t in zip(idxs, decoded):
                t = t.strip()
                results[i] = t
                self.cache[(src, tgt, chunks[i])] = t
        return [results[i] for i in range(len(chunks))]

    # -- публичный API -----------------------------------------------------
    def translate(self, text, tgt, src=None):
        """Переводит текст (любой длины, с абзацами). Возвращает (перевод, src)."""
        tgt = resolve_lang(tgt)
        if tgt is None:
            raise ValueError("Не указан язык перевода.")
        src = resolve_lang(src) if src else None
        if not text.strip():
            return text, src or tgt
        if src is None:
            src = detect_language(text)
        if src == tgt:
            return text, src

        lines = text.split("\n")
        plan = []          # (индекс строки, число кусков) либо None для пустых
        all_chunks = []
        for line in lines:
            if not line.strip():
                plan.append(0)
                continue
            ch = split_into_chunks(line.strip())
            plan.append(len(ch))
            all_chunks.extend(ch)

        translated = self._translate_chunks(all_chunks, src, tgt)

        joiner = "" if tgt in ("zh", "ja") else " "
        out_lines, pos = [], 0
        for n in plan:
            if n == 0:
                out_lines.append("")
            else:
                out_lines.append(joiner.join(translated[pos:pos + n]))
                pos += n
        return "\n".join(out_lines), src


# --------------------------------------------------------------------------
# Интерфейсы
# --------------------------------------------------------------------------
def print_languages():
    print("Поддерживаемые языки:")
    for code, (ru, nat, nllb) in LANGS.items():
        print(f"  {code:3} — {ru:15} {nat}")
    print("\nМодели (--model):")
    for k, (repo, _, note) in MODELS.items():
        mark = " *" if k == DEFAULT_MODEL else ""
        print(f"  {k:10} {note}{mark}")


HELP_INTERACTIVE = """\
Команды:
  /to xx      язык перевода (например /to de, /to японский)
  /from xx    язык оригинала ('auto' — определять автоматически)
  /swap       поменять языки местами
  /langs      список языков
  /help       эта справка
  /quit       выход
Всё остальное — текст для перевода. Пустая строка игнорируется."""


def interactive(tr, src, tgt):
    print("Мини-переводчик. /help — справка, /quit — выход.")
    print(f"Направление: {src or 'auto'} → {tgt}")
    last_src = None
    while True:
        try:
            line = input(f"[{src or 'auto'}→{tgt}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line.partition(" ")
            cmd = cmd.lower()
            try:
                if cmd in ("/quit", "/q", "/exit"):
                    break
                elif cmd == "/to":
                    new = resolve_lang(arg)
                    if new is None:
                        print("Укажите конкретный язык.")
                    else:
                        tgt = new
                elif cmd == "/from":
                    src = resolve_lang(arg)
                elif cmd == "/swap":
                    s = src or last_src
                    if s is None:
                        print("Исходный язык ещё неизвестен.")
                    else:
                        src, tgt = tgt, s
                elif cmd == "/langs":
                    print_languages()
                else:
                    print(HELP_INTERACTIVE)
            except ValueError as e:
                print(e)
            continue
        try:
            t0 = time.time()
            out, used = tr.translate(line, tgt, src)
            last_src = used
            print(f"  ({used}→{tgt}, {time.time() - t0:.1f} c)")
            print(out)
        except ValueError as e:
            print(e)


def main():
    p = argparse.ArgumentParser(
        description="Мини-ИИ для машинного перевода между 14 языками (без API-ключей).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("text", nargs="*", help="текст для перевода")
    p.add_argument("-s", "--src", default="auto", help="язык оригинала (по умолчанию auto)")
    p.add_argument("-t", "--tgt", default="en", help="язык перевода (по умолчанию en)")
    p.add_argument("-f", "--file", help="перевести текстовый файл (UTF-8)")
    p.add_argument("-o", "--out", help="сохранить результат в файл")
    p.add_argument("-i", "--interactive", action="store_true", help="интерактивный режим")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL, choices=MODELS.keys(),
                   help=f"модель (по умолчанию {DEFAULT_MODEL})")
    p.add_argument("--beams", type=int, default=4, help="ширина beam search (1 — быстрее, 5 — точнее)")
    p.add_argument("--batch", type=int, default=8, help="размер батча")
    p.add_argument("--device", choices=["cpu", "cuda", "mps"], help="устройство (по умолчанию авто)")
    p.add_argument("--offline", action="store_true", help="не обращаться к сети (модель уже скачана)")
    p.add_argument("--list", action="store_true", help="показать языки и модели")
    p.add_argument("-q", "--quiet", action="store_true", help="не печатать служебные сообщения")
    args = p.parse_args()

    if args.list:
        print_languages()
        return

    try:
        src = resolve_lang(args.src)
        tgt = resolve_lang(args.tgt)
    except ValueError as e:
        sys.exit(str(e))
    if tgt is None:
        sys.exit("Язык перевода не может быть 'auto'.")

    tr = Translator(args.model, args.device, args.beams, args.batch,
                    args.offline, verbose=not args.quiet)

    if args.interactive:
        interactive(tr, src, tgt)
        return

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            sys.exit(f"Не удалось прочитать файл: {e}")
    elif args.text:
        text = " ".join(args.text)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        interactive(tr, src, tgt)
        return

    t0 = time.time()
    result, used = tr.translate(text, tgt, src)
    if not args.quiet:
        print(f"[{used} → {tgt}, {time.time() - t0:.1f} c]", file=sys.stderr)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(result)
        if not args.quiet:
            print(f"Сохранено: {args.out}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
