/* ============================================
   AnPaw Agent Lab — 前端交互逻辑
   ============================================ */

// ---- DOM 引用 ----
const messagesEl    = document.querySelector("#messages");
const traceEl       = document.querySelector("#traceList");
const form          = document.querySelector("#chatForm");
const input         = document.querySelector("#messageInput");
const agentId       = document.querySelector("#agentId");
const providerSelect= document.querySelector("#providerSelect");
const modelSelect   = document.querySelector("#modelSelect");
const refreshModels = document.querySelector("#refreshModels");
const apiKey        = document.querySelector("#apiKey");
const modelInfo     = document.querySelector("#modelInfo");
const clearTrace    = document.querySelector("#clearTrace");
const viewLogs      = document.querySelector("#viewLogs");
const testModel     = document.querySelector("#testModel");
const sendBtn       = document.querySelector("#sendBtn");
const toggleSettings= document.querySelector("#toggleSettings");
const settingsPanel = document.querySelector("#settingsPanel");
const scrollBottom  = document.querySelector("#scrollBottom");
const emptyState    = document.querySelector("#emptyState");
const toastContainer= document.querySelector("#toastContainer");
let startupTraceEvents = [];
let requestTraceEvents = [];

const traceSections = {
  startup: {
    title: "服务启动期",
    count: "4 项",
    nodes: ["Workspace 初始化", "Skill 加载", "Tool 注册", "Runner 就绪"],
  },
  request: {
    title: "单次请求期",
    count: "6 项",
    nodes: ["用户提问", "Manager 取 Workspace", "Runner 编排", "Skill 匹配", "Agent Loop", "Tool/Final"],
  },
};

// ---- 设置面板折叠 ----
toggleSettings.addEventListener("click", () => {
  settingsPanel.classList.toggle("open");
  toggleSettings.classList.toggle("active");
});

// ---- 输入框自动增高 ----
function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autoResize);

// ---- 回车发送 / Shift+回车换行 ----
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

// ---- API Key 存储 ----
apiKey.addEventListener("input", () => {
  localStorage.setItem(apiKeyStorageName(), apiKey.value.trim());
  updateModelInfoHint();
});

// ---- 滚动到底部按钮 ----
messagesEl.addEventListener("scroll", () => {
  const nearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
  scrollBottom.classList.toggle("visible", !nearBottom);
});

scrollBottom.addEventListener("click", () => {
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
});

// ---- 建议词点击 ----
document.querySelectorAll(".suggestion-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    input.value = chip.dataset.text;
    autoResize();
    input.focus();
  });
});

// ============================================
//  初始化加载
// ============================================

async function loadConfig() {
  try {
    const [configRes, providersRes, agentsRes, startupTraceRes] = await Promise.all([
      fetch("/config"),
      fetch("/providers"),
      fetch("/agents"),
      fetch("/startup-trace"),
    ]);
    window.anpawConfig = await configRes.json();
    window.anpawProviders = (await providersRes.json()).providers || [];
    window.anpawAgents = await agentsRes.json();
    const startupPayload = await startupTraceRes.json();
    startupTraceEvents = startupPayload.trace || [];
    renderAgents();
    renderProviders();
    await loadModels(window.anpawConfig.provider || "kilo");
    updateModelInfoHint();
    renderTracePanel();
  } catch (err) {
    toast("加载配置失败：" + err.message, "error");
  }
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
  modelInfo.textContent = `${provider?.name || config.provider} · ${selectedModel} · ${keyState}${extra ? ` · ${extra}` : ""}`;
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

function renderAgents() {
  agentId.replaceChildren();
  const payload = window.anpawAgents || {};
  for (const agent of payload.agents || []) {
    const option = document.createElement("option");
    option.value = agent.id;
    option.textContent = `${agent.name} · ${agent.id}`;
    option.title = agent.description || agent.id;
    agentId.appendChild(option);
  }
  const saved = localStorage.getItem("anpaw.agentId");
  const preferred = saved || payload.default_agent || "default";
  if ([...agentId.options].some((option) => option.value === preferred)) {
    agentId.value = preferred;
  }
}

async function loadModels(providerId, refresh = false) {
  modelSelect.disabled = true;
  refreshModels.disabled = true;
  try {
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
  } catch (err) {
    toast("加载模型列表失败：" + err.message, "error");
  } finally {
    modelSelect.disabled = false;
    refreshModels.disabled = false;
    updateModelInfoHint();
  }
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

// ============================================
//  消息渲染
// ============================================

const AVATARS = {
  user: "🧑",
  assistant: "🐾",
};

function hideEmptyState() {
  if (emptyState) emptyState.style.display = "none";
}

function addMessage(role, text, isError = false) {
  hideEmptyState();

  const node = document.createElement("div");
  node.className = `msg ${role}${isError ? " error" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = AVATARS[role] || "❓";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";

  const roleLabel = document.createElement("span");
  roleLabel.className = "role";
  roleLabel.textContent = role;

  const content = document.createElement("div");
  content.className = "msg-content";
  content.innerHTML = escapeHtml(text);

  bubble.appendChild(roleLabel);
  bubble.appendChild(content);
  node.appendChild(avatar);
  node.appendChild(bubble);
  messagesEl.appendChild(node);
  scrollToBottom();
  return { node, bubble, content };
}

function setMessageText(node, role, text, isError = false) {
  const { bubble, content } = node;
  node.node.className = `msg ${role}${isError ? " error" : ""}`;
  content.innerHTML = escapeHtml(text);
  scrollToBottom();
}

/** 显示打字指示器 */
function showTypingIndicator() {
  hideEmptyState();
  const node = document.createElement("div");
  node.className = "msg assistant";
  node.id = "typingIndicator";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = "🐾";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";

  const typing = document.createElement("div");
  typing.className = "typing-indicator";
  typing.innerHTML = "<span></span><span></span><span></span>";

  bubble.appendChild(typing);
  node.appendChild(avatar);
  node.appendChild(bubble);
  messagesEl.appendChild(node);
  scrollToBottom();
  return node;
}

function removeTypingIndicator() {
  const el = document.getElementById("typingIndicator");
  if (el) el.remove();
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ============================================
//  Trace 渲染 — 时间线 + 阶段分组
// ============================================

function renderTrace(events) {
  requestTraceEvents = events || [];
  renderTracePanel();
}

function renderTracePanel() {
  traceEl.replaceChildren();

  traceEl.appendChild(createTraceSection("startup", startupTraceEvents));
  traceEl.appendChild(createTraceSection("request", requestTraceEvents));

  traceEl.scrollTop = traceEl.scrollHeight;
}

function createTraceSection(kind, events) {
  const meta = traceSections[kind];
  const section = document.createElement("section");
  section.className = "trace-section flow-group";

  const head = document.createElement("button");
  head.className = "flow-group-head";
  head.type = "button";
  head.setAttribute("aria-expanded", "true");

  const label = document.createElement("span");
  label.className = "flow-label";
  label.textContent = meta.title;

  const count = document.createElement("span");
  count.className = "flow-count";
  count.textContent = meta.count;

  const toggle = document.createElement("span");
  toggle.className = "flow-toggle";
  toggle.textContent = "▼";

  head.appendChild(label);
  head.appendChild(count);
  head.appendChild(toggle);
  section.appendChild(head);

  const body = document.createElement("div");
  body.className = "trace-section-body";
  body.appendChild(createFlowRow(meta.nodes));

  // 按连续相同 stage 分组
  const groups = [];
  for (const event of events || []) {
    const stage = event.stage || "event";
    const last = groups[groups.length - 1];
    if (last && last.stage === stage) {
      last.events.push(event);
    } else {
      groups.push({ stage, events: [event] });
    }
  }

  for (const group of groups) {
    body.appendChild(createTraceGroup(group.stage, group.events));
  }

  head.addEventListener("click", () => {
    const collapsed = section.classList.toggle("collapsed");
    head.setAttribute("aria-expanded", String(!collapsed));
  });

  section.appendChild(body);
  return section;
}

function createFlowRow(nodes) {
  const row = document.createElement("div");
  row.className = "flow-row";

  nodes.forEach((name, index) => {
    if (index > 0) {
      const arrow = document.createElement("span");
      arrow.className = "flow-arrow";
      arrow.textContent = "→";
      row.appendChild(arrow);
    }

    const node = document.createElement("span");
    node.className = "flow-node";
    node.textContent = name;
    row.appendChild(node);
  });

  return row;
}

function appendTraceEvent(event) {
  requestTraceEvents.push(event);
  renderTracePanel();
}

function createTraceGroup(stage, events) {
  const group = document.createElement("div");
  group.className = "trace-group";
  group.dataset.stage = stage;

  // 分组头部
  const header = document.createElement("div");
  header.className = "trace-group-header";

  const dot = document.createElement("span");
  dot.className = "trace-dot";
  dot.dataset.stage = stage;

  const label = document.createElement("span");
  label.className = "trace-group-label";
  label.dataset.stage = stage;
  label.textContent = stage;

  const count = document.createElement("span");
  count.className = "trace-group-count";
  count.textContent = `${events.length} 条`;

  const toggle = document.createElement("span");
  toggle.className = "trace-group-toggle";
  toggle.textContent = "▼";

  header.appendChild(dot);
  header.appendChild(label);
  header.appendChild(count);
  header.appendChild(toggle);

  // 事件列表
  const list = document.createElement("div");
  list.className = "trace-group-list";
  for (const event of events) {
    appendEventItem(list, event);
  }

  // 点击头部折叠/展开
  header.addEventListener("click", () => {
    group.classList.toggle("collapsed");
  });

  group.appendChild(header);
  group.appendChild(list);
  return group;
}

function appendEventItem(listEl, event) {
  const node = document.createElement("div");
  node.className = "event";

  const detail = event.detail || event.message || "";
  const hasData = event.data && Object.keys(event.data).length > 0;

  const header = document.createElement("div");
  header.className = "event-header";

  const detailEl = document.createElement("span");
  detailEl.className = "event-detail";
  detailEl.textContent = detail;
  detailEl.title = detail;
  header.appendChild(detailEl);

  if (hasData) {
    const toggle = document.createElement("span");
    toggle.className = "event-toggle";
    toggle.textContent = "▶";
    header.appendChild(toggle);

    const body = document.createElement("div");
    body.className = "event-body";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(event.data, null, 2);
    body.appendChild(pre);

    header.addEventListener("click", (e) => {
      e.stopPropagation();
      node.classList.toggle("expanded");
    });

    node.appendChild(header);
    node.appendChild(body);
  } else {
    header.style.cursor = "default";
    node.appendChild(header);
  }

  listEl.appendChild(node);
}

function updateGroupCount(groupEl) {
  const count = groupEl.querySelector(".trace-group-count");
  const events = groupEl.querySelectorAll(".trace-group-list .event");
  count.textContent = `${events.length} 条`;
}

// ============================================
//  工具函数
// ============================================

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  toastContainer.appendChild(el);
  setTimeout(() => {
    el.classList.add("hide");
    setTimeout(() => el.remove(), 200);
  }, 3000);
}

// ============================================
//  发送消息
// ============================================

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  addMessage("user", text);
  input.value = "";
  autoResize();
  sendBtn.classList.add("loading");
  sendBtn.disabled = true;

  // 显示打字指示器
  const typingNode = showTypingIndicator();
  let assistantNode = null;
  let answer = "";
  let firstChunk = true;

  try {
    const res = await fetch("/chat-stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        agent_id: agentId.value || window.anpawAgents?.default_agent || "default",
        provider: providerSelect.value,
        model: modelSelect.value,
        message: text,
        api_key: apiKey.value.trim(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());

    await readChatStream(res, {
      onStatus(event) {
        appendTraceEvent({
          stage: event.stage || "stream",
          detail: event.message || "",
          data: event.data || {},
        });
      },
      onChunk(text) {
        if (firstChunk) {
          removeTypingIndicator();
          assistantNode = addMessage("assistant", "");
          firstChunk = false;
        }
        answer += text;
        setMessageText(assistantNode, "assistant", answer);
      },
      onTrace(trace) {
        renderTrace(trace);
      },
      onError(message) {
        removeTypingIndicator();
        if (!assistantNode) {
          assistantNode = addMessage("assistant", message, true);
        } else {
          setMessageText(assistantNode, "assistant", message, true);
        }
      },
    });

    // 如果流结束但没有收到任何 chunk（比如只有 trace），移除打字指示器
    removeTypingIndicator();
    if (!assistantNode && !firstChunk) {
      // 不太可能到达，但兜底
    }
  } catch (error) {
    removeTypingIndicator();
    addMessage("assistant", error.message, true);
  } finally {
    sendBtn.classList.remove("loading");
    sendBtn.disabled = false;
    input.focus();
  }
});

async function readChatStream(res, handlers) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      handleStreamLine(line, handlers);
    }
  }
  if (buffer.trim()) {
    handleStreamLine(buffer, handlers);
  }
}

function handleStreamLine(line, handlers) {
  if (!line.trim()) return;
  try {
    const event = JSON.parse(line);
    if (event.type === "status") handlers.onStatus?.(event);
    if (event.type === "chunk") handlers.onChunk?.(event.text || "");
    if (event.type === "trace") handlers.onTrace?.(event.trace || []);
    if (event.type === "error") handlers.onError?.(event.message || "stream error");
  } catch (e) {
    // 忽略 JSON 解析失败的行
  }
}

// ============================================
//  其他事件绑定
// ============================================

// 展开全部 trace 分组和事件
document.querySelector("#expandAllTrace").addEventListener("click", () => {
  document.querySelectorAll(".flow-group").forEach((g) => {
    g.classList.remove("collapsed");
    g.querySelector(".flow-group-head")?.setAttribute("aria-expanded", "true");
  });
  document.querySelectorAll(".trace-group").forEach((g) => g.classList.remove("collapsed"));
  document.querySelectorAll(".event").forEach((e) => e.classList.add("expanded"));
});

// 收起全部 trace 分组和事件
document.querySelector("#collapseAllTrace").addEventListener("click", () => {
  document.querySelectorAll(".event").forEach((e) => e.classList.remove("expanded"));
  document.querySelectorAll(".trace-group").forEach((g) => g.classList.add("collapsed"));
  document.querySelectorAll(".flow-group").forEach((g) => {
    g.classList.add("collapsed");
    g.querySelector(".flow-group-head")?.setAttribute("aria-expanded", "false");
  });
});

clearTrace.addEventListener("click", () => {
  requestTraceEvents = [];
  renderTracePanel();
});

viewLogs.addEventListener("click", async () => {
  try {
    const res = await fetch("/logs?lines=80");
    const payload = await res.json();
    renderTrace([
      {
        stage: "backend-log",
        detail: payload.log_file,
        data: { lines: payload.lines || [] },
      },
    ]);
  } catch (err) {
    toast("获取日志失败：" + err.message, "error");
  }
});

providerSelect.addEventListener("change", async () => {
  apiKey.value = localStorage.getItem(apiKeyStorageName()) || "";
  await loadModels(providerSelect.value);
  updateModelInfoHint();
  toast(`已切换到 ${currentProvider()?.name || providerSelect.value}`, "info");
});

agentId.addEventListener("change", () => {
  localStorage.setItem("anpaw.agentId", agentId.value);
  requestTraceEvents = [];
  renderTracePanel();
  addMessage("assistant", `已切换到智能体：${agentId.value}`);
  toast(`智能体已切换为 ${agentId.value}`, "success");
});

modelSelect.addEventListener("change", () => {
  localStorage.setItem(modelStorageName(), modelSelect.value);
  updateModelInfoHint();
});

refreshModels.addEventListener("click", async () => {
  await loadModels(providerSelect.value, true);
  toast("模型列表已刷新", "success");
});

testModel.addEventListener("click", async () => {
  testModel.disabled = true;
  updateModelInfoHint("testing...");
  try {
    const res = await fetch("/model-test", {
      method: "POST",
      headers: { "content-type": "application/json" },
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
      addMessage("assistant", `模型连通成功（${payload.auth || "no_key"}）：${payload.message}`);
      toast("模型连通成功", "success");
    } else {
      updateModelInfoHint("not connected");
      addMessage(
        "assistant",
        `模型测试失败（${payload.auth || "no_key"}）：${payload.message}\n\n免费模型可能会被公共池限流，换一个模型或稍后重试即可。`,
        true
      );
      toast("模型测试失败", "error");
    }
  } catch (error) {
    updateModelInfoHint("test failed");
    addMessage("assistant", error.message, true);
    toast("测试请求失败", "error");
  } finally {
    testModel.disabled = false;
  }
});

// ============================================
//  启动
// ============================================

// 空状态作为首屏视图，点击建议词或直接输入消息后自动消失。
// 配置加载完成后在顶部 modelInfo 中显示当前模型信息。
loadConfig();
