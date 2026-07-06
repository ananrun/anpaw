const messagesEl = document.querySelector("#messages");
const traceEl = document.querySelector("#traceList");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const agentId = document.querySelector("#agentId");
const providerSelect = document.querySelector("#providerSelect");
const modelSelect = document.querySelector("#modelSelect");
const refreshModels = document.querySelector("#refreshModels");
const apiKey = document.querySelector("#apiKey");
const modelInfo = document.querySelector("#modelInfo");
const clearTrace = document.querySelector("#clearTrace");
const viewLogs = document.querySelector("#viewLogs");
const testModel = document.querySelector("#testModel");

apiKey.addEventListener("input", () => {
  localStorage.setItem(apiKeyStorageName(), apiKey.value.trim());
  updateModelInfoHint();
});

async function loadConfig() {
  const [configRes, providersRes] = await Promise.all([
    fetch("/config"),
    fetch("/providers"),
  ]);
  window.anpawConfig = await configRes.json();
  window.anpawProviders = (await providersRes.json()).providers || [];
  renderProviders();
  await loadModels(window.anpawConfig.provider || "kilo");
  updateModelInfoHint();
}

function updateModelInfoHint(extra = "") {
  const config = window.anpawConfig;
  if (!config) return;
  const provider = currentProvider();
  const selectedModel = modelSelect.value || config.model;
  const keyState = apiKey.value.trim()
    ? "using page key"
    : provider?.has_env_key
      ? `using ${provider.api_key_env}`
      : "free no key";
  modelInfo.textContent = `${provider?.name || config.provider} · ${selectedModel} · ${
    provider?.base_url || config.base_url
  } · ${
    keyState
  }${extra ? ` · ${extra}` : ""}`;
}

function renderProviders() {
  providerSelect.replaceChildren();
  for (const provider of window.anpawProviders) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.name;
    providerSelect.appendChild(option);
  }
  providerSelect.value = window.anpawConfig.provider || "kilo";
  apiKey.value = localStorage.getItem(apiKeyStorageName()) || "";
}

async function loadModels(providerId, refresh = false) {
  modelSelect.disabled = true;
  refreshModels.disabled = true;
  const res = await fetch(`/models?provider=${encodeURIComponent(providerId)}&refresh=${refresh}`);
  const payload = await res.json();
  modelSelect.replaceChildren();
  for (const model of payload.models || []) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name === model.id ? model.id : `${model.name} · ${model.id}`;
    option.title = model.description || model.id;
    modelSelect.appendChild(option);
  }
  const saved = localStorage.getItem(modelStorageName(providerId));
  const preferred = saved || currentProvider()?.default_model || window.anpawConfig.model;
  if ([...modelSelect.options].some((option) => option.value === preferred)) {
    modelSelect.value = preferred;
  }
  modelSelect.disabled = false;
  refreshModels.disabled = false;
  updateModelInfoHint();
}

function currentProvider() {
  return (window.anpawProviders || []).find((item) => item.id === providerSelect.value);
}

function apiKeyStorageName() {
  return `anpaw.${providerSelect.value || "kilo"}.apiKey`;
}

function modelStorageName(providerId = providerSelect.value || "kilo") {
  return `anpaw.${providerId}.model`;
}

function addMessage(role, text, isError = false) {
  const node = document.createElement("div");
  node.className = `msg ${role}${isError ? " error" : ""}`;
  node.innerHTML = `<span class="role">${role}</span>${escapeHtml(text)}`;
  messagesEl.appendChild(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderTrace(events) {
  traceEl.replaceChildren();
  for (const event of events || []) {
    const node = document.createElement("div");
    node.className = "event";
    node.innerHTML = `
      <strong>${escapeHtml(event.stage || "event")}</strong>
      <p>${escapeHtml(event.detail || "")}</p>
      <pre>${escapeHtml(JSON.stringify(event.data || {}, null, 2))}</pre>
    `;
    traceEl.appendChild(node);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  addMessage("user", text);
  input.value = "";
  const button = form.querySelector("button");
  button.disabled = true;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({
        agent_id: agentId.value.trim() || "default",
        provider: providerSelect.value,
        model: modelSelect.value,
        message: text,
        api_key: apiKey.value.trim(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const payload = await res.json();
    addMessage("assistant", payload.answer);
    renderTrace(payload.trace);
  } catch (error) {
    addMessage("assistant", error.message, true);
  } finally {
    button.disabled = false;
    input.focus();
  }
});

clearTrace.addEventListener("click", () => traceEl.replaceChildren());

viewLogs.addEventListener("click", async () => {
  const res = await fetch("/logs?lines=80");
  const payload = await res.json();
  renderTrace([
    {
      stage: "backend-log",
      detail: payload.log_file,
      data: {lines: payload.lines || []},
    },
  ]);
});

providerSelect.addEventListener("change", async () => {
  apiKey.value = localStorage.getItem(apiKeyStorageName()) || "";
  await loadModels(providerSelect.value);
  updateModelInfoHint();
});

modelSelect.addEventListener("change", () => {
  localStorage.setItem(modelStorageName(), modelSelect.value);
  updateModelInfoHint();
});

refreshModels.addEventListener("click", async () => {
  await loadModels(providerSelect.value, true);
});

testModel.addEventListener("click", async () => {
  testModel.disabled = true;
  updateModelInfoHint("testing...");
  try {
    const res = await fetch("/model-test", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({
        provider: providerSelect.value,
        model: modelSelect.value,
        api_key: apiKey.value.trim(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const payload = await res.json();
    if (payload.ok) {
      updateModelInfoHint("connected");
      addMessage(
        "assistant",
        `模型连通成功（${payload.auth || "no_key"}）：${payload.message}`
      );
    } else {
      updateModelInfoHint("not connected");
      addMessage(
        "assistant",
        `模型测试失败（${payload.auth || "no_key"}）：${payload.message}\n\n免费模型可能会被公共池限流，换一个模型或稍后重试即可。`,
        true
      );
    }
  } catch (error) {
    updateModelInfoHint("test failed");
    addMessage("assistant", error.message, true);
  } finally {
    testModel.disabled = false;
  }
});

addMessage(
  "assistant",
  "页面已就绪。OpenCode 和 Kilo Code 的免费模型默认无需 Key；直接点“测试模型”或发送消息即可。填 Key 只用于使用自己的额度。"
);
loadConfig();
