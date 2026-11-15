// Web Worker: запускает NLLB-200 прямо в браузере через Transformers.js (ONNX + WASM).
// Модель скачивается один раз с Hugging Face и кэшируется браузером.
import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.5.1";

env.allowLocalModels = false;

const MODEL = "Xenova/nllb-200-distilled-600M";
let translatorPromise = null;

function getTranslator() {
  if (!translatorPromise) {
    translatorPromise = pipeline("translation", MODEL, {
      progress_callback: (p) => self.postMessage({ type: "download", p }),
    }).catch((e) => {
      translatorPromise = null; // позволить повторную попытку
      throw e;
    });
  }
  return translatorPromise;
}

self.onmessage = async (e) => {
  const { id, type } = e.data;
  try {
    if (type === "load") {
      await getTranslator();
      self.postMessage({ id, type: "loaded" });
    } else if (type === "translate") {
      const tr = await getTranslator();
      const { chunks, src, tgt } = e.data;
      const out = [];
      for (let i = 0; i < chunks.length; i++) {
        const r = await tr(chunks[i], {
          src_lang: src,
          tgt_lang: tgt,
          max_new_tokens: 256,
          num_beams: 2,
          no_repeat_ngram_size: 4,
        });
        out.push(r[0].translation_text.trim());
        self.postMessage({ id, type: "progress", done: i + 1, total: chunks.length });
      }
      self.postMessage({ id, type: "result", chunks: out });
    }
  } catch (err) {
    self.postMessage({ id, type: "error", message: String(err && err.message || err) });
  }
};
