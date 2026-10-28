(() => {
  "use strict";

  const STYLE = `
    :host { all: initial; }
    .ll-layer { position: fixed; inset: 0; z-index: 2147483647; pointer-events: none; color: #1f2926; font-family: Aptos, Segoe UI, system-ui, sans-serif; }
    button { font: inherit; }
    .ll-card { position: fixed; top: 16px; right: 16px; width: min(360px, calc(100vw - 24px)); pointer-events: auto; border: 1px solid #dfe2dc; border-radius: 14px; background: #fffefa; box-shadow: 0 16px 44px rgba(31, 41, 38, .20); overflow: hidden; }
    .ll-card[hidden] { display: none; }
    .ll-card-head { padding: 14px 16px 11px; border-bottom: 1px solid #ecece7; display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
    .ll-kicker { color: #76817c; font-size: 10px; text-transform: uppercase; letter-spacing: .12em; font-weight: 750; margin-bottom: 5px; }
    .ll-original { color: #1f2926; font-size: 14px; line-height: 1.45; max-height: 42px; overflow: hidden; }
    .ll-close { border: 0; background: transparent; color: #76817c; font-size: 22px; line-height: 1; cursor: pointer; padding: 0 1px; }
    .ll-body { padding: 15px 16px; }
    .ll-loading { color: #76817c; font-size: 14px; padding: 6px 0; }
    .ll-translation { color: #1f2926; font-size: 21px; font-weight: 730; letter-spacing: -.025em; line-height: 1.35; }
    .ll-source { color: #76817c; font-size: 11px; margin-top: 8px; }
    .ll-error { color: #9b4d3e; background: #fae4dd; border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.45; }
    .ll-actions { padding: 0 16px 15px; display: flex; gap: 8px; }
    .ll-action { border: 1px solid #dfe2dc; border-radius: 999px; background: #fffefa; color: #1f2926; cursor: pointer; padding: 7px 11px; font-size: 12px; }
    .ll-action:hover { border-color: #df664b; color: #df664b; }
    .ll-action.primary { background: #df664b; border-color: #df664b; color: #fffefa; }
    .ll-action.primary:hover { background: #c7543c; }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: .01ms !important; } }
  `;

  const host = document.createElement("div");
  host.setAttribute("data-lingo-lens", "true");
  document.documentElement.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>${STYLE}</style>
    <div class="ll-layer">
      <section class="ll-card" hidden aria-live="polite">
        <div class="ll-card-head"><div><div class="ll-kicker">Current selection</div><div class="ll-original"></div></div><button class="ll-close" type="button" aria-label="关闭">×</button></div>
        <div class="ll-body"><div class="ll-loading">正在生成中文...</div></div>
        <div class="ll-actions" hidden></div>
      </section>
    </div>`;

  const card = shadow.querySelector(".ll-card");
  const originalNode = shadow.querySelector(".ll-original");
  const body = shadow.querySelector(".ll-body");
  const actions = shadow.querySelector(".ll-actions");
  let selectedText = "";
  let selectionRect = null;
  let lastResult = null;
  let selectionTimer = null;
  let requestId = 0;

  function cleanText(value) {
    return value.replace(/\s+/g, " ").trim().slice(0, 500);
  }

  function isEnglish(value) {
    const text = value.trim();
    if (/^[A-Za-z]:[\\/]/.test(text)) return false;
    if (/^(?:https?|file|ftp):\/\//i.test(text)) return false;
    if (/^\\\\/.test(text)) return false;
    if (!/\s/.test(text) && ((text.match(/\//g) || []).length >= 2 || (text.match(/\\/g) || []).length >= 2)) return false;
    return /[A-Za-z]/.test(text) && !/^[\d\W_]+$/.test(text);
  }

  function insideHost(event) {
    return event.composedPath?.().includes(host);
  }

  function hideAll() {
    card.hidden = true;
    actions.hidden = true;
    selectedText = "";
    selectionRect = null;
    requestId += 1;
  }

  function readSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) { hideAll(); return; }
    const text = cleanText(selection.toString());
    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (!text || text.length < 2 || !isEnglish(text) || !rect.width) { hideAll(); return; }
    if (text === selectedText && !card.hidden) return;
    selectedText = text;
    selectionRect = rect;
    originalNode.textContent = text;
    card.hidden = true;
    actions.hidden = true;
    translateCurrent();
  }

  function scheduleSelection() {
    clearTimeout(selectionTimer);
    selectionTimer = setTimeout(readSelection, 80);
  }

  async function requestTranslation(text) {
    let result;
    try {
      result = await chrome.runtime.sendMessage({ type: "lingo-lens-translate", text });
    } catch (error) {
      throw error;
    }
    if (!result?.ok) throw new Error(result?.error || "翻译服务暂不可用");
    return result;
  }

  function isContextInvalidated(error) {
    return /Extension context invalidated/i.test(String(error?.message || error));
  }

  function renderResult(result) {
    lastResult = result;
    body.innerHTML = `<div class="ll-translation"></div><div class="ll-source"></div>`;
    body.querySelector(".ll-translation").textContent = result.translation;
    body.querySelector(".ll-source").textContent = result.source || "翻译结果";
    actions.innerHTML = `<button class="ll-action primary" data-action="save" type="button">收藏</button><button class="ll-action" data-action="copy" type="button">复制</button><button class="ll-action" data-action="retry" type="button">重试</button>`;
    actions.hidden = false;
    actions.querySelector("[data-action='save']").addEventListener("click", saveCurrent);
    actions.querySelector("[data-action='copy']").addEventListener("click", copyCurrent);
    actions.querySelector("[data-action='retry']").addEventListener("click", translateCurrent);
  }

  function renderError(error) {
    if (isContextInvalidated(error)) {
      body.innerHTML = `<div class="ll-error">扩展刚刚更新，请刷新当前网页后再继续划词翻译。</div>`;
      actions.innerHTML = `<button class="ll-action primary" data-action="refresh" type="button">刷新页面</button>`;
      actions.hidden = false;
      actions.querySelector("button").addEventListener("click", () => location.reload());
      return;
    }
    body.innerHTML = `<div class="ll-error"></div>`;
    body.querySelector(".ll-error").textContent = `翻译失败：${error.message}`;
    actions.innerHTML = `<button class="ll-action primary" data-action="retry" type="button">再次尝试</button>`;
    actions.hidden = false;
    actions.querySelector("button").addEventListener("click", translateCurrent);
  }

  async function translateCurrent() {
    if (!selectedText) return;
    const textAtRequest = selectedText;
    const thisRequest = ++requestId;
    card.hidden = false;
    actions.hidden = true;
    body.innerHTML = `<div class="ll-loading">正在生成中文...</div>`;
    try {
      const result = await requestTranslation(textAtRequest);
      if (thisRequest === requestId && textAtRequest === selectedText) renderResult(result);
    } catch (error) {
      if (thisRequest === requestId && textAtRequest === selectedText) renderError(error);
    }
  }

  async function saveCurrent() {
    if (!lastResult) return;
    const current = { text: selectedText, translation: lastResult.translation, url: location.href, createdAt: Date.now() };
    const data = await chrome.storage.local.get({ savedWords: [] });
    const savedWords = [current, ...data.savedWords.filter(item => item.text !== current.text)].slice(0, 200);
    await chrome.storage.local.set({ savedWords });
    const button = actions.querySelector("[data-action='save']");
    button.textContent = "已收藏";
    button.disabled = true;
  }

  async function copyCurrent() {
    if (!lastResult) return;
    await navigator.clipboard.writeText(`${selectedText}\n${lastResult.translation}`);
    const button = actions.querySelector("[data-action='copy']");
    button.textContent = "已复制";
    setTimeout(() => { if (button.isConnected) button.textContent = "复制"; }, 1400);
  }

  shadow.querySelector(".ll-close").addEventListener("click", hideAll);
  document.addEventListener("selectionchange", scheduleSelection, true);
  document.addEventListener("mouseup", scheduleSelection, true);
  document.addEventListener("keyup", scheduleSelection, true);
  document.addEventListener("mousedown", event => { if (!insideHost(event)) hideAll(); }, true);
})();
