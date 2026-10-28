const FALLBACK_TRANSLATIONS = {
  ambitious: "雄心勃勃的；有抱负的",
  friction: "阻力；让事情变难的额外步骤",
  threshold: "门槛；开始做某事所需的最低程度",
  confidence: "信心；自信",
  estimate: "估计；估算",
  significant: "显著的；重要的",
  revenue: "收入；收益",
  decline: "下降；减少"
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "lingo-lens-translate") return undefined;
  translate(message.text)
    .then(result => sendResponse({ ok: true, ...result }))
    .catch(error => sendResponse({ ok: false, error: error.message || "翻译服务暂不可用" }));
  return true;
});

async function translate(text) {
  const normalized = text.trim().toLowerCase();
  if (FALLBACK_TRANSLATIONS[normalized]) {
    return { translation: FALLBACK_TRANSLATIONS[normalized], source: "内置词典" };
  }

  const settings = await chrome.storage.local.get({
    translateEndpoint: "https://api.mymemory.translated.net/get"
  });
  const url = new URL(settings.translateEndpoint);
  url.searchParams.set("q", text);
  url.searchParams.set("langpair", "en|zh-CN");
  const response = await fetch(url.toString());
  if (!response.ok) throw new Error(`翻译服务返回 ${response.status}`);
  const data = await response.json();
  const translation = String(data?.responseData?.translatedText || "").replace(/<[^>]*>/g, "").trim();
  if (!translation) throw new Error("没有得到翻译结果");
  return { translation, source: "在线翻译" };
}
