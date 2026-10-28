const input = document.querySelector("#translateEndpoint");
const status = document.querySelector("#status");

chrome.storage.local.get({ translateEndpoint: "https://api.mymemory.translated.net/get" }).then(data => {
  input.value = data.translateEndpoint;
});

document.querySelector("#save").addEventListener("click", async () => {
  const value = input.value.trim();
  try { new URL(value); } catch { status.textContent = "请输入有效的网址"; return; }
  await chrome.storage.local.set({ translateEndpoint: value });
  status.textContent = "设置已保存";
});
