const state = {
  tabs: [],
  activeId: null,
  bridge: null,
  saveTimer: null
};

const editor = document.getElementById("editor");
const highlight = document.getElementById("highlight");
const gutter = document.getElementById("gutter");
const tabList = document.getElementById("tabList");
const tabStrip = document.getElementById("tabStrip");
const consoleBody = document.getElementById("consoleBody");
const cursorStatus = document.getElementById("cursorStatus");

const keywords = new Set([
  "and","break","do","else","elseif","end","for","function","if","in","local","nil",
  "not","or","repeat","return","then","until","while","continue","export","const"
]);

const builtins = new Set([
  "print","warn","require","pcall","xpcall","pairs","ipairs","next","type","tonumber",
  "tostring","assert","game","workspace","Instance","Enum","Vector2","Vector3","CFrame",
  "Color3","UDim","UDim2","task","coroutine","math","string","table","debug","utf8",
  "loadstring","getgenv","writefile","readfile","isfile","isfolder","makefolder",
  "delfile","delfolder","listfiles","setclipboard","getclipboard","identifyexecutor",
  "getexecutorname","setfpscap","getfpscap","getcustomasset","WebSocket","Drawing"
]);

function escapeHtml(text){
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function highlightLuau(source){
  const stash = [];
  function protect(html){
    const token = "___AKAZ_TOKEN_" + stash.length + "___";
    stash.push(html);
    return token;
  }

  let text = source;

  text = text.replace(/--\[\[[\s\S]*?\]\]|--[^\n]*/g, function(m){
    return protect('<span class="token-comment">' + escapeHtml(m) + "</span>");
  });

  text = escapeHtml(text);

  text = text.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, function(m){
    return protect('<span class="token-string">' + m + "</span>");
  });

  text = text.replace(/\b\d+(?:\.\d+)?\b/g, function(m){
    return '<span class="token-number">' + m + "</span>";
  });

  text = text.replace(/\b[A-Za-z_]\w*\b/g, function(m){
    if (keywords.has(m)) return '<span class="token-keyword">' + m + "</span>";
    if (builtins.has(m)) return '<span class="token-builtin">' + m + "</span>";
    return m;
  });

  text = text.replace(/\b([A-Za-z_]\w*)(?=\s*\()/g,
    '<span class="token-function">$1</span>');

  return text.replace(/___AKAZ_TOKEN_(\d+)___/g, function(_, index){
    return stash[Number(index)];
  });
}

function renderEditor(){
  const source = editor.value;
  highlight.innerHTML = highlightLuau(source) + (source.endsWith("\n") ? " " : "");
  const lineCount = Math.max(1, source.split("\n").length);
  gutter.innerHTML = Array.from({length: lineCount}, function(_, i){
    return String(i + 1);
  }).join("<br>");

  highlight.scrollTop = editor.scrollTop;
  highlight.scrollLeft = editor.scrollLeft;
  gutter.scrollTop = editor.scrollTop;
  updateCursor();
}

function updateCursor(){
  const before = editor.value.slice(0, editor.selectionStart);
  const parts = before.split("\n");
  cursorStatus.textContent =
    "Ln " + parts.length + ", Col " + (parts[parts.length - 1].length + 1);
}

function activeTab(){
  return state.tabs.find(function(tab){ return tab.id === state.activeId; }) || null;
}

function makeId(){
  return "script-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

function persistSoon(){
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(persistNow, 350);
}

function persistNow(){
  const current = activeTab();
  if (current) current.content = editor.value;
  if (state.bridge) state.bridge.save_tabs(JSON.stringify(state.tabs));
}

function setActive(id){
  const old = activeTab();
  if (old) old.content = editor.value;

  state.activeId = id;
  const current = activeTab();
  if (!current) return;

  editor.value = current.content || "";
  document.getElementById("breadcrumbName").textContent = current.name;
  renderEditor();
  renderTabs();
  editor.focus();
}

function renderTabs(){
  tabList.innerHTML = "";
  tabStrip.querySelectorAll(".script-tab").forEach(function(node){ node.remove(); });

  state.tabs.forEach(function(tab){
    const item = document.createElement("div");
    item.className = "tab-item" + (tab.id === state.activeId ? " active" : "");
    item.dataset.tab = tab.id;
    item.innerHTML =
      '<span class="file-icon">λ</span><span class="tab-name">' +
      escapeHtml(tab.name) + "</span>";
    item.addEventListener("click", function(){ setActive(tab.id); });
    tabList.appendChild(item);

    const stripTab = document.createElement("div");
    stripTab.className =
      "workspace-tab script-tab" + (tab.id === state.activeId ? " active" : "");
    stripTab.dataset.id = tab.id;
    stripTab.innerHTML =
      '<span class="tab-dot"></span><span class="tab-title">' +
      escapeHtml(tab.name) +
      '</span><button class="tab-close" title="Close">×</button>';

    stripTab.addEventListener("click", function(e){
      if (!e.target.classList.contains("tab-close")) setActive(tab.id);
    });

    stripTab.querySelector(".tab-close").addEventListener("click", function(e){
      e.stopPropagation();
      closeTab(tab.id);
    });

    tabStrip.appendChild(stripTab);
  });
}

function addTab(){
  const tab = {
    id: makeId(),
    name: "Script " + (state.tabs.length + 1),
    content: 'print("Hello, World!")'
  };
  state.tabs.push(tab);
  setActive(tab.id);
  persistNow();
}

function closeTab(id){
  if (state.tabs.length === 1){
    state.tabs[0].content = "";
    editor.value = "";
    renderEditor();
    persistNow();
    return;
  }

  const index = state.tabs.findIndex(function(tab){ return tab.id === id; });
  if (index < 0) return;

  state.tabs.splice(index, 1);

  if (state.activeId === id){
    const next = state.tabs[Math.max(0, index - 1)];
    state.activeId = next.id;
    editor.value = next.content || "";
  }

  renderTabs();
  renderEditor();
  persistNow();
}

function log(message, level){
  const row = document.createElement("div");
  row.className = "log " + (level || "info");
  row.textContent =
    "[" + new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"}) +
    "] " + message;
  consoleBody.appendChild(row);
  consoleBody.scrollTop = consoleBody.scrollHeight;
}

function applyStatus(data){
  const stateMap = {
    offline: "Offline",
    loading: "Loading",
    ready: "Ready",
    injecting: "Attaching",
    executing: "Running",
    attached: "Attached",
    error: "Error"
  };

  const label = stateMap[data.state] || data.state || "Offline";
  document.getElementById("runtimeStatusText").textContent = label;
  document.getElementById("runtimeDetail").textContent = data.detail || "—";
  document.getElementById("runtimeState").textContent = label;

  let color = "#65707a";
  if (data.state === "attached" || data.state === "ready") color = "#78c69a";
  if (data.state === "injecting" || data.state === "executing" || data.state === "loading") color = "#d4ad69";
  if (data.state === "error") color = "#ca7373";

  document.getElementById("runtimeLed").style.background = color;
  document.querySelector("#railState span").style.background = color;
  document.querySelector(".state-dot").style.background = color;
}

function applyRuntime(data){
  document.getElementById("runtimePid").textContent = data.pid || "—";
  document.getElementById("runtimeVersion").textContent = data.version || "—";
  document.getElementById("sessionRoblox").textContent = data.roblox ? "Yes" : "No";
  document.getElementById("sessionInjected").textContent = data.injected ? "Yes" : "No";

  applyStatus({
    state: data.injected ? "attached" : (data.roblox ? "ready" : "offline"),
    detail: data.injected ? "Runtime attached" :
      (data.roblox ? "Roblox detected" : "Roblox not detected")
  });
}

function switchScreen(name){
  document.querySelectorAll("[data-screen-panel]").forEach(function(panel){
    panel.classList.toggle("hidden", panel.dataset.screenPanel !== name);
  });

  document.querySelectorAll(".rail-btn").forEach(function(btn){
    btn.classList.toggle("active", btn.dataset.screen === name);
  });
}

function runCurrent(){
  persistNow();
  if (!state.bridge) return log("Bridge unavailable", "error");
  log("Run requested", "info");
  state.bridge.execute(editor.value);
}

function importScript(){
  if (!state.bridge) return;
  state.bridge.open_file("Open Luau script", function(content){
    if (!content) return;
    editor.value = content;
    const tab = activeTab();
    if (tab) tab.content = content;
    renderEditor();
    persistNow();
    log("Script imported", "success");
  });
}

function exportScript(){
  if (!state.bridge) return;
  const tab = activeTab();
  const safeName = (tab ? tab.name : "Script").replace(/[^\w-]/g, "_");
  state.bridge.save_file(editor.value, safeName + ".luau", function(path){
    if (path) log("Saved " + path, "success");
  });
}

editor.addEventListener("input", function(){
  renderEditor();
  persistSoon();
});

editor.addEventListener("keyup", updateCursor);
editor.addEventListener("click", updateCursor);
editor.addEventListener("select", updateCursor);

editor.addEventListener("scroll", function(){
  highlight.scrollTop = editor.scrollTop;
  highlight.scrollLeft = editor.scrollLeft;
  gutter.scrollTop = editor.scrollTop;
});

editor.addEventListener("keydown", function(e){
  if (e.ctrlKey && e.key === "Enter"){
    e.preventDefault();
    runCurrent();
    return;
  }

  if (e.ctrlKey && e.key.toLowerCase() === "s"){
    e.preventDefault();
    exportScript();
    return;
  }

  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "n"){
    e.preventDefault();
    addTab();
    return;
  }

  if (e.key === "Tab"){
    e.preventDefault();
    editor.setRangeText("    ", editor.selectionStart, editor.selectionEnd, "end");
    renderEditor();
    persistSoon();
  }
});

document.getElementById("newTab").addEventListener("click", addTab);
document.getElementById("importBtn").addEventListener("click", importScript);
document.getElementById("exportBtn").addEventListener("click", exportScript);
document.getElementById("runBtn").addEventListener("click", runCurrent);
document.getElementById("injectBtn").addEventListener("click", function(){
  if (state.bridge) state.bridge.inject();
});

document.getElementById("clearConsole").addEventListener("click", function(){
  consoleBody.innerHTML = "";
});

document.getElementById("collapseConsole").addEventListener("click", function(){
  document.getElementById("consolePanel").classList.toggle("collapsed");
});

document.getElementById("refreshRuntime").addEventListener("click", function(){
  if (!state.bridge) return;
  state.bridge.runtime_info(function(info){
    try { applyRuntime(JSON.parse(info)); } catch {}
  });
});

document.getElementById("refreshTabs").addEventListener("click", function(){
  if (!state.bridge) return;
  state.bridge.load_tabs(function(data){
    try { state.tabs = JSON.parse(data); } catch { state.tabs = []; }
    if (!state.tabs.length){
      addTab();
      return;
    }
    const preferred = state.activeId && state.tabs.some(function(tab){
      return tab.id === state.activeId;
    }) ? state.activeId : state.tabs[0].id;
    setActive(preferred);
  });
});

document.getElementById("searchTabs").addEventListener("input", function(e){
  const query = e.target.value.toLowerCase();
  tabList.querySelectorAll(".tab-item").forEach(function(item){
    item.style.display =
      item.textContent.toLowerCase().includes(query) ? "" : "none";
  });
});

document.querySelectorAll(".rail-btn").forEach(function(btn){
  btn.addEventListener("click", function(){ switchScreen(btn.dataset.screen); });
});

document.querySelectorAll(".chrome-btn").forEach(function(btn){
  btn.addEventListener("click", function(){
    if (!state.bridge) return;
    const action = btn.dataset.action;
    if (action === "minimize") state.bridge.minimize();
    else if (action === "maximize") state.bridge.maximize_restore();
    else if (action === "close") state.bridge.close();
  });
});

document.getElementById("alwaysOnTop").addEventListener("change", function(e){
  if (state.bridge) state.bridge.set_topmost(e.target.checked);
});

document.getElementById("largeEditor").addEventListener("change", function(e){
  const size = e.target.checked ? "13px" : "12px";
  document.querySelectorAll(".highlight,.editor-stack textarea").forEach(function(el){
    el.style.fontSize = size;
  });
});

window.__akazStatus = applyStatus;
window.__akazLog = function(data){ log(data.message, data.level); };
window.__akazRuntime = applyRuntime;

window.addEventListener("load", function(){
  new QWebChannel(qt.webChannelTransport, function(channel){
    state.bridge = channel.objects.bridge;

    state.bridge.load_tabs(function(data){
      try { state.tabs = JSON.parse(data); } catch { state.tabs = []; }

      if (!state.tabs.length){
        addTab();
      } else {
        state.activeId = state.tabs[0].id;
        setActive(state.activeId);
      }

      renderTabs();
      log("Interface ready", "success");
    });

    state.bridge.runtime_info(function(info){
      try { applyRuntime(JSON.parse(info)); } catch {}
    });
  });
});
