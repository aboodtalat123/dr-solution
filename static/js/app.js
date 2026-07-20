const MAX_FILE_SIZE = 15 * 1024 * 1024;
const ALLOWED_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp"];
const THEME_KEY = "dr-solution.theme";
const API_KEY_STORAGE_PREFIX = "dr-solution.apikey-";
const DB_NAME = "dr-solution-study-library";
const DB_VERSION = 1;

const state = {
  file: null,
  result: null,
  providers: [],
  exportTheme: "emerald",
  progressTimer: null,
  toastTimer: null,
};

const elements = {
  views: document.querySelectorAll(".view"),
  workspaceView: document.getElementById("workspaceView"),
  processingView: document.getElementById("processingView"),
  resultsView: document.getElementById("resultsView"),
  historyView: document.getElementById("historyView"),
  analysisForm: document.getElementById("analysisForm"),
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("fileInput"),
  selectedFile: document.getElementById("selectedFile"),
  filePreview: document.getElementById("filePreview"),
  fileName: document.getElementById("fileName"),
  fileMeta: document.getElementById("fileMeta"),
  removeFileButton: document.getElementById("removeFileButton"),
  analyzeButton: document.getElementById("analyzeButton"),
  providerSelect: document.getElementById("providerSelect"),
  languageSelect: document.getElementById("languageSelect"),
  contentKindSelect: document.getElementById("contentKindSelect"),
  providerHint: document.getElementById("providerHint"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  toggleApiKeyButton: document.getElementById("toggleApiKeyButton"),
  providerKeyLink: document.getElementById("providerKeyLink"),
  connectionState: document.getElementById("connectionState"),
  versionLabel: document.getElementById("versionLabel"),
  questionsEnabled: document.getElementById("questionsEnabled"),
  questionOptions: document.getElementById("questionOptions"),
  questionCount: document.getElementById("questionCount"),
  questionMinus: document.getElementById("questionMinus"),
  questionPlus: document.getElementById("questionPlus"),
  progressBar: document.getElementById("progressBar"),
  progressPercent: document.getElementById("progressPercent"),
  processingTitle: document.getElementById("processingTitle"),
  processingFileName: document.getElementById("processingFileName"),
  processingSteps: document.querySelectorAll("#processingSteps li"),
  resultTitle: document.getElementById("resultTitle"),
  resultMeta: document.getElementById("resultMeta"),
  slideCount: document.getElementById("slideCount"),
  questionCountBadge: document.getElementById("questionCountBadge"),
  slidesPanel: document.getElementById("slidesPanel"),
  chapterPanel: document.getElementById("chapterPanel"),
  quizPanel: document.getElementById("quizPanel"),
  resultTabs: document.getElementById("resultTabs"),
  copyButton: document.getElementById("copyButton"),
  exportButton: document.getElementById("exportButton"),
  exportSwatches: document.getElementById("exportSwatches"),
  backButton: document.getElementById("backButton"),
  newAnalysisButton: document.getElementById("newAnalysisButton"),
  historyNewButton: document.getElementById("historyNewButton"),
  navItems: document.querySelectorAll(".nav-item"),
  historyList: document.getElementById("historyList"),
  historyGrid: document.getElementById("historyGrid"),
  historyCount: document.getElementById("historyCount"),
  clearHistoryButton: document.getElementById("clearHistoryButton"),
  themeButton: document.getElementById("themeButton"),
  menuButton: document.getElementById("menuButton"),
  sidebar: document.getElementById("sidebar"),
  sidebarBackdrop: document.getElementById("sidebarBackdrop"),
  sidebarToggle: document.getElementById("sidebarToggle"),
  toast: document.getElementById("toast"),
};

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}

function escapeHTML(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function richText(value = "") {
  return escapeHTML(value).replaceAll("\n", "<br />");
}

function showView(view) {
  elements.views.forEach((item) => item.classList.remove("is-active"));
  view.classList.add("is-active");
  window.scrollTo({ top: 0, behavior: "smooth" });
  closeSidebar();
}

function setNavigation(activeView) {
  elements.navItems.forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === activeView);
  });
}

function showToast(message, type = "success") {
  clearTimeout(state.toastTimer);
  elements.toast.querySelector("span").textContent = message;
  elements.toast.classList.toggle("is-error", type === "error");
  const icon = elements.toast.querySelector("svg");
  if (icon) icon.setAttribute("data-lucide", type === "error" ? "circle-alert" : "circle-check");
  refreshIcons();
  elements.toast.classList.add("is-visible");
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("is-visible"), 3800);
}

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function fileExtension(filename) {
  return filename.split(".").pop()?.toLowerCase() || "";
}

function chooseFile(file) {
  if (!file) return;
  const extension = fileExtension(file.name);
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    showToast("نوع الملف غير مدعوم", "error");
    return;
  }
  if (file.size > MAX_FILE_SIZE) {
    showToast("حجم الملف أكبر من 15 MB", "error");
    return;
  }

  state.file = file;
  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = `${extension.toUpperCase()} · ${formatBytes(file.size)}`;
  elements.dropzone.hidden = true;
  elements.selectedFile.hidden = false;
  updateAnalyzeButton();

  if (file.type.startsWith("image/")) {
    const imageUrl = URL.createObjectURL(file);
    elements.filePreview.innerHTML = `<img src="${imageUrl}" alt="معاينة الملف" />`;
  } else {
    elements.filePreview.innerHTML = '<i data-lucide="file-stack"></i>';
  }
  refreshIcons();
}

function clearFile() {
  state.file = null;
  elements.fileInput.value = "";
  elements.dropzone.hidden = false;
  elements.selectedFile.hidden = true;
  elements.filePreview.innerHTML = '<i data-lucide="file-text"></i>';
  elements.analyzeButton.disabled = true;
  refreshIcons();
}

function selectedProvider() {
  return state.providers.find((provider) => provider.id === elements.providerSelect.value);
}

function providerReady() {
  const provider = selectedProvider();
  return Boolean(provider && (provider.configured || provider.accepts_user_key));
}

function keyRequired() {
  const provider = selectedProvider();
  return Boolean(provider && (provider.requires_user_key || !provider.configured));
}

function keyReady() {
  return !keyRequired() || Boolean(elements.apiKeyInput.value.trim());
}

function updateConnectionState() {
  const serverOk = elements.connectionState.classList.contains("is-ready") || state._serverOk;
  const key = elements.apiKeyInput.value.trim();
  const provider = selectedProvider();
  const connected = serverOk && key.length > 10;
  const name = provider ? provider.label || provider.id : "";
  if (connected) {
    elements.connectionState.className = "connection is-ready";
    elements.connectionState.lastElementChild.textContent = "متصل \u00B7 " + name;
  } else if (serverOk) {
    elements.connectionState.className = "connection";
    elements.connectionState.lastElementChild.textContent = "غير متصل - أضف مفتاح";
  }
}

function updateAnalyzeButton() {
  elements.analyzeButton.disabled = !state.file || !providerReady() || !keyReady();
}

function loadSavedApiKey() {
  const provider = selectedProvider();
  if (!provider) return;
  const saved = localStorage.getItem(API_KEY_STORAGE_PREFIX + provider.id);
  if (saved) {
    elements.apiKeyInput.value = saved;
    const checkbox = document.getElementById("saveApiKey");
    if (checkbox) checkbox.checked = true;
  }
  updateConnectionState();
}

function saveApiKey() {
  const provider = selectedProvider();
  if (!provider) return;
  const checkbox = document.getElementById("saveApiKey");
  if (!checkbox) return;
  if (checkbox.checked && elements.apiKeyInput.value.trim()) {
    localStorage.setItem(API_KEY_STORAGE_PREFIX + provider.id, elements.apiKeyInput.value.trim());
  } else {
    localStorage.removeItem(API_KEY_STORAGE_PREFIX + provider.id);
  }
}

function updateProviderHint() {
  const provider = selectedProvider();
  if (!provider) return;
  if (provider.id === "gemini") {
    elements.providerHint.innerHTML = '<i data-lucide="badge-check"></i> Gemini 3.1 Flash-Lite · ضمن حصة Google المجانية';
  } else if (provider.id === "deepseek") {
    elements.providerHint.innerHTML = '<i data-lucide="coins"></i> DeepSeek Chat · مدفوع حسب الاستخدام (رخيص جداً)';
  } else if (provider.supports_vision) {
    elements.providerHint.innerHTML = '<i data-lucide="panels-top-left"></i> يقرأ كل سلايد بصرياً ونصياً';
  } else {
    elements.providerHint.innerHTML = '<i data-lucide="text"></i> مناسب للسلايدات ذات النص القابل للنسخ';
  }

  const keyLabels = {
    gemini: { placeholder: "ألصق مفتاح Gemini", link: "احصل على مفتاح Gemini" },
    claude: { placeholder: "ألصق مفتاح Claude", link: "احصل على مفتاح Claude" },
    deepseek: { placeholder: "ألصق مفتاح DeepSeek", link: "احصل على مفتاح DeepSeek" },
  };
  const keyLabel = keyLabels[provider.id] || { placeholder: "ألصق مفتاح API", link: "احصل على مفتاح API" };
  elements.apiKeyInput.placeholder = keyLabel.placeholder;
  elements.apiKeyInput.required = keyRequired();
  elements.providerKeyLink.hidden = !provider.key_url;
  if (provider.key_url) {
    elements.providerKeyLink.href = provider.key_url;
    elements.providerKeyLink.querySelector("span").textContent = keyLabel.link;
  }

  loadSavedApiKey();
  updateAnalyzeButton();
  updateConnectionState();
  refreshIcons();
}

async function loadProviders() {
  try {
    const [healthResponse, providersResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/providers"),
    ]);
    if (!healthResponse.ok || !providersResponse.ok) throw new Error("offline");

    const health = await healthResponse.json();
    state.providers = await providersResponse.json();
    elements.connectionState.className = "connection is-ready";
    const visibleProviderIds = new Set([...elements.providerSelect.options].map((option) => option.value));
    const availableProviders = state.providers.filter(
      (provider) => visibleProviderIds.has(provider.id) && provider.free_tier && (provider.configured || provider.accepts_user_key),
    ).length;
    elements.connectionState.lastElementChild.textContent = `${availableProviders} محرك مجاني`;
    elements.versionLabel.textContent = `Dr. Solution. v${health.version}`;

    [...elements.providerSelect.options].forEach((option) => {
      const provider = state.providers.find((item) => item.id === option.value);
      if (!provider) return;
      const available = provider.configured || provider.accepts_user_key;
      option.textContent = provider.label;
      option.disabled = !available;
    });

    const firstReady = state.providers.find((provider) => provider.configured || provider.accepts_user_key);
    if (firstReady) elements.providerSelect.value = firstReady.id;
    state._serverOk = true;
    updateProviderHint();
    updateConnectionState();
  } catch {
    elements.connectionState.className = "connection is-error";
    elements.connectionState.lastElementChild.textContent = "الخادم غير متصل";
    elements.providerHint.innerHTML = '<i data-lucide="wifi-off"></i> تعذر الاتصال بالخادم';
    elements.analyzeButton.disabled = true;
    state._serverOk = false;
    refreshIcons();
  }
}

function updateQuestionControls() {
  const enabled = elements.questionsEnabled.checked;
  elements.questionOptions.classList.toggle("is-disabled", !enabled);
  elements.questionsEnabled.closest(".switch").querySelector("b").textContent = enabled ? "مفعّل" : "متوقف";
}

function changeQuestionCount(delta) {
  const current = Number.parseInt(elements.questionCount.value, 10) || 8;
  elements.questionCount.value = Math.max(1, Math.min(20, current + delta));
}

function selectedQuestionTypes() {
  return [...document.querySelectorAll('input[name="questionType"]:checked')].map((input) => input.value);
}

function startProgress() {
  const stages = [
    { progress: 14, step: 0, title: "نحوّل الصفحات إلى سلايدات" },
    { progress: 34, step: 1, title: "نقرأ النص والصور معاً" },
    { progress: 56, step: 1, title: "نكتب شرح كل سلايد" },
    { progress: 74, step: 2, title: "نربط أفكار المادة" },
    { progress: 89, step: 3, title: "نجهّز المراجعة والاختبار" },
    { progress: 95, step: 3, title: "اللمسات الأخيرة" },
  ];
  let index = 0;
  elements.progressBar.style.width = "3%";
  if (elements.progressPercent) elements.progressPercent.textContent = "0%";
  updateProgressStage(stages[0]);
  state.progressTimer = setInterval(() => {
    index = Math.min(index + 1, stages.length - 1);
    updateProgressStage(stages[index]);
  }, 2800);
}

function setRealProgress(pct, done, total) {
  clearInterval(state.progressTimer);
  state.progressTimer = null;
  const width = Math.max(3, Math.min(100, pct));
  elements.progressBar.style.width = `${width}%`;
  if (elements.progressPercent) elements.progressPercent.textContent = `${pct}%`;
  const finished = done >= total;
  elements.processingTitle.textContent = finished
    ? "جارٍ التجميع النهائي للنتائج…"
    : `تم تحليل ${done} من ${total} صفحة`;
}

function updateProgressStage(stage) {
  elements.progressBar.style.width = `${stage.progress}%`;
  if (elements.progressPercent) elements.progressPercent.textContent = `${stage.progress}%`;
  elements.processingTitle.textContent = stage.title;
  elements.processingSteps.forEach((item, index) => {
    item.classList.toggle("is-active", index === stage.step);
    item.classList.toggle("is-done", index < stage.step);
    const icon = item.querySelector("svg");
    if (icon) icon.setAttribute("data-lucide", index < stage.step ? "circle-check" : index === stage.step ? "loader-circle" : "circle");
  });
  refreshIcons();
}

function stopProgress(success = false) {
  clearInterval(state.progressTimer);
  state.progressTimer = null;
  if (success) {
    elements.progressBar.style.width = "100%";
    if (elements.progressPercent) elements.progressPercent.textContent = "100%";
    elements.processingSteps.forEach((item) => {
      item.classList.remove("is-active");
      item.classList.add("is-done");
    });
  }
}

async function submitAnalysis(event) {
  event.preventDefault();
  if (!state.file || !providerReady()) return;
  if (!keyReady()) {
    showToast("أضف مفتاح المحرك للمتابعة", "error");
    elements.apiKeyInput.focus();
    return;
  }

  const questionTypes = selectedQuestionTypes();
  if (elements.questionsEnabled.checked && !questionTypes.length) {
    showToast("اختر نوع سؤال واحداً على الأقل", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", state.file);
  formData.append("provider", elements.providerSelect.value);
  saveApiKey();
  formData.append("api_key", elements.apiKeyInput.value.trim());
  formData.append("target_language", elements.languageSelect.value);
  formData.append("content_kind", elements.contentKindSelect.value);
  formData.append("depth", document.querySelector('input[name="depth"]:checked').value);
  formData.append("questions_enabled", elements.questionsEnabled.checked);
  formData.append("question_types", questionTypes.join(","));
  formData.append("question_count", elements.questionCount.value);
  formData.append("question_difficulty", document.querySelector('input[name="questionDifficulty"]:checked').value);

  elements.processingFileName.textContent = state.file.name;
  showView(elements.processingView);
  startProgress();

  try {
    const response = await fetch("/api/analyze/stream", { method: "POST", body: formData });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "تعذر تحليل الملف الأكاديمي الآن.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let payload = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const evt = JSON.parse(line);
        if (evt.type === "start") {
          state.totalPages = evt.total;
        } else if (evt.type === "progress") {
          const pct = evt.total ? Math.round((evt.done / evt.total) * 100) : 0;
          setRealProgress(pct, evt.done, evt.total);
        } else if (evt.type === "done") {
          payload = evt.payload;
        } else if (evt.type === "error") {
          throw new Error(evt.message || "حدث خطأ أثناء التحليل.");
        }
      }
    }

    if (!payload) throw new Error("لم يتم استلام نتيجة التحليل.");
    stopProgress(true);
    state.result = payload;
    await saveResult(payload);
    renderResult(payload);
    setTimeout(() => showView(elements.resultsView), 220);
  } catch (error) {
    stopProgress(false);
    elements.apiKeyInput.value = "";
    showView(elements.workspaceView);
    showToast(error.message || "حدث خطأ غير متوقع", "error");
  } finally {
    updateAnalyzeButton();
  }
}

function renderResult(payload) {
  const chapter = payload.result;
  elements.resultTitle.textContent = chapter.chapter_title || payload.filename;
  const correctionLabel = document.querySelector('input[name="correctionMode"]:checked')?.value === "immediate" ? "تصحيح فوري" : "تصحيح بنهاية";
  elements.resultMeta.innerHTML = [
    metaItem("file-text", payload.filename),
    metaItem("cpu", providerLabel(payload.provider)),
    metaItem("library", contentKindLabel(payload.content_kind)),
    metaItem("panels-top-left", `${payload.stats.analyzed_pages} سلايد`),
    metaItem("badge-help", `${chapter.questions.length} سؤال`),
    metaItem("zap", correctionLabel),
  ].join("");
  elements.slideCount.textContent = chapter.slides.length;
  elements.questionCountBadge.textContent = chapter.questions.length;
  elements.slidesPanel.innerHTML = renderSlides(chapter.slides);
  elements.chapterPanel.innerHTML = renderChapter(chapter);
  elements.quizPanel.innerHTML = renderQuiz(chapter.questions);
  activateTab("slides");
  bindResultInteractions();
  renderHistory();
  refreshIcons();
}

function metaItem(icon, text) {
  return `<span><i data-lucide="${icon}"></i>${escapeHTML(text)}</span>`;
}

function renderSlides(slides = []) {
  if (!slides.length) {
    return '<div class="empty-result"><i data-lucide="panels-top-left"></i><p>لا توجد سلايدات محللة.</p></div>';
  }
  const jumpbar = `<nav class="slide-jumpbar" aria-label="انتقال بين السلايدات">${slides
    .map((slide) => `<button type="button" data-jump-slide="${slide.page_number}" title="السلايد ${slide.page_number}">${slide.page_number}</button>`)
    .join("")}</nav>`;
  const cards = slides.map((slide) => `
    <article class="slide-card" id="slide-${slide.page_number}">
      <header class="slide-card__header">
        <span class="slide-number">سلايد ${String(slide.page_number).padStart(2, "0")}</span>
        <h2>${escapeHTML(slide.title)}</h2>
        <button class="slide-ask-btn" type="button" data-ask-slide="${slide.page_number}">
          <i data-lucide="message-square-question"></i>
          <span>اسأل عن هذه الصفحة</span>
        </button>
      </header>
      ${slide.original_text ? `<div class="slide-original-data" hidden>${escapeHTML(slide.original_text)}</div>` : ""}
      <div class="slide-card__body">
        <div class="slide-visual-col">
          <figure class="slide-preview">
            <img src="${escapeHTML(slide.preview_data_url)}" alt="معاينة السلايد ${slide.page_number}" loading="lazy" />
          </figure>
        </div>
        <section class="slide-translation-col"><div class="slide-line-content">${(slide.translation || "لا توجد ترجمة إضافية.").split(/\r?\n/).filter(l => l.trim() !== "").map(l => `<div class="slide-line">${escapeHTML(l)}</div>`).join("")}</div></section>
      </div>
      <div class="slide-card__content">
        <section class="slide-explanation">
          <span class="section-kicker"><i data-lucide="book-open-text"></i> شرح السلايد</span>
          <p>${richText(slide.explanation || "لا يوجد شرح متاح.")}</p>
          ${renderSimpleList(slide.key_points, "slide-key-points")}
        </section>
        <section class="slide-insight">
          <span class="section-kicker"><i data-lucide="scan-search"></i> شرح الصورة</span>
          <p>${richText(slide.image_description || "لا توجد تفاصيل إضافية.")}</p>
        </section>
        <section class="slide-insight">
          <span class="section-kicker"><i data-lucide="brain-circuit"></i> تحليل المحتوى</span>
          <p>${richText(slide.content_analysis || "لا توجد تفاصيل إضافية.")}</p>
        </section>
        <section class="slide-insight is-summary">
          <span class="section-kicker"><i data-lucide="bookmark-check"></i> خلاصة السلايد</span>
          <p>${richText(slide.slide_summary || "لا توجد خلاصة.")}</p>
        </section>
      </div>
    </article>`).join("");
  return `${jumpbar}<div class="slides-list">${cards}</div>`;
}

function renderChapter(chapter) {
  return `
    <div class="chapter-layout">
      <div class="chapter-main">
        ${contentSection("telescope", "صورة عامة", `<p>${richText(chapter.chapter_overview || "لا توجد مقدمة متاحة.")}</p>`)}
        ${contentSection("notebook-tabs", "الخلاصة النهائية", `<p>${richText(chapter.chapter_summary || "لا توجد خلاصة متاحة.")}</p>`, "is-coral")}
      </div>
      <aside class="chapter-side">
        ${contentSection("target", "أهداف التعلم", renderSimpleList(chapter.learning_objectives, "key-points"), "is-blue")}
        ${contentSection("book-marked", "مصطلحات المادة", renderGlossary(chapter.glossary))}
        ${contentSection("languages", "لغة المصدر", `<p>${escapeHTML(chapter.source_language)}</p>`, "is-blue")}
      </aside>
    </div>`;
}

function contentSection(icon, title, body, colorClass = "") {
  return `<section class="content-section"><div class="content-section__head"><span class="${colorClass}"><i data-lucide="${icon}"></i></span><h2>${escapeHTML(title)}</h2></div>${body}</section>`;
}

function renderSimpleList(items = [], className) {
  if (!items.length) return '<p class="muted">لا توجد عناصر إضافية.</p>';
  return `<ul class="${className}">${items.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>`;
}

function renderGlossary(items = []) {
  if (!items.length) return '<p class="muted">لا توجد مصطلحات إضافية.</p>';
  return `<ul class="glossary-list">${items.map((item) => `<li><strong>${escapeHTML(item.term)}</strong><span>${escapeHTML(item.meaning)}</span></li>`).join("")}</ul>`;
}

function renderQuiz(questions = []) {
  if (!questions.length) {
    return '<div class="empty-result"><i data-lucide="clipboard-x"></i><p>لم يتم طلب أسئلة لهذه المادة.</p></div>';
  }
  const immediate = document.querySelector('input[name="correctionMode"]:checked')?.value === "immediate";
  const toolbarHtml = immediate ? "" : `
    <div class="quiz-toolbar">
      <div class="quiz-progress"><strong id="quizScore">اختبار من ${questions.length} أسئلة</strong><span>اضغط للتصحيح بعد الإجابة</span></div>
      <button class="secondary-button" id="checkQuizButton" type="button"><i data-lucide="check-check"></i><span>صحّح الاختبار</span></button>
    </div>`;
  return `
    ${toolbarHtml}
    <div class="quiz-list">${questions.map((question, index) => renderQuestion(question, index)).join("")}</div>`;
}

function renderQuestion(question, index) {
  const immediate = document.querySelector('input[name="correctionMode"]:checked')?.value === "immediate";
  const options = question.options?.length
    ? `<div class="quiz-options">${question.options.map((option) => `<button class="quiz-option ${immediate ? "is-immediate" : ""}" type="button" data-question="${index}" data-option="${escapeHTML(option)}">${escapeHTML(option)}</button>`).join("")}</div>`
    : `<textarea class="answer-input" data-written-answer="${index}" placeholder="اكتب إجابتك هنا..."></textarea>`;
  return `
    <article class="quiz-question" data-quiz-question="${index}" data-correct-answer="${escapeHTML(question.correct_answer)}" data-type="${question.type}">
      <header class="quiz-question__head"><b>سؤال ${index + 1}</b><span>${questionTypeLabel(question.type)}</span><span>${escapeHTML(question.difficulty)}</span></header>
      <div class="quiz-question__body">
        <h3>${escapeHTML(question.question)}</h3>
        ${options}
        <div class="quiz-question__actions"><button class="text-button reveal-answer" type="button" data-reveal-answer="${index}">كشف الإجابة</button></div>
        <div class="answer-reveal" id="answer-${index}"><strong>الإجابة النموذجية:</strong> ${richText(question.correct_answer)}${question.explanation ? `<br /><span>${richText(question.explanation)}</span>` : ""}</div>
      </div>
    </article>`;
}

function questionTypeLabel(type) {
  return {
    multiple_choice: "اختيار متعدد",
    true_false: "صح أو خطأ",
    short_answer: "إجابة قصيرة",
    essay: "مقالي",
  }[type] || "سؤال";
}

function bindResultInteractions() {
  document.querySelectorAll("[data-jump-slide]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(`slide-${button.dataset.jumpSlide}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  });
  elements.quizPanel.querySelectorAll(".quiz-option.is-immediate").forEach((option) => {
    option.addEventListener("click", () => {
      const question = option.closest(".quiz-question");
      const expected = question.dataset.correctAnswer.trim();
      question.querySelectorAll(".quiz-option").forEach((item) => {
        item.classList.remove("is-selected", "is-correct", "is-wrong");
        if (item.dataset.option.trim() === expected) item.classList.add("is-correct");
      });
      if (option.dataset.option.trim() === expected) {
        option.classList.add("is-selected", "is-correct");
      } else {
        option.classList.add("is-wrong");
        const correctOption = [...question.querySelectorAll(".quiz-option")].find((item) => item.dataset.option.trim() === expected);
        if (correctOption) correctOption.classList.add("is-correct");
      }
    });
  });
  elements.quizPanel.querySelectorAll(".quiz-option:not(.is-immediate)").forEach((option) => {
    option.addEventListener("click", () => {
      const question = option.closest(".quiz-question");
      question.querySelectorAll(".quiz-option").forEach((item) => item.classList.remove("is-selected", "is-correct", "is-wrong"));
      option.classList.add("is-selected");
    });
  });
  elements.quizPanel.querySelectorAll("[data-reveal-answer]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(`answer-${button.dataset.revealAnswer}`)?.classList.toggle("is-visible"));
  });
  document.getElementById("checkQuizButton")?.addEventListener("click", checkQuiz);
      document.querySelectorAll("[data-ask-slide]").forEach((button) => {
      button.addEventListener("click", () => {
        const slideNum = button.dataset.askSlide;
        const card = document.getElementById(`slide-${slideNum}`);
        if (card) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          card.classList.add("is-highlighted");
          setTimeout(() => card.classList.remove("is-highlighted"), 2000);
        }
        if (window.DrSolutionChat) window.DrSolutionChat.setActiveSlide(slideNum);
        const chatPanel = document.getElementById("dr-panel");
        const chatBubble = document.getElementById("dr-bubble");
        if (chatPanel && chatBubble) {
          if (!chatPanel.classList.contains("is-open")) {
            chatBubble.click();
          }
          const input = document.getElementById("dr-inp");
          if (input) {
            input.value = `اشرح لي السلايد ${slideNum} بالتفصيل`;
            input.dispatchEvent(new Event("input"));
            setTimeout(() => {
              document.getElementById("dr-send")?.click();
            }, 300);
          }
        }
      });
    });
}

function checkQuiz() {
  const autoQuestions = [...elements.quizPanel.querySelectorAll('.quiz-question[data-type="multiple_choice"], .quiz-question[data-type="true_false"]')];
  let correct = 0;
  autoQuestions.forEach((question) => {
    const selected = question.querySelector(".quiz-option.is-selected");
    const expected = question.dataset.correctAnswer.trim();
    question.querySelectorAll(".quiz-option").forEach((option) => {
      if (option.dataset.option.trim() === expected) option.classList.add("is-correct");
    });
    if (selected) {
      if (selected.dataset.option.trim() === expected) correct += 1;
      else selected.classList.add("is-wrong");
    }
  });
  const score = document.getElementById("quizScore");
  if (score) score.textContent = autoQuestions.length ? `نتيجتك ${correct} من ${autoQuestions.length} في الأسئلة الموضوعية` : "راجع إجاباتك مع النماذج";
  showToast("تم تصحيح الأسئلة الموضوعية");
}

function activateTab(tabName) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === tabName));
  document.querySelectorAll(".result-panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === tabName));
}

function providerLabel(provider) {
  return { gemini: "Gemini", claude: "Claude", deepseek: "DeepSeek" }[provider] || provider;
}

function contentKindLabel(kind) {
  return {
    auto: "تلقائي",
    lecture: "محاضرة",
    research: "بحث علمي",
    book: "كتاب",
    university_document: "مستند جامعي",
  }[kind] || "مادة أكاديمية";
}

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("results")) {
        request.result.createObjectStore("results", { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withResultStore(mode, operation) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction("results", mode);
    const store = transaction.objectStore("results");
    const request = operation(store);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => database.close();
  });
}

async function saveResult(payload) {
  try {
    await withResultStore("readwrite", (store) => store.put(payload));
    const all = await getHistory();
    const stale = all.slice(8);
    await Promise.all(stale.map((item) => withResultStore("readwrite", (store) => store.delete(item.id))));
  } catch {
    showToast("اكتمل التحليل، لكن تعذر حفظه في سجل المتصفح", "error");
  }
}

async function getHistory() {
  try {
    const all = await withResultStore("readonly", (store) => store.getAll());
    return all.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  } catch {
    return [];
  }
}

async function clearHistory() {
  try {
    await withResultStore("readwrite", (store) => store.clear());
  } catch {
    // The UI remains usable even if private browsing blocks IndexedDB.
  }
}

async function renderHistory() {
  const history = await getHistory();
  elements.historyCount.textContent = history.length;
  elements.historyList.innerHTML = history.length
    ? history.slice(0, 5).map((item) => `<button class="history-item" type="button" data-result-id="${item.id}"><strong>${escapeHTML(item.result.chapter_title || item.filename)}</strong><span>${item.stats.analyzed_pages} سلايد · ${formatDate(item.created_at)}</span></button>`).join("")
    : '<div class="history-empty">لا توجد مواد محفوظة بعد.</div>';
  elements.historyGrid.innerHTML = history.length
    ? history.map((item) => `<button class="history-card" type="button" data-result-id="${item.id}"><span class="history-card__icon"><i data-lucide="panels-top-left"></i></span><h3>${escapeHTML(item.result.chapter_title || item.filename)}</h3><p>${escapeHTML(item.filename)}</p><span class="history-card__meta"><span>${item.stats.analyzed_pages} سلايد</span><span>·</span><span>${item.result.questions.length} سؤال</span><span>${formatDate(item.created_at)}</span></span></button>`).join("")
    : '<div class="empty-result"><i data-lucide="history"></i><p>ستظهر أول مادة هنا.</p></div>';
  document.querySelectorAll("[data-result-id]").forEach((button) => button.addEventListener("click", () => openHistoryItem(button.dataset.resultId)));
  refreshIcons();
}

async function openHistoryItem(id) {
  const history = await getHistory();
  const result = history.find((item) => item.id === id);
  if (!result) return;
  state.result = result;
  renderResult(result);
  showView(elements.resultsView);
  setNavigation("workspace");
}

function formatDate(value) {
  try {
    return new Intl.DateTimeFormat("ar", { month: "short", day: "numeric" }).format(new Date(value));
  } catch {
    return "الآن";
  }
}

function newAnalysis() {
  clearFile();
  state.result = null;
  showView(elements.workspaceView);
  setNavigation("workspace");
}

function resultAsMarkdown(payload) {
  const chapter = payload.result;
  const slides = chapter.slides.map((slide) => `## سلايد ${slide.page_number}: ${slide.title}\n\n### الشرح\n${slide.explanation}\n\n### الترجمة\n${slide.translation}\n\n### شرح الصورة\n${slide.image_description}\n\n### تحليل المحتوى\n${slide.content_analysis}\n\n**الخلاصة:** ${slide.slide_summary}`).join("\n\n---\n\n");
  const questions = chapter.questions.map((question, index) => `${index + 1}. ${question.question}\n   الإجابة: ${question.correct_answer}`).join("\n");
  return `# ${chapter.chapter_title}\n\n${chapter.chapter_overview}\n\n${slides}\n\n# خلاصة المادة\n\n${chapter.chapter_summary}\n\n# الأسئلة\n\n${questions}\n`;
}

async function copyResult() {
  if (!state.result) return;
  try {
    await navigator.clipboard.writeText(resultAsMarkdown(state.result));
    showToast("تم نسخ الشرح كاملاً");
  } catch {
    showToast("تعذر النسخ من المتصفح", "error");
  }
}

function exportResult() {
  if (!state.result || !window.DrSolutionExporter) return;
  window.DrSolutionExporter.download(state.result, state.exportTheme);
  showToast("تم تجهيز صفحة HTML التفاعلية");
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  elements.themeButton.innerHTML = `<i data-lucide="${theme === "dark" ? "sun" : "moon"}"></i>`;
  refreshIcons();
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme || "light";
  const next = current === "light" ? "dark" : "light";
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

function openSidebar() {
  elements.sidebar.classList.add("is-open");
  elements.sidebarBackdrop.classList.add("is-visible");
}

function closeSidebar() {
  elements.sidebar.classList.remove("is-open");
  elements.sidebarBackdrop.classList.remove("is-visible");
}

function toggleSidebar() {
  document.body.classList.toggle("sidebar-hidden");
  const hidden = document.body.classList.contains("sidebar-hidden");
  const icon = hidden ? "panel-left-open" : "panel-left-close";
  document.querySelectorAll("#sidebarToggle, #sidebarCloseBtn").forEach((el) => {
    el.innerHTML = `<i data-lucide="${icon}"></i>`;
    el.setAttribute("aria-label", hidden ? "إظهار الشريط" : "إخفاء الشريط");
    el.title = hidden ? "إظهار الشريط الجانبي" : "إخفاء الشريط الجانبي";
  });
  refreshIcons();
  setTimeout(refreshIcons, 350);
}

elements.dropzone.addEventListener("click", () => elements.fileInput.click());
elements.dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.fileInput.click();
  }
});
elements.fileInput.addEventListener("change", (event) => chooseFile(event.target.files[0]));
elements.removeFileButton.addEventListener("click", clearFile);
elements.analysisForm.addEventListener("submit", submitAnalysis);
elements.providerSelect.addEventListener("change", updateProviderHint);
function detectKeyProvider(key) {
  if (/^AIzaSy[A-Za-z0-9_-]{33}$/.test(key.trim())) return "gemini";
  if (/^sk-[A-Za-z0-9]{20,}$/.test(key.trim())) return "deepseek";
  if (/^sk-ant-[A-Za-z0-9]{20,}$/.test(key.trim())) return "claude";
  return null;
}

function updateKeyConnectionFeedback(valid) {
  const input = elements.apiKeyInput;
  input.style.borderColor = valid ? "var(--primary)" : "";
  input.style.boxShadow = valid ? "0 0 0 3px color-mix(in srgb, var(--primary) 13%, transparent)" : "";
}

elements.apiKeyInput.addEventListener("input", () => {
  updateAnalyzeButton();
  saveApiKey();
  const key = elements.apiKeyInput.value.trim();
  updateKeyConnectionFeedback(key.length > 10);
  updateConnectionState();
  window.dispatchEvent(new CustomEvent("keychange"));
});

elements.apiKeyInput.addEventListener("paste", () => {
  setTimeout(() => {
    const key = elements.apiKeyInput.value.trim();
    if (key.length < 10) return;
    const detected = detectKeyProvider(key);
    if (detected && detected !== elements.providerSelect.value) {
      const option = [...elements.providerSelect.options].find((o) => o.value === detected && !o.disabled);
      if (option) {
        elements.providerSelect.value = detected;
        updateProviderHint();
        showToast(`تم التبديل إلى ${option.textContent} تلقائياً`);
      }
    }
    updateKeyConnectionFeedback(key.length > 10);
    updateConnectionState();
  }, 50);
});
document.getElementById("saveApiKey")?.addEventListener("change", saveApiKey);
elements.toggleApiKeyButton.addEventListener("click", () => {
  const revealing = elements.apiKeyInput.type === "password";
  elements.apiKeyInput.type = revealing ? "text" : "password";
  elements.toggleApiKeyButton.innerHTML = `<i data-lucide="${revealing ? "eye-off" : "eye"}"></i>`;
  elements.toggleApiKeyButton.setAttribute("aria-label", revealing ? "إخفاء المفتاح" : "إظهار المفتاح");
  elements.toggleApiKeyButton.title = revealing ? "إخفاء المفتاح" : "إظهار المفتاح";
  refreshIcons();
});
elements.questionsEnabled.addEventListener("change", updateQuestionControls);
elements.questionMinus.addEventListener("click", () => changeQuestionCount(-1));
elements.questionPlus.addEventListener("click", () => changeQuestionCount(1));
elements.newAnalysisButton.addEventListener("click", newAnalysis);
elements.historyNewButton.addEventListener("click", newAnalysis);
elements.backButton.addEventListener("click", newAnalysis);
elements.copyButton.addEventListener("click", copyResult);
elements.exportButton.addEventListener("click", exportResult);
elements.themeButton.addEventListener("click", toggleTheme);
elements.menuButton.addEventListener("click", openSidebar);
elements.sidebarToggle.addEventListener("click", toggleSidebar);
document.getElementById("sidebarCloseBtn")?.addEventListener("click", toggleSidebar);
elements.sidebarBackdrop.addEventListener("click", closeSidebar);

document.querySelectorAll('input[name="questionType"]').forEach((input) => {
  input.addEventListener("change", () => {
    if (elements.questionsEnabled.checked && !selectedQuestionTypes().length) {
      input.checked = true;
      showToast("اختر نوع سؤال واحداً على الأقل", "error");
    }
  });
});

["dragenter", "dragover"].forEach((eventName) => {
  elements.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropzone.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  elements.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropzone.classList.remove("is-dragging");
  });
});
elements.dropzone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));

elements.resultTabs.addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) activateTab(tab.dataset.tab);
});

elements.exportSwatches.addEventListener("click", (event) => {
  const swatch = event.target.closest("[data-export-theme]");
  if (!swatch) return;
  state.exportTheme = swatch.dataset.exportTheme;
  elements.exportSwatches.querySelectorAll(".swatch").forEach((item) => item.classList.toggle("is-active", item === swatch));
});

elements.navItems.forEach((item) => {
  item.addEventListener("click", () => {
    setNavigation(item.dataset.view);
    showView(item.dataset.view === "history" ? elements.historyView : elements.workspaceView);
    if (item.dataset.view === "history") renderHistory();
  });
});

elements.clearHistoryButton.addEventListener("click", async () => {
  await clearHistory();
  await renderHistory();
  showToast("تم مسح السجل");
});

/* ── Video Analysis Mode ── */
const videoState = { result: null };

const videoEls = {
  section: document.getElementById("videoSection"),
  resultsSection: document.getElementById("videoResultsSection"),
  form: document.getElementById("videoForm"),
  extractBtn: document.getElementById("extractVideoButton"),
  status: document.getElementById("videoStatus"),
  apiKey: document.getElementById("videoApiKey"),
  backBtn: document.getElementById("videoBackButton"),
  copyBtn: document.getElementById("videoCopyButton"),
  exportBtn: document.getElementById("videoExportButton"),
  title: document.getElementById("videoResultTitle"),
  meta: document.getElementById("videoResultMeta"),
  container: document.getElementById("videoGoalsContainer"),
  modeTabs: document.querySelectorAll(".mode-tab"),
};

let currentMode = "file";

function switchMode(mode) {
  currentMode = mode;
  videoEls.modeTabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.mode === mode));
  elements.workspaceView.classList.toggle("is-active", mode === "file");
  if (videoEls.section) videoEls.section.classList.toggle("is-active", mode === "video");
  elements.resultsView.classList.remove("is-active");
  if (videoEls.resultsSection) videoEls.resultsSection.classList.remove("is-active");
}

videoEls.modeTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchMode(tab.dataset.mode));
});

function formatVideoTime(seconds = 0) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function transcriptSourceLabel(source) {
  if (source === "youtube_captions") return "ترجمة YouTube";
  if (source === "whisper") return "Whisper محلي";
  return "تحليل بصري فقط";
}

function segmentationModeLabel(mode) {
  return mode === "scene_detection" ? "تغيّر السلايدات" : "تقطيع زمني احتياطي";
}

function renderVideoSegment(segment) {
  const frame = String(segment.frame_data_url || "");
  const safeFrame = frame.startsWith("data:image/") ? frame : "";
  const points = segment.key_points || [];
  const terms = segment.technical_terms || [];
  return `<article class="video-segment-card">
    <header class="video-segment-card__header">
      <span>المقطع ${segment.index}</span>
      <h3>${escapeHTML(segment.title || `مقطع ${segment.index}`)}</h3>
      <time>${formatVideoTime(segment.start_sec)} - ${formatVideoTime(segment.end_sec)}</time>
    </header>
    <div class="video-segment-card__body">
      <div class="video-segment-frame">
        ${safeFrame ? `<img src="${safeFrame}" alt="إطار المقطع ${segment.index}">` : '<i data-lucide="image-off"></i>'}
      </div>
      <div class="video-segment-explanation">
        <p>${richText(segment.arabic_explanation || segment.segment_summary || "لا يتوفر شرح لهذا المقطع.")}</p>
        ${segment.translation ? `<div class="video-translation"><strong>الترجمة</strong><p>${richText(segment.translation)}</p></div>` : ""}
      </div>
    </div>
    ${points.length ? `<ul class="video-key-points">${points.map((point) => `<li>${escapeHTML(point)}</li>`).join("")}</ul>` : ""}
    ${terms.length ? `<div class="video-terms">${terms.map((term) => `<span><b>${escapeHTML(term.term)}</b>${escapeHTML(term.arabic_equivalent || term.explanation || "")}</span>`).join("")}</div>` : ""}
    ${segment.transcript_text ? `<details class="video-transcript"><summary>النص المنطوق في هذا المقطع</summary><p>${richText(segment.transcript_text)}</p></details>` : ""}
  </article>`;
}

function renderVideoResults(data) {
  const results = data.results || [];
  const validResults = results.filter((item) => !item.error);
  const totalSegments = validResults.reduce((sum, item) => sum + (item.segments || []).length, 0);
  const totalObjectives = validResults.reduce((sum, item) => sum + (item.learning_objectives || []).length, 0);
  videoEls.title.textContent = validResults.length === 1
    ? validResults[0].video_title
    : `تحليل ${validResults.length} فيديو`;
  videoEls.meta.innerHTML = [
    `<span><i data-lucide="video"></i>${results.length} فيديو</span>`,
    `<span><i data-lucide="panels-top-left"></i>${totalSegments} مقطع</span>`,
    `<span><i data-lucide="target"></i>${totalObjectives} هدف</span>`,
  ].join("");

  const statsHtml = `<div class="video-goal-stats">
    <div class="video-goal-stat"><strong>${results.length}</strong><span>فيديو</span></div>
    <div class="video-goal-stat"><strong>${totalSegments}</strong><span>مقطع مشروح</span></div>
    <div class="video-goal-stat"><strong>${totalObjectives}</strong><span>هدف تعلم</span></div>
  </div>`;

  const resultsHtml = results.map((item) => {
    if (item.error) {
      return `<div class="video-goal-error"><i data-lucide="circle-alert"></i><strong>${escapeHTML(item.video_title || "فيديو")}</strong><span>${escapeHTML(item.error)}</span></div>`;
    }
    const warnings = item.warnings || [];
    const objectives = item.learning_objectives || [];
    return `<section class="video-analysis-result">
      <header class="video-analysis-header">
        <div><span class="eyebrow">${transcriptSourceLabel(item.transcript_source)}</span><h2>${escapeHTML(item.video_title)}</h2></div>
        <div class="video-analysis-meta">
          <span><i data-lucide="clock-3"></i>${formatVideoTime(item.duration_sec)}</span>
          <span><i data-lucide="scan-line"></i>${segmentationModeLabel(item.segmentation_mode)}</span>
        </div>
      </header>
      ${warnings.length ? `<div class="video-warnings">${warnings.map((warning) => `<p><i data-lucide="info"></i>${escapeHTML(warning)}</p>`).join("")}</div>` : ""}
      <div class="video-overview">
        <div><strong>الخلاصة العامة</strong><p>${richText(item.overall_summary || "تُبنى الخلاصة من المقاطع التي نجح تحليلها.")}</p></div>
        <div><strong>أهداف التعلم</strong>${objectives.length ? `<ul>${objectives.map((objective) => `<li>${escapeHTML(objective)}</li>`).join("")}</ul>` : '<p class="muted">لا تتوفر أهداف بعد.</p>'}</div>
      </div>
      <div class="video-segments">${(item.segments || []).map(renderVideoSegment).join("")}</div>
    </section>`;
  }).join("");

  videoEls.container.innerHTML = statsHtml + resultsHtml;
  videoEls.resultsSection.classList.add("is-active");
  elements.workspaceView.classList.remove("is-active");
  if (videoEls.section) videoEls.section.classList.remove("is-active");
  elements.processingView.classList.remove("is-active");
  elements.resultsView.classList.remove("is-active");
  refreshIcons();
}

videoEls.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!videoEls.apiKey.value.trim()) {
    showToast("أضف مفتاح Gemini لتحليل الفيديو", "error");
    videoEls.apiKey.focus();
    return;
  }
  videoEls.extractBtn.disabled = true;
  videoEls.status.textContent = "جارٍ تنزيل الفيديو وتحليل السلايدات...";
  elements.processingView.classList.add("is-active");
  videoEls.section.classList.remove("is-active");
  startProgress();

  const formData = new FormData(videoEls.form);
  const body = {
    url: formData.get("url"),
    start: formData.get("start") ? parseInt(formData.get("start"), 10) : null,
    end: formData.get("end") ? parseInt(formData.get("end"), 10) : null,
    provider: formData.get("provider") || "gemini",
    api_key: videoEls.apiKey.value.trim(),
    model: "",
  };

  try {
    const resp = await fetch("/api/analyze-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const errorData = await resp.json().catch(() => ({}));
      throw new Error(errorData.detail || "فشل تحليل الفيديو");
    }
    const data = await resp.json();
    videoState.result = data;
    stopProgress(true);
    elements.processingView.classList.remove("is-active");
    renderVideoResults(data);
    const totalSegments = (data.results || []).reduce((sum, item) => sum + (item.segments || []).length, 0);
    videoEls.apiKey.value = "";
    videoEls.status.textContent = `تم شرح ${totalSegments} مقطع`;
    showToast(`تم شرح ${totalSegments} مقطع`);
  } catch (error) {
    stopProgress(false);
    elements.processingView.classList.remove("is-active");
    videoEls.section.classList.add("is-active");
    videoEls.status.textContent = "";
    showToast(error.message || "حدث خطأ", "error");
  } finally {
    videoEls.extractBtn.disabled = false;
  }
});

videoEls.backBtn.addEventListener("click", () => {
  if (videoEls.resultsSection) videoEls.resultsSection.classList.remove("is-active");
  if (videoEls.section) videoEls.section.classList.add("is-active");
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "smooth" });
  setNavigation("workspace");
});
videoEls.copyBtn.addEventListener("click", async () => {
  if (!videoState.result) return;
  const lines = [];
  for (const item of videoState.result.results || []) {
    lines.push(`## ${item.video_title}`);
    if (item.error) {
      lines.push(`خطأ: ${item.error}`, "");
      continue;
    }
    lines.push(item.overall_summary || "");
    for (const objective of item.learning_objectives || []) lines.push(`- ${objective}`);
    for (const segment of item.segments || []) {
      lines.push("", `### ${segment.title} (${formatVideoTime(segment.start_sec)} - ${formatVideoTime(segment.end_sec)})`);
      lines.push(segment.arabic_explanation || segment.segment_summary || "");
      if (segment.transcript_text) lines.push(`النص المنطوق: ${segment.transcript_text}`);
    }
    lines.push("");
  }
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    showToast("تم نسخ شرح الفيديو");
  } catch { showToast("تعذر النسخ", "error"); }
});

videoEls.exportBtn.addEventListener("click", () => {
  if (!videoState.result) return;
  const results = videoState.result.results || [];
  const exportedVideos = results.map((item) => {
    if (item.error) return `<section><h2>${escapeHTML(item.video_title || "فيديو")}</h2><p class="error">${escapeHTML(item.error)}</p></section>`;
    const segments = (item.segments || []).map((segment) => {
      const frame = String(segment.frame_data_url || "");
      const image = frame.startsWith("data:image/") ? `<img src="${frame}" alt="إطار المقطع ${segment.index}">` : "";
      const points = (segment.key_points || []).map((point) => `<li>${escapeHTML(point)}</li>`).join("");
      return `<article><header><b>المقطع ${segment.index}</b><h3>${escapeHTML(segment.title)}</h3><time>${formatVideoTime(segment.start_sec)} - ${formatVideoTime(segment.end_sec)}</time></header><div class="segment">${image}<div><p>${richText(segment.arabic_explanation || segment.segment_summary || "")}</p>${points ? `<ul>${points}</ul>` : ""}</div></div>${segment.transcript_text ? `<details><summary>النص المنطوق</summary><p>${richText(segment.transcript_text)}</p></details>` : ""}</article>`;
    }).join("");
    const objectives = (item.learning_objectives || []).map((objective) => `<li>${escapeHTML(objective)}</li>`).join("");
    return `<section><h2>${escapeHTML(item.video_title)}</h2><div class="meta"><span>${formatVideoTime(item.duration_sec)}</span><span>${transcriptSourceLabel(item.transcript_source)}</span><span>${segmentationModeLabel(item.segmentation_mode)}</span></div><div class="overview"><div><h3>الخلاصة العامة</h3><p>${richText(item.overall_summary || "")}</p></div><div><h3>أهداف التعلم</h3><ul>${objectives}</ul></div></div>${segments}</section>`;
  }).join("");
  const html = `<!doctype html>
<html lang="ar" dir="rtl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>شرح الفيديو - Dr. Solution.</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, Arial, sans-serif; background: #f3f6fa; color: #17212b; padding: 28px; line-height: 1.85; }
  .container { max-width: 1120px; margin: 0 auto; } h1 { margin-bottom: 24px; color: #1557b0; }
  section { margin-bottom: 42px; } section > h2 { margin-bottom: 8px; }
  .meta { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; color: #657481; font-size: .88rem; }
  .overview { display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px; padding: 20px; margin-bottom: 22px; border: 1px solid #d6dce4; background: #fff; }
  article { margin-bottom: 18px; overflow: hidden; border: 1px solid #d6dce4; border-radius: 8px; background: #fff; }
  article header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid #e2e7ed; } article header h3 { flex: 1; }
  article time { color: #657481; font-size: .82rem; direction: ltr; } .segment { display: grid; grid-template-columns: minmax(260px,.8fr) minmax(0,1.2fr); gap: 20px; padding: 18px; }
  .segment img { width: 100%; max-height: 360px; object-fit: contain; background: #eef2f7; } ul { padding-right: 22px; }
  details { padding: 12px 18px; border-top: 1px solid #e2e7ed; } summary { cursor: pointer; color: #1557b0; font-weight: 700; } details p { margin-top: 10px; }
  .error { padding: 16px; color: #b3261e; background: #fff; } .footer { text-align: center; color: #7a8792; }
  @media(max-width:720px){body{padding:14px}.overview,.segment{grid-template-columns:1fr}article header{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body><div class="container">
  <h1>شرح الفيديو الأكاديمي</h1>
  ${exportedVideos}
  <div class="footer">تم الإنشاء بواسطة Dr. Solution.</div>
</div></body></html>`;
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "dr-solution-video-analysis.html";
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("تم تنزيل شرح الفيديو بصيغة HTML");
});

applyTheme(localStorage.getItem(THEME_KEY) || "light");
updateQuestionControls();
renderHistory();
loadProviders();
refreshIcons();
