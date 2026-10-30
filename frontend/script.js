/* ==========================================================================
   Bug Buster - script.js
   Upload + preview, validation, loading state, backend connection, results.

   Backend contract (see backend/main.py):
   - GET  {API}/health
   - POST {API}/analyze-bug   multipart/form-data: image, repo_path, issue_hint (optional)

   All text from the model is written with textContent (never innerHTML),
   and nothing here ever applies a patch to a repository.
   ========================================================================== */

"use strict";

const DEFAULT_API_URL = "http://localhost:8000";
const STORAGE_KEY = "bugbuster.apiUrl";
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const REQUEST_TIMEOUT_MS = 10 * 60 * 1000; // local models can be slow

const $ = (id) => document.getElementById(id);

const el = {
  form: $("analyze-form"),
  uploadWrap: $("upload-wrap"),
  dropZone: $("drop-zone"),
  imageInput: $("image-input"),
  previewImg: $("preview-img"),
  previewName: $("preview-name"),
  previewSize: $("preview-size"),
  removeImage: $("remove-image"),
  imageError: $("image-error"),
  repoPath: $("repo-path"),
  repoError: $("repo-error"),
  hint: $("issue-hint"),
  hintCount: $("hint-count"),
  submit: $("submit-btn"),
  submitLabel: document.querySelector("#submit-btn .btn-label"),
  elapsed: $("elapsed"),
  loadingElapsed: $("loading-elapsed"),
  results: $("results"),
  connPill: $("conn-pill"),
  connLabel: $("conn-label"),
  openSettings: $("open-settings"),
  dialog: $("settings-dialog"),
  apiInput: $("api-url-input"),
  saveSettings: $("save-settings"),
  resetSettings: $("reset-settings"),
  closeSettings: $("close-settings"),
  settingsError: $("settings-error"),
  toast: $("toast"),
};

let selectedFile = null;
let previewUrl = null;
let controller = null;
let timerId = null;
let toastTimer = null;

/* ---------- Settings / API address ---------- */
function getApiUrl() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_API_URL;
  } catch (_) {
    return DEFAULT_API_URL;
  }
}

function setApiUrl(url) {
  try {
    if (url === DEFAULT_API_URL) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, url);
  } catch (_) {
    /* storage unavailable: setting lasts only for this page load */
  }
}

function normalizeUrl(raw) {
  const value = (raw || "").trim().replace(/\/+$/, "");
  try {
    const u = new URL(value);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.origin + (u.pathname === "/" ? "" : u.pathname.replace(/\/+$/, ""));
  } catch (_) {
    return null;
  }
}

/* ---------- Small helpers ---------- */
function showToast(message) {
  el.toast.textContent = message;
  el.toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.toast.classList.remove("is-visible"), 2400);
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function formatClock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ":" + String(s).padStart(2, "0");
}

function setError(node, message) {
  if (message) {
    node.textContent = message;
    node.hidden = false;
  } else {
    node.textContent = "";
    node.hidden = true;
  }
}

function setState(state) {
  el.results.dataset.state = state;
}

function fillList(listEl, items, emptyText) {
  listEl.textContent = "";
  const values = (items || []).filter(Boolean);
  if (!values.length) values.push(emptyText);
  for (const text of values) {
    const li = document.createElement("li");
    li.textContent = text;
    listEl.appendChild(li);
  }
}

/* ---------- Image upload + preview ---------- */
function clearImage() {
  selectedFile = null;
  el.imageInput.value = "";
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  el.previewImg.removeAttribute("src");
  el.uploadWrap.dataset.hasFile = "false";
  setError(el.imageError, "");
}

function acceptImage(file) {
  setError(el.imageError, "");
  if (!file) return;
  if (!ALLOWED_TYPES.includes(file.type)) {
    clearImage();
    setError(el.imageError, "Please choose a PNG, JPEG or WebP image.");
    return;
  }
  if (file.size > MAX_IMAGE_BYTES) {
    clearImage();
    setError(el.imageError, "That image is " + formatSize(file.size) + ". The limit is 10 MB.");
    return;
  }
  if (file.size === 0) {
    clearImage();
    setError(el.imageError, "That file is empty.");
    return;
  }
  selectedFile = file;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  el.previewImg.src = previewUrl;
  el.previewName.textContent = file.name || "screenshot";
  el.previewSize.textContent = formatSize(file.size);
  el.uploadWrap.dataset.hasFile = "true";
}

el.imageInput.addEventListener("change", () => acceptImage(el.imageInput.files[0]));
el.removeImage.addEventListener("click", clearImage);

["dragenter", "dragover"].forEach((evt) =>
  el.dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    el.dropZone.classList.add("is-dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  el.dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    el.dropZone.classList.remove("is-dragover");
  })
);
el.dropZone.addEventListener("drop", (e) => {
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  acceptImage(file);
});

// Pasting a screenshot (Cmd/Ctrl+V) anywhere on the page also works.
document.addEventListener("paste", (e) => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  for (const item of items) {
    if (item.kind === "file" && item.type.startsWith("image/")) {
      acceptImage(item.getAsFile());
      showToast("Screenshot pasted");
      return;
    }
  }
});

/* ---------- Form fields ---------- */
el.hint.addEventListener("input", () => {
  el.hintCount.textContent = String(el.hint.value.length);
});
el.repoPath.addEventListener("input", () => {
  el.repoPath.removeAttribute("aria-invalid");
  setError(el.repoError, "");
});

function validate() {
  let ok = true;
  if (!selectedFile) {
    setError(el.imageError, "Add a screenshot of the bug first.");
    ok = false;
  }
  if (!el.repoPath.value.trim()) {
    el.repoPath.setAttribute("aria-invalid", "true");
    setError(el.repoError, "Enter the full path to your project folder.");
    ok = false;
  }
  if (!ok) {
    const first = !selectedFile ? el.dropZone : el.repoPath;
    first.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  return ok;
}

/* ---------- Loading state ---------- */
function startTimer() {
  const began = Date.now();
  const tick = () => {
    const secs = (Date.now() - began) / 1000;
    el.elapsed.textContent = formatClock(secs);
    el.loadingElapsed.textContent = formatClock(secs);
  };
  tick();
  timerId = setInterval(tick, 1000);
}

function stopTimer() {
  clearInterval(timerId);
  timerId = null;
}

function setLoading(on) {
  el.submit.classList.toggle("is-loading", on);
  el.submit.disabled = on;
  el.submit.setAttribute("aria-busy", on ? "true" : "false");
  el.submitLabel.textContent = on ? "Investigating" : "Exorcise bug";
  if (on) {
    setState("loading");
    startTimer();
  } else {
    stopTimer();
    el.elapsed.textContent = "";
  }
}

/* ---------- Errors ---------- */
const ERROR_TITLES = {
  ollama_unreachable: "Ollama is not running",
  model_missing: "Model not installed",
  model_timeout: "The model took too long",
  model_bad_output: "The model gave an unusable answer",
  empty_model_answer: "The model returned nothing",
  upload_too_large: "Image too large",
  network: "Cannot reach the backend",
  timeout: "The request timed out",
};

function showError(code, message) {
  $("error-title").textContent = ERROR_TITLES[code] || "Something went wrong";
  $("error-message").textContent = message || "The backend returned an error.";
  $("error-code").textContent = code || "error";
  setState("error");
  el.results.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Rendering results ---------- */
function renderDiff(diffText) {
  const code = $("git-diff");
  code.textContent = "";
  const lines = String(diffText).replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
  const frag = document.createDocumentFragment();
  for (const line of lines) {
    const span = document.createElement("span");
    let kind = "ctx";
    if (line.startsWith("@@")) kind = "hunk";
    else if (/^(diff --git|index |--- |\+\+\+ |new file|deleted file)/.test(line)) kind = "meta";
    else if (line.startsWith("+")) kind = "add";
    else if (line.startsWith("-")) kind = "del";
    span.className = "diff-line " + kind;
    span.textContent = line === "" ? " " : line;
    frag.appendChild(span);
  }
  code.appendChild(frag);
}

function renderResult(data) {
  const a = data.analysis || {};
  const confidence = a.confidence || "likely";

  if (confidence === "insufficient") {
    $("insufficient-reason").textContent = data.root_cause || "";
    $("insufficient-details").textContent =
      a.screenshot_analysis || "No screenshot description was returned.";
    setState("insufficient");
    el.results.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const conf = $("confidence-badge");
  conf.dataset.tone = confidence === "confirmed" ? "confirmed" : "likely";
  conf.textContent = confidence === "confirmed" ? "Confirmed" : "Likely";

  const verified = $("verified-badge");
  const hasDiff = Boolean(data.git_diff && data.git_diff.trim());
  verified.hidden = !hasDiff;
  verified.dataset.tone = a.patch_verified ? "verified" : "unverified";
  verified.textContent = a.patch_verified ? "Patch verified" : "Patch unverified";

  $("meta-model").textContent = a.model || "local model";
  $("meta-elapsed").textContent = (a.elapsed_seconds ?? 0).toFixed(1);

  $("culprit-file").textContent = data.culprit_file || "-";
  const lines = $("culprit-lines");
  if (a.culprit_lines) {
    lines.textContent = "lines " + a.culprit_lines;
    lines.hidden = false;
  } else {
    lines.hidden = true;
  }
  $("root-cause").textContent = data.root_cause || "-";

  const diffEmpty = $("diff-empty");
  const diffCode = $("git-diff");
  const diffBlock = diffCode.closest("pre");
  const copyDiff = $("copy-diff");
  if (hasDiff) {
    renderDiff(data.git_diff);
    diffBlock.hidden = false;
    diffEmpty.hidden = true;
    copyDiff.hidden = false;
  } else {
    diffCode.textContent = "";
    diffBlock.hidden = true;
    diffEmpty.hidden = false;
    copyDiff.hidden = true;
  }

  const notes = [...(a.patch_warnings || []), ...(a.patch_errors || [])];
  const warnEl = $("patch-warnings");
  warnEl.textContent = "";
  for (const note of notes) {
    const li = document.createElement("li");
    li.textContent = note;
    warnEl.appendChild(li);
  }
  warnEl.hidden = notes.length === 0;

  $("fixed-code").textContent = data.fixed_code || "";
  $("copy-fixed").hidden = !data.fixed_code;

  fillList($("evidence-list"), a.evidence, "No confirmed evidence was returned.");
  fillList($("guesses-list"), a.guesses, "No guesses were reported.");
  fillList($("files-list"), a.files_analyzed, "No file list was returned.");
  $("screenshot-analysis").textContent = a.screenshot_analysis || "Not available.";

  setState("success");
  el.results.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Copy buttons ---------- */
async function copyText(text, button, label) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const ta = document.createElement("textarea"); // fallback for plain http / old browsers
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch (__) {
      showToast("Copy failed. Select the text and copy it manually.");
      ta.remove();
      return;
    }
    ta.remove();
  }
  const labelEl = button.querySelector(".copy-label");
  button.classList.add("is-copied");
  if (labelEl) labelEl.textContent = "Copied";
  showToast(label + " copied");
  setTimeout(() => {
    button.classList.remove("is-copied");
    if (labelEl) labelEl.textContent = button.dataset.label;
  }, 1800);
}

for (const [id, target, label] of [
  ["copy-diff", "git-diff", "Diff"],
  ["copy-fixed", "fixed-code", "Code"],
]) {
  const btn = $(id);
  btn.dataset.label = btn.querySelector(".copy-label").textContent;
  btn.addEventListener("click", () => copyText($(target).textContent, btn, label));
}

/* ---------- Backend: health ---------- */
async function checkHealth() {
  el.connPill.dataset.status = "checking";
  el.connLabel.textContent = "Checking backend";
  const base = getApiUrl();
  try {
    const res = await fetch(base + "/health", { cache: "no-store" });
    let body = {};
    try {
      body = await res.json();
    } catch (_) {
      /* ignore */
    }
    if (res.ok && body.status === "ok") {
      el.connPill.dataset.status = "online";
      el.connLabel.textContent = "Backend online";
      el.connPill.title = "Connected to " + base + " (model " + (body.model || "?") + ")";
    } else {
      el.connPill.dataset.status = "degraded";
      el.connLabel.textContent = "Backend needs attention";
      el.connPill.title = body.detail || "The backend answered but is not ready.";
    }
  } catch (_) {
    el.connPill.dataset.status = "offline";
    el.connLabel.textContent = "Backend offline";
    el.connPill.title = "Cannot reach " + base + ". Start the backend, or change the URL in settings.";
  }
}

/* ---------- Backend: analyze ---------- */
async function analyze(event) {
  event.preventDefault();
  if (el.submit.disabled) return;
  setError(el.imageError, "");
  setError(el.repoError, "");
  if (!validate()) return;

  const fd = new FormData();
  fd.append("image", selectedFile, selectedFile.name || "screenshot.png");
  fd.append("repo_path", el.repoPath.value.trim());
  const hint = el.hint.value.trim();
  if (hint) fd.append("issue_hint", hint);

  controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("timeout"), REQUEST_TIMEOUT_MS);
  setLoading(true);

  try {
    const res = await fetch(getApiUrl() + "/analyze-bug", {
      method: "POST",
      body: fd,
      signal: controller.signal,
    });
    let body = null;
    try {
      body = await res.json();
    } catch (_) {
      /* non-JSON error */
    }
    if (!res.ok) {
      const detail =
        body && typeof body.detail === "string"
          ? body.detail
          : body && Array.isArray(body.detail)
          ? body.detail.map((d) => d.msg).join(" ")
          : "The backend returned HTTP " + res.status + ".";
      showError((body && body.error) || "http_" + res.status, detail);
      return;
    }
    if (!body || typeof body !== "object" || !("culprit_file" in body)) {
      showError("bad_response", "The backend sent a response this page does not understand.");
      return;
    }
    renderResult(body);
  } catch (err) {
    if (controller.signal.aborted) {
      if (controller.signal.reason === "timeout") {
        showError("timeout", "No answer after 10 minutes. Try a smaller repo or a faster model.");
      } else {
        setState("idle");
      }
    } else {
      showError(
        "network",
        "Could not reach the backend at " + getApiUrl() + ". Make sure it is running, then press Try again."
      );
      checkHealth();
    }
  } finally {
    clearTimeout(timeout);
    controller = null;
    setLoading(false);
  }
}

el.form.addEventListener("submit", analyze);
$("retry-btn").addEventListener("click", () => {
  el.form.requestSubmit();
});

/* ---------- Settings dialog ---------- */
el.openSettings.addEventListener("click", () => {
  el.apiInput.value = getApiUrl();
  setError(el.settingsError, "");
  el.dialog.showModal();
  el.apiInput.focus();
});
el.closeSettings.addEventListener("click", () => el.dialog.close());
el.resetSettings.addEventListener("click", () => {
  el.apiInput.value = DEFAULT_API_URL;
  setError(el.settingsError, "");
});
el.saveSettings.addEventListener("click", () => {
  const url = normalizeUrl(el.apiInput.value);
  if (!url) {
    setError(el.settingsError, "Enter a full address such as http://localhost:8000");
    return;
  }
  setApiUrl(url);
  el.dialog.close();
  showToast("Backend set to " + url);
  checkHealth();
});

/* ---------- Start ---------- */
checkHealth();
setInterval(() => {
  if (!document.hidden && !el.submit.disabled) checkHealth();
}, 30000);
