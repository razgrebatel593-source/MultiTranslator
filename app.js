// Мини-переводчик: интерфейс + два режима (браузер / локальный Python-сервер).

// --------------------------------------------------------------------------
// Языки (те же, что в mini_translator.py): ISO -> [рус. название, родное, код NLLB]
// --------------------------------------------------------------------------
const LANGS = {
  ru: ["русский", "Русский", "rus_Cyrl"],
  en: ["английский", "English", "eng_Latn"],
  de: ["немецкий", "Deutsch", "deu_Latn"],
  fr: ["французский", "Français", "fra_Latn"],
  it: ["итальянский", "Italiano", "ita_Latn"],
  es: ["испанский", "Español", "spa_Latn"],
  pt: ["португальский", "Português", "por_Latn"],
  nl: ["нидерландский", "Nederlands", "nld_Latn"],
  ar: ["арабский", "العربية", "arb_Arab"],
  hi: ["хинди", "हिन्दी", "hin_Deva"],
  zh: ["китайский", "中文", "zho_Hans"],
  ko: ["корейский", "한국어", "kor_Hang"],
  ja: ["японский", "日本語", "jpn_Jpan"],
  el: ["греческий", "Ελληνικά", "ell_Grek"],
};

// --------------------------------------------------------------------------
// Автоопределение языка (порт detect_language из Python-скрипта)
// --------------------------------------------------------------------------
const STOPWORDS = {
  en: "the and is are of to in that it for with as was on be this you not have at by",
  de: "der die das und ist nicht ich ein eine zu mit den von sie auf für auch dem",
  fr: "le la les et est un une des du de que pour pas dans qui sur avec ce vous nous",
  it: "il lo la gli le e è un una di che per non con sono del della mi ho anche questo",
  es: "el la los las y es un una de que por no con para se del en su lo como más",
  pt: "o a os as e é um uma de que para não com em do da no na por mais está você",
  nl: "de het een en is van dat niet ik te voor met zijn op ze er maar ook aan als",
};
for (const k of Object.keys(STOPWORDS)) STOPWORDS[k] = new Set(STOPWORDS[k].split(" "));

function scriptOf(ch) {
  const cp = ch.codePointAt(0);
  if ((cp >= 0x3040 && cp <= 0x30ff) || (cp >= 0x31f0 && cp <= 0x31ff)) return "kana";
  if ((cp >= 0xac00 && cp <= 0xd7af) || (cp >= 0x1100 && cp <= 0x11ff) || (cp >= 0x3130 && cp <= 0x318f)) return "hangul";
  if ((cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x3400 && cp <= 0x4dbf)) return "han";
  if (cp >= 0x0900 && cp <= 0x097f) return "deva";
  if ((cp >= 0x0600 && cp <= 0x06ff) || (cp >= 0x0750 && cp <= 0x077f)) return "arab";
  if ((cp >= 0x0370 && cp <= 0x03ff) || (cp >= 0x1f00 && cp <= 0x1fff)) return "greek";
  if (cp >= 0x0400 && cp <= 0x04ff) return "cyr";
  if (/\p{Script=Latin}/u.test(ch)) return "latin";
  return null;
}

function detectLanguage(text) {
  const counts = {};
  for (const ch of text) {
    const s = scriptOf(ch);
    if (s) counts[s] = (counts[s] || 0) + 1;
  }
  const keys = Object.keys(counts);
  if (!keys.length) return "en";
  if (counts.kana) return "ja";
  if (counts.hangul && counts.hangul >= (counts.han || 0)) return "ko";
  const total = keys.reduce((a, k) => a + counts[k], 0);
  const top = keys.reduce((a, k) => (counts[k] > counts[a] ? k : a));
  const simple = { han: "zh", deva: "hi", arab: "ar", greek: "el", cyr: "ru" };
  if (simple[top] && counts[top] / total > 0.3) return simple[top];

  const words = (text.toLowerCase().match(/\p{L}+/gu) || []);
  let best = "en", bestScore = 0;
  for (const [lang, set] of Object.entries(STOPWORDS)) {
    const score = words.reduce((a, w) => a + (set.has(w) ? 1 : 0), 0);
    if (score > bestScore) { best = lang; bestScore = score; }
  }
  return best;
}

// --------------------------------------------------------------------------
// Разбиение на фрагменты (порт split_into_chunks)
// --------------------------------------------------------------------------
function splitIntoChunks(line, maxChars = 280) {
  const sentences = line.split(/(?<=[.!?…؟।])\s+|(?<=[。！？])/u).filter((s) => s && s.trim());
  const pieces = [];
  for (const s of sentences) {
    if (s.length <= maxChars * 1.5) {
      pieces.push(s.trim());
    } else {
      let buf = "";
      for (const part of s.split(/(?<=[,;:，、；：])\s*/u)) {
        if (buf.length + part.length > maxChars && buf) { pieces.push(buf.trim()); buf = ""; }
        buf += part + " ";
      }
      if (buf.trim()) pieces.push(buf.trim());
    }
  }
  const chunks = [];
  let cur = "";
  for (const p of pieces) {
    if (cur && cur.length + p.length + 1 > maxChars) { chunks.push(cur); cur = p; }
    else cur = cur ? `${cur} ${p}` : p;
  }
  if (cur) chunks.push(cur);
  return chunks;
}

// --------------------------------------------------------------------------
// DOM
// --------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const el = {
  src: $("src"), tgt: $("tgt"), swap: $("swap"),
  input: $("input"), output: $("output"), count: $("count"), detected: $("detected"),
  go: $("go"), status: $("status"), bar: $("bar"), barFill: $("barFill"),
  clear: $("clear"), copy: $("copy"), save: $("save"), openFile: $("openFile"), file: $("file"),
  modeBrowser: $("modeBrowser"), modeServer: $("modeServer"), modeHint: $("modeHint"),
  serverRow: $("serverRow"), serverUrl: $("serverUrl"), serverBadge: $("serverBadge"),
};

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

function setStatus(msg, isErr = false) {
  el.status.textContent = msg;
  el.status.classList.toggle("err", isErr);
}
function setProgress(frac) {
  if (frac == null) { el.bar.hidden = true; return; }
  el.bar.hidden = false;
  el.barFill.style.width = `${Math.round(Math.min(1, Math.max(0, frac)) * 100)}%`;
}

// Списки языков
el.src.append(new Option("Определить автоматически", "auto"));
for (const [code, [ru, nat]] of Object.entries(LANGS)) {
  el.src.append(new Option(`${ru[0].toUpperCase() + ru.slice(1)} — ${nat}`, code));
  el.tgt.append(new Option(`${ru[0].toUpperCase() + ru.slice(1)} — ${nat}`, code));
}
el.src.value = store.get("src", "auto");
el.tgt.value = store.get("tgt", "en");
if (!el.src.value) el.src.value = "auto";
if (!el.tgt.value) el.tgt.value = "en";

// --------------------------------------------------------------------------
// Режим: браузер
// --------------------------------------------------------------------------
let worker = null;
let reqId = 0;
const pending = new Map();
const files = new Map(); // прогресс скачивания по файлам модели
const cache = new Map();

function getWorker() {
  if (worker) return worker;
  worker = new Worker("worker.js", { type: "module" });
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === "download") return onDownload(m.p);
    const p = pending.get(m.id);
    if (!p) return;
    if (m.type === "progress") p.onProgress?.(m.done, m.total);
    else if (m.type === "result" || m.type === "loaded") { pending.delete(m.id); p.resolve(m); }
    else if (m.type === "error") { pending.delete(m.id); p.reject(new Error(m.message)); }
  };
  worker.onerror = (e) => {
    for (const p of pending.values()) p.reject(new Error(e.message || "Ошибка воркера"));
    pending.clear();
    worker = null;
  };
  return worker;
}

function callWorker(msg, onProgress) {
  return new Promise((resolve, reject) => {
    const id = ++reqId;
    pending.set(id, { resolve, reject, onProgress });
    getWorker().postMessage({ id, ...msg });
  });
}

let modelReady = false;
function onDownload(p) {
  if (modelReady || !p || !p.file) return;
  if (p.status === "progress" && p.total) files.set(p.file, { loaded: p.loaded, total: p.total });
  if (p.status === "done" && files.has(p.file)) {
    const f = files.get(p.file); f.loaded = f.total;
  }
  let loaded = 0, total = 0;
  for (const f of files.values()) { loaded += f.loaded; total += f.total; }
  if (total) {
    setProgress(loaded / total);
    setStatus(`Загрузка модели в браузер: ${(loaded / 1e6).toFixed(0)} / ${(total / 1e6).toFixed(0)} МБ (один раз, дальше из кэша)`);
  }
}

async function translateBrowser(text, src, tgt) {
  const lines = text.split("\n");
  const plan = [];
  const all = [];
  for (const line of lines) {
    if (!line.trim()) { plan.push(0); continue; }
    const ch = splitIntoChunks(line.trim());
    plan.push(ch.length);
    all.push(...ch);
  }
  const srcCode = LANGS[src][2], tgtCode = LANGS[tgt][2];

  // кэш + список того, что надо перевести
  const result = new Array(all.length);
  const todoIdx = [];
  all.forEach((c, i) => {
    const k = `${src}|${tgt}|${c}`;
    if (cache.has(k)) result[i] = cache.get(k); else todoIdx.push(i);
  });

  if (todoIdx.length) {
    if (!modelReady) {
      setStatus("Запуск модели…");
      setProgress(0);
      await callWorker({ type: "load" });
      modelReady = true;
    }
    const r = await callWorker(
      { type: "translate", chunks: todoIdx.map((i) => all[i]), src: srcCode, tgt: tgtCode },
      (done, total) => { setProgress(done / total); setStatus(`Перевод: ${done} / ${total}`); }
    );
    todoIdx.forEach((i, j) => { result[i] = r.chunks[j]; cache.set(`${src}|${tgt}|${all[i]}`, r.chunks[j]); });
  }

  const joiner = tgt === "zh" || tgt === "ja" ? "" : " ";
  const out = [];
  let pos = 0;
  for (const n of plan) {
    if (n === 0) out.push("");
    else { out.push(result.slice(pos, pos + n).join(joiner)); pos += n; }
  }
  return out.join("\n");
}

// --------------------------------------------------------------------------
// Режим: Python-сервер
// --------------------------------------------------------------------------
const apiBase = () => el.serverUrl.value.trim().replace(/\/+$/, "");

async function pingServer(timeoutMs = 2500) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`${apiBase()}/api/health`, { signal: ctl.signal });
    const j = await r.json();
    return j && j.ok ? j : null;
  } catch { return null; } finally { clearTimeout(t); }
}

async function refreshBadge() {
  el.serverBadge.className = "badge";
  el.serverBadge.textContent = "проверка…";
  const h = await pingServer();
  if (h) {
    el.serverBadge.classList.add("ok");
    el.serverBadge.textContent = `● подключён (${h.model}${h.loaded ? ", модель загружена" : ""})`;
  } else {
    el.serverBadge.classList.add("bad");
    el.serverBadge.textContent = "● нет связи — запустите: python server.py";
  }
  return !!h;
}

async function translateServer(text, src, tgt) {
  setStatus("Перевод на сервере… (при первом запуске модель загружается — это может занять время)");
  setProgress(null);
  let r;
  try {
    r = await fetch(`${apiBase()}/api/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, src: src === "auto" ? "auto" : src, tgt }),
    });
  } catch {
    throw new Error("Сервер недоступен. Запустите в папке проекта: python server.py");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Ошибка сервера (${r.status})`);
  return { text: j.translation, src: j.src };
}

// --------------------------------------------------------------------------
// Режимы и главная кнопка
// --------------------------------------------------------------------------
let mode = "browser";

function setMode(m) {
  mode = m;
  store.set("mode", m);
  el.modeBrowser.classList.toggle("on", m === "browser");
  el.modeServer.classList.toggle("on", m === "server");
  el.serverRow.hidden = m !== "server";
  el.modeHint.textContent = m === "browser"
    ? "Модель NLLB-200 (≈600 МБ) один раз скачивается в браузер и дальше работает офлайн. Ничего не отправляется на сторонние серверы."
    : "Перевод выполняет ваш Python-скрипт mini_translator.py на этом компьютере (CPU/GPU). Запустите: python server.py";
  if (m === "server") refreshBadge();
}

async function run() {
  const text = el.input.value;
  if (!text.trim()) { setStatus("Введите текст для перевода."); return; }
  const tgt = el.tgt.value;
  let src = el.src.value;
  el.go.disabled = true;
  el.output.value = "";
  el.detected.textContent = "";
  const t0 = performance.now();
  try {
    let out, used = src;
    if (mode === "server") {
      const r = await translateServer(text, src, tgt);
      out = r.text; used = r.src;
    } else {
      if (src === "auto") used = detectLanguage(text);
      out = used === tgt ? text : await translateBrowser(text, used, tgt);
    }
    el.output.value = out;
    if (src === "auto" && LANGS[used]) el.detected.textContent = `Определён язык: ${LANGS[used][0]}`;
    setStatus(`Готово за ${((performance.now() - t0) / 1000).toFixed(1)} с`);
  } catch (e) {
    setStatus(e.message || String(e), true);
  } finally {
    el.go.disabled = false;
    setProgress(null);
  }
}

// --------------------------------------------------------------------------
// События
// --------------------------------------------------------------------------
el.modeBrowser.onclick = () => setMode("browser");
el.modeServer.onclick = () => setMode("server");
el.serverUrl.onchange = () => { store.set("serverUrl", el.serverUrl.value.trim()); refreshBadge(); };
el.go.onclick = run;

el.src.onchange = () => store.set("src", el.src.value);
el.tgt.onchange = () => store.set("tgt", el.tgt.value);

el.swap.onclick = () => {
  const s = el.src.value;
  let newTgt = s;
  if (s === "auto") {
    const guess = el.input.value.trim() ? detectLanguage(el.input.value) : null;
    if (!guess) { setStatus("Выберите язык оригинала, чтобы поменять языки местами."); return; }
    newTgt = guess;
  }
  el.src.value = el.tgt.value;
  el.tgt.value = newTgt;
  // перевод становится новым оригиналом
  if (el.output.value) { el.input.value = el.output.value; el.output.value = ""; updateCount(); }
  store.set("src", el.src.value); store.set("tgt", el.tgt.value);
};

function updateCount() { el.count.textContent = `${el.input.value.length} симв.`; }
el.input.addEventListener("input", updateCount);

el.clear.onclick = () => {
  el.input.value = ""; el.output.value = ""; el.detected.textContent = "";
  updateCount(); setStatus(""); el.input.focus();
};

el.copy.onclick = async () => {
  if (!el.output.value) return;
  try { await navigator.clipboard.writeText(el.output.value); setStatus("Скопировано."); }
  catch { el.output.select(); document.execCommand("copy"); setStatus("Скопировано."); }
};

el.save.onclick = () => {
  if (!el.output.value) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([el.output.value], { type: "text/plain;charset=utf-8" }));
  a.download = `translation_${el.tgt.value}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
};

el.openFile.onclick = () => el.file.click();
el.file.onchange = async () => {
  const f = el.file.files[0];
  if (!f) return;
  el.input.value = await f.text();
  el.file.value = "";
  updateCount();
};

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
  if (e.altKey && e.key.toLowerCase() === "s") { e.preventDefault(); el.swap.click(); }
});

// --------------------------------------------------------------------------
// Старт
// --------------------------------------------------------------------------
(function init() {
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  el.serverUrl.value = store.get("serverUrl", local ? location.origin : "http://localhost:8000");
  updateCount();
  setMode(store.get("mode", "browser"));
  // Если страница открыта через server.py — сразу переключаемся на сервер
  if (local && !store.get("mode", null)) {
    pingServer(1500).then((h) => { if (h) setMode("server"); });
  }
  // Ссылка на репозиторий для GitHub Pages: https://USER.github.io/REPO/
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  if (m) {
    const repo = location.pathname.split("/").filter(Boolean)[0];
    if (repo) $("repoLink").href = `https://github.com/${m[1]}/${repo}`;
  }
})();
