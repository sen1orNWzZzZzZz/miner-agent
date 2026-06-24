(function () {
  "use strict";

  console.log("[app] app.js loaded");

  const $ = (id) => document.getElementById(id);

  let attachments = [];

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function renderAttachments() {
    const list = $("attachment-list");
    if (!list) return;
    list.innerHTML = attachments
      .map(
        (name, idx) =>
          `<span class="inline-flex items-center gap-1 px-2 py-1 bg-indigo-50 text-indigo-700 rounded-md text-xs">
            📄 ${escapeHtml(name)}
            <button type="button" data-idx="${idx}" class="attach-remove text-indigo-500 hover:text-indigo-800 font-bold ml-1">×</button>
          </span>`
      )
      .join("");
    list.querySelectorAll(".attach-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        attachments.splice(parseInt(btn.dataset.idx, 10), 1);
        renderAttachments();
      });
    });
  }

  function showStatus(elId, message, type = "info") {
    const el = $(elId);
    el.textContent = message;
    el.className = `mt-3 text-sm ${type === "success" ? "status-success" : type === "error" ? "status-error" : "status-info"}`;
    el.classList.remove("hidden");
  }

  function hideStatus(elId) {
    const el = $(elId);
    el.classList.add("hidden");
  }

  function validatePdf(file) {
    if (!file) return "未选择文件";
    if (file.type !== "application/pdf") return `文件类型 ${file.type || "未知"} 不是 PDF`;
    if (!file.name.toLowerCase().endsWith(".pdf")) return "文件扩展名不是 .pdf";
    return null;
  }

  async function loadConfig() {
    console.log("[app] loadConfig start");
    try {
      const res = await fetch("/api/config/llm");
      if (!res.ok) throw new Error("加载配置失败");
      const cfg = await res.json();
      console.log("[app] loadConfig success", cfg.provider, cfg.model);
      $("provider").value = cfg.provider || "openai";
      $("model").value = cfg.model || "gpt-4o-mini";
      $("base_url").value = cfg.base_url || "";
      $("api_key").value = cfg.api_key || "";
      $("use_mock").checked = !!cfg.use_mock;
      updateModeBadge(cfg.use_mock, cfg.api_key);
    } catch (err) {
      console.error("[app] loadConfig failed", err);
      showStatus("config-status", err.message, "error");
      const badge = $("mode-badge");
      badge.textContent = "配置加载失败";
      badge.className = "text-xs px-2 py-1 rounded-full bg-red-100 text-red-700";
    }
  }

  function updateModeBadge(useMock, apiKey) {
    const badge = $("mode-badge");
    if (useMock) {
      badge.textContent = "Mock 模式";
      badge.className = "text-xs px-2 py-1 rounded-full bg-amber-100 text-amber-700";
    } else if (apiKey) {
      badge.textContent = "真实模型";
      badge.className = "text-xs px-2 py-1 rounded-full bg-emerald-100 text-emerald-700";
    } else {
      badge.textContent = "未配置模型";
      badge.className = "text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-600";
    }
  }

  // Modal controls
  function openModal() {
    $("config-modal").classList.remove("hidden");
    hideStatus("config-status");
  }

  function closeModal() {
    $("config-modal").classList.add("hidden");
  }

  $("open-config").addEventListener("click", openModal);
  $("close-config").addEventListener("click", closeModal);
  $("config-modal").addEventListener("click", (e) => {
    if (e.target.id === "config-modal") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("config-modal").classList.contains("hidden")) {
      closeModal();
    }
  });

  $("llm-config-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    hideStatus("config-status");
    const payload = {
      provider: $("provider").value,
      model: $("model").value,
      base_url: $("base_url").value || null,
      api_key: $("api_key").value || null,
      use_mock: $("use_mock").checked,
    };

    try {
      const res = await fetch("/api/config/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "保存失败");
      showStatus("config-status", "配置已保存", "success");
      updateModeBadge(data.use_mock, data.api_key);
    } catch (err) {
      showStatus("config-status", err.message, "error");
    }
  });

  $("test-config").addEventListener("click", async () => {
    hideStatus("config-status");
    showStatus("config-status", "正在测试连接…", "info");
    try {
      const res = await fetch("/api/config/llm/test", { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        showStatus("config-status", `连接成功（${data.mode}）：${data.message}`, "success");
      } else {
        showStatus("config-status", data.message, "error");
      }
    } catch (err) {
      showStatus("config-status", `测试失败：${err.message}`, "error");
    }
  });

  // --- Metals price API config ---
  async function loadPriceConfig() {
    try {
      const res = await fetch("/api/config/price");
      if (!res.ok) throw new Error("加载价格配置失败");
      const cfg = await res.json();
      $("price_provider").value = cfg.provider || "metalpriceapi";
      $("price_base_url").value = cfg.base_url || "";
      $("price_api_key").value = cfg.api_key || "";
      $("price_use_mock").checked = !!cfg.use_mock;
    } catch (err) {
      console.error("[app] loadPriceConfig failed", err);
    }
  }

  $("price-config-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    hideStatus("price-config-status");
    const payload = {
      provider: $("price_provider").value,
      base_url: $("price_base_url").value || null,
      api_key: $("price_api_key").value || null,
      use_mock: $("price_use_mock").checked,
    };
    try {
      const res = await fetch("/api/config/price", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "保存失败");
      showStatus("price-config-status", "价格配置已保存", "success");
    } catch (err) {
      showStatus("price-config-status", err.message, "error");
    }
  });

  $("test-price-config").addEventListener("click", async () => {
    hideStatus("price-config-status");
    showStatus("price-config-status", "正在测试连接…", "info");
    try {
      const res = await fetch("/api/config/price/test", { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        showStatus("price-config-status", `连接成功（${data.mode}）：${data.message}`, "success");
      } else {
        showStatus("price-config-status", data.message, "error");
      }
    } catch (err) {
      showStatus("price-config-status", `测试失败：${err.message}`, "error");
    }
  });

  $("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const queryEl = $("query");
    const query = queryEl.value.trim();
    if (!query) return;

    const history = $("chat-history");
    const sendBtn = $("send-btn");

    // User message
    const userDiv = document.createElement("div");
    userDiv.className = "user-message";
    userDiv.textContent = query;
    history.appendChild(userDiv);
    queryEl.value = "";
    sendBtn.disabled = true;
    history.scrollTop = history.scrollHeight;

    // Loading indicator
    const botDiv = document.createElement("div");
    botDiv.className = "bot-message";
    botDiv.innerHTML = "<span class='text-slate-400'>Agent 正在调用工具并生成简报…</span>";
    history.appendChild(botDiv);
    history.scrollTop = history.scrollHeight;

    try {
      const res = await fetch("/briefing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, attachments }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "生成失败");
      const cachedNote = data.cached
        ? `<div class="cache-hint">♻️ 缓存命中：30 分钟内的相同请求，直接返回上次结果（未消耗新 token）。</div>`
        : "";
      botDiv.innerHTML = cachedNote + marked.parse(data.markdown);
    } catch (err) {
      botDiv.innerHTML = `<span class="text-red-600">错误：${escapeHtml(err.message)}</span>`;
    } finally {
      sendBtn.disabled = false;
      history.scrollTop = history.scrollHeight;
    }
  });

  $("attach-file").addEventListener("change", async () => {
    const fileInput = $("attach-file");
    if (!fileInput.files || fileInput.files.length === 0) return;

    const file = fileInput.files[0];
    const validationError = validatePdf(file);
    if (validationError) {
      showStatus("config-status", `附件上传失败：${validationError}`, "error");
      fileInput.value = "";
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    const history = $("chat-history");
    const uploadDiv = document.createElement("div");
    uploadDiv.className = "bot-message";
    uploadDiv.innerHTML = "<span class='text-slate-400'>正在上传 PDF 附件…</span>";
    history.appendChild(uploadDiv);
    history.scrollTop = history.scrollHeight;

    try {
      const res = await fetch("/api/upload/pdf", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "上传失败");

      attachments.push(data.filename);
      renderAttachments();
      const cachedTag = data.cached ? "（♻️ 缓存命中，未消耗新 token）" : "";
      uploadDiv.innerHTML = `已上传附件 <strong>${escapeHtml(data.filename)}</strong>${cachedTag}，可在后续提问中引用。`;

      if (data.summary) {
        const summaryDiv = document.createElement("div");
        summaryDiv.className = "bot-message";
        summaryDiv.innerHTML = `<div class="text-sm font-medium mb-1">📄 PDF 自然语言摘要</div>${marked.parse(data.summary)}`;
        history.appendChild(summaryDiv);
      }
    } catch (err) {
      uploadDiv.innerHTML = `<span class="text-red-600">附件上传失败：${escapeHtml(err.message)}</span>`;
    } finally {
      fileInput.value = "";
      history.scrollTop = history.scrollHeight;
    }
  });

  $("upload-pdf").addEventListener("click", async () => {
    const fileInput = $("pdf-file");
    if (!fileInput.files || fileInput.files.length === 0) {
      showStatus("pdf-status", "请先选择一个 PDF 文件", "error");
      return;
    }

    const file = fileInput.files[0];
    const validationError = validatePdf(file);
    if (validationError) {
      showStatus("pdf-status", validationError, "error");
      return;
    }

    hideStatus("pdf-status");
    $("pdf-result").classList.add("hidden");

    const formData = new FormData();
    formData.append("file", file);

    showStatus("pdf-status", "正在上传并解析…", "info");
    try {
      const res = await fetch("/api/upload/pdf", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "解析失败");
      const cachedTag = data.cached ? "（♻️ 缓存命中）" : "";
      showStatus("pdf-status", `解析成功：${data.filename}${cachedTag}`, "success");
      if (data.summary) {
        $("pdf-result").innerHTML = `<div class="font-medium mb-1">自然语言总结</div><div class="text-slate-700 whitespace-pre-line">${escapeHtml(data.summary)}</div>`;
      } else {
        $("pdf-result").textContent = JSON.stringify(data.result, null, 2);
      }
      $("pdf-result").classList.remove("hidden");
    } catch (err) {
      showStatus("pdf-status", err.message, "error");
    }
  });

  loadConfig();
  loadPriceConfig();
})();
