(function () {
  var CHAT_STORAGE_KEY = "dr-solution.chat-history";
  var API_URL = "/api/chat";
  var isOpen = false;
  var messages = [];
  var isWaiting = false;
  var activeSlideNumber = null;

  var style = document.createElement("style");
  style.textContent = `
    .dr-bubble{position:fixed;z-index:999;right:24px;bottom:24px;width:62px;height:62px;border:0;border-radius:50%;color:#fff;background:linear-gradient(135deg,#1a73e8,#0d47a1);box-shadow:0 6px 28px rgba(26,115,232,0.35),0 0 0 3px rgba(184,149,74,0.2);cursor:pointer;transition:all 0.35s cubic-bezier(0.34,1.56,0.64,1);display:grid;place-items:center;animation:dr-pulse 3s ease-in-out infinite}
    .dr-bubble::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:2px solid rgba(26,115,232,0.15);animation:dr-ring 3s ease-in-out infinite}
    @keyframes dr-pulse{0%,100%{box-shadow:0 6px 28px rgba(26,115,232,0.35),0 0 0 3px rgba(184,149,74,0.2)}50%{box-shadow:0 8px 36px rgba(26,115,232,0.45),0 0 0 5px rgba(184,149,74,0.25)}}
    @keyframes dr-ring{0%,100%{opacity:0.3;transform:scale(1)}50%{opacity:0.6;transform:scale(1.08)}}
    .dr-bubble:hover{transform:scale(1.12);box-shadow:0 10px 36px rgba(26,115,232,0.45),0 0 0 4px rgba(184,149,74,0.25);animation:none}
    .dr-bubble:hover::after{animation:none;opacity:0}
    .dr-bubble.is-open{transform:rotate(45deg) scale(0.9);animation:none}
    .dr-bubble.is-open:hover{transform:rotate(45deg) scale(1)}
    .dr-bubble.is-open::after{opacity:0;animation:none}
    .dr-panel{position:fixed;z-index:998;left:0;top:0;bottom:0;width:420px;max-width:92vw;background:color-mix(in srgb,var(--surface,#fff) 90%,transparent);backdrop-filter:blur(32px) saturate(180%);-webkit-backdrop-filter:blur(32px) saturate(180%);border-left:1px solid var(--line,#dfe3dd);box-shadow:8px 0 50px rgba(0,0,0,0.12);transform:translateX(-105%);transition:transform 0.4s cubic-bezier(0.22,1,0.36,1);display:flex;flex-direction:column;direction:rtl}
    .dr-panel.is-open{transform:translateX(0)}
    body.dr-open .main{margin-left:420px !important;padding-left:24px !important}
    .main{transition:margin-left .4s cubic-bezier(.22,1,.36,1)}
    .dr-head{padding:14px 18px;border-bottom:1px solid var(--line,#dfe3dd);background:linear-gradient(135deg,var(--surface,#fff) 40%,var(--primary-soft,#e8f0fe));flex-shrink:0;display:flex;align-items:center;gap:10px}
    .dr-avatar{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#1a73e8,#0d47a1);color:#fff;display:grid;place-items:center;flex-shrink:0;font-size:17px;box-shadow:0 3px 10px rgba(26,115,232,0.2)}
    .dr-head-info{min-width:0;flex:1}
    .dr-head-info strong{display:block;font-size:14px;color:var(--ink,#17191f)}
    .dr-head-info span{color:var(--muted,#737984);font-size:11px}
    .dr-head-close{width:32px;height:32px;border:0;border-radius:8px;color:var(--muted,#737984);background:transparent;cursor:pointer;display:grid;place-items:center;transition:all 0.15s;flex-shrink:0}
    .dr-head-close:hover{background:var(--surface-soft,#f0f2ef);color:var(--ink,#17191f)}
    .dr-msgs{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:12px;scroll-behavior:smooth}
    .dr-msg{max-width:88%;padding:12px 16px;border-radius:16px;font-size:14px;line-height:1.8;white-space:pre-wrap;animation:dr-in 0.25s ease}
    @keyframes dr-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
    .dr-msg.user{background:linear-gradient(135deg,#1a73e8,#0d47a1);color:#fff;align-self:flex-end;border-bottom-left-radius:4px}
.dr-msg.bot{background:color-mix(in srgb,var(--surface,#fff) 95%,var(--primary));color:var(--ink-soft,#41464f);align-self:flex-start;border-bottom-right-radius:4px;border:1px solid var(--line,#dfe3dd);box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.dr-msg.bot .dr-label{display:flex;align-items:center;gap:5px;margin-bottom:5px;color:var(--primary,#1a73e8);font-size:10px;font-weight:700}
    .dr-msg.bot .dr-label svg{width:12px;height:12px}
    .dr-msg.bot .dr-src{margin-top:8px;padding-top:8px;border-top:1px solid var(--line,#dfe3dd)}
    .dr-msg.bot .dr-src span{display:block;color:var(--muted,#737984);font-size:10px;margin-bottom:4px}
    .dr-msg.bot .dr-src a{display:block;color:var(--blue,#2f65f5);font-size:11px;text-decoration:none;margin-bottom:3px}
    .dr-msg.bot .dr-src a:hover{text-decoration:underline}
    .dr-msg.err{background:color-mix(in srgb,var(--danger,#c94343) 6%,transparent);color:var(--danger,#c94343);align-self:flex-start;border:1px solid color-mix(in srgb,var(--danger,#c94343) 16%,transparent)}
    .dr-type{display:flex;gap:4px;padding:14px 18px;align-self:flex-start}
    .dr-type span{width:7px;height:7px;border-radius:50%;background:var(--muted,#737984);animation:dr-b 1.4s infinite ease-in-out}
    .dr-type span:nth-child(2){animation-delay:0.16s}
    .dr-type span:nth-child(3){animation-delay:0.32s}
    @keyframes dr-b{0%,80%,100%{transform:scale(0.6)}40%{transform:scale(1)}}
    .dr-inp-wrap{padding:12px 14px 14px;border-top:1px solid var(--line,#dfe3dd);background:color-mix(in srgb,var(--surface,#fff) 90%,transparent);flex-shrink:0;display:flex;gap:8px}
    .dr-inp{flex:1;min-height:42px;padding:10px 14px;border:1px solid var(--line-strong,#c7cdc5);border-radius:12px;outline:0;color:var(--ink,#17191f);background:var(--surface-soft,#f0f2ef);font:inherit;font-size:13px;line-height:1.5;resize:none;transition:border-color 0.2s,box-shadow 0.2s}
    .dr-inp:focus{border-color:var(--primary,#1a73e8);box-shadow:0 0 0 3px var(--primary-glow, rgba(26,115,232,0.13))}
    .dr-send{width:42px;height:42px;border:0;border-radius:12px;color:#fff;background:linear-gradient(135deg,var(--primary,#1a73e8),#0d47a1);cursor:pointer;display:grid;place-items:center;flex-shrink:0;transition:all 0.2s}
    .dr-send:hover{transform:scale(1.08);box-shadow:0 4px 16px var(--primary-glow, rgba(26,115,232,0.2))}
    .dr-send:disabled{opacity:0.4;cursor:not-allowed;transform:none}
    .dr-send svg{width:18px;height:18px}
    .dr-welcome{text-align:center;padding:36px 18px;color:var(--muted,#737984)}
    .dr-welcome svg{width:44px;height:44px;color:var(--primary,#1a73e8);margin-bottom:10px;opacity:0.5}
    .dr-welcome strong{display:block;font-size:15px;color:var(--ink,#17191f);margin-bottom:5px}
    .dr-welcome p{font-size:12px;line-height:1.7;margin:0}
    @media(max-width:900px){body.dr-open .main{margin-left:0 !important}.dr-panel{width:100vw;max-width:100vw;box-shadow:none}}@media(max-width:600px){.dr-bubble{right:14px;bottom:14px;width:56px;height:56px}}
  `;
  document.head.appendChild(style);

  function loadMessages() {
    try { return JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY)) || []; } catch { return []; }
  }

  function saveMessages() {
    try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages.slice(-50))); } catch {}
  }

  function addMessage(text, role, sources) {
    messages.push({ text: text, role: role, sources: sources || [], ts: Date.now() });
    saveMessages();
    renderMessages();
  }

  function getActiveKey() {
    var el = document.getElementById("apiKeyInput");
    var key = el ? el.value.trim() : "";
    if (!key) {
      try {
        var saved = localStorage.getItem("dr-solution.apikey-gemini");
        if (saved) key = saved;
      } catch {}
    }
    return key;
  }

  function getActiveProvider() {
    var el = document.getElementById("providerSelect");
    return el ? el.options[el.selectedIndex].textContent : "Gemini";
  }

  function getSlideContext(slideNum) {
    var el = null;
    if (slideNum) el = document.getElementById("slide-" + slideNum);
    if (!el) el = document.querySelector(".slide-card:target");
    if (!el && activeSlideNumber) el = document.getElementById("slide-" + activeSlideNumber);
    if (!el) el = document.querySelector(".slide-card");
    if (!el) return "";
    var parts = [];
    var t = el.querySelector("h2");
    var e = el.querySelector(".slide-explanation");
    var tl = el.querySelector(".slide-translation-col .slide-line-content");
    var insights = el.querySelectorAll(".slide-insight");
    var s = el.querySelector(".slide-insight.is-summary p");
    var orig = el.querySelector(".slide-original-data");
    var sa = el.querySelector(".slide-number");
    if (sa) parts.push("رقم السلايد: " + sa.textContent);
    if (t) parts.push("العنوان: " + t.textContent);
    if (orig) parts.push("النص الأصلي للسلايد: " + orig.textContent);
    if (tl) parts.push("الترجمة: " + tl.textContent);
    if (e) parts.push("الشرح: " + e.textContent);
    if (insights.length >= 2) parts.push("شرح الصورة: " + (insights[0].querySelector("p")?.textContent || ""));
    if (insights.length >= 3) parts.push("تحليل المحتوى: " + (insights[1].querySelector("p")?.textContent || ""));
    if (s) parts.push("خلاصة السلايد: " + s.textContent);
    return parts.join("\n");
  }

  function detectSlideNumber(q) {
    var m = String(q).match(/(?:السلايد|الشريحة|شريحه|سلايد|slide)\s*(?:رقم\s*)?(\d+)/i);
    if (m) {
      var n = m[1];
      if (document.getElementById("slide-" + n)) return n;
    }
    return null;
  }

  function getPageContext(slideNum) {
    var titleEl = document.querySelector(".results__title h1") || document.querySelector("h1");
    var meta = Array.from(document.querySelectorAll(".result-meta span")).map(function (el) { return el.textContent; }).join(" | ");
    var ctx = "";
    if (titleEl) ctx += "المادة: " + titleEl.textContent + "\n";
    if (meta) ctx += meta + "\n";
    ctx += "عدد السلايدات: " + document.querySelectorAll(".slide-card").length + "\n";
    ctx += getSlideContext(slideNum);
    return ctx;
  }

  function renderMessages() {
    var c = document.getElementById("dr-msgs");
    if (!c) return;
    if (!messages.length) {
      var hasKey = getActiveKey().length > 0;
      var aiName = getActiveProvider();
      var tip = hasKey
        ? ('<p>اسألني أي سؤال عام أو عن السلايد الحالي.<br><span style="font-size:11px;color:var(--primary,#1a73e8);font-weight:600">متصلة بـ ' + esc(aiName) + '</span></p>')
        : '<p style="color:var(--danger,#c94343)">ما في مفتاح API. أضف مفتاح المحرك من القالب أولاً.</p>';
      c.innerHTML = '<div class="dr-welcome"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.6l1.7 6.3L20 10.6l-6.3 1.7L12 18.6l-1.7-6.3L4 10.6l6.3-1.7z"/><path d="M18.4 3.4l.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2L16 6.3l2.2-.7z" opacity=".7"/></svg><strong>مساعد Dr. Solution.</strong>' + tip + '</div>';
      return;
    }
    c.innerHTML = messages.map(function (msg) {
      if (msg.role === "user") return '<div class="dr-msg user">' + esc(msg.text) + '</div>';
      var src = msg.sources && msg.sources.length ? '<div class="dr-src"><span>المصادر:</span>' + msg.sources.map(function (s) { return '<a href="' + escA(s.url || "#") + '" target="_blank">' + esc(s.title || s) + "</a>"; }).join("") + "</div>" : "";
      return '<div class="dr-msg bot"><div class="dr-label"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.6l1.7 6.3L20 10.6l-6.3 1.7L12 18.6l-1.7-6.3L4 10.6l6.3-1.7z"/><path d="M18.4 3.4l.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2L16 6.3l2.2-.7z" opacity=".75"/></svg> Dr. Solution.</div>' + rt(msg.text) + src + "</div>";
    }).join("");
    c.scrollTop = c.scrollHeight;
  }

  function esc(v) { return String(v).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;"); }
  function escA(v) { return String(v).replaceAll('"', "&quot;").replaceAll("&", "&amp;"); }
  function rt(v) { return esc(v).replaceAll("\n", "<br />"); }

  function showTyping() {
    var c = document.getElementById("dr-msgs");
    if (!c) return;
    var d = document.createElement("div");
    d.className = "dr-type";
    d.id = "dr-type";
    d.innerHTML = "<span></span><span></span><span></span>";
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
  }

  function hideTyping() { var e = document.getElementById("dr-type"); if (e) e.remove(); }

  function sendQuestion() {
    var inp = document.getElementById("dr-inp");
    var btn = document.getElementById("dr-send");
    var q = (inp.value || "").trim();
    if (!q || isWaiting) return;

    var key = getActiveKey();
    if (!key) {
      addMessage("عذراً، ما في مفتاح API. روح للقالب فوق وأضف مفتاح المحرك أولاً.", "err");
      inp.focus();
      return;
    }

    isWaiting = true;
    btn.disabled = true;
    addMessage(q, "user");
    inp.value = "";
    inp.style.height = "auto";
    showTyping();

    var qNum = detectSlideNumber(q);
    var slideNum = qNum || activeSlideNumber || "";
    var ctx = getPageContext(slideNum);
    var slide = (slideNum && document.getElementById("slide-" + slideNum)) || document.querySelector(".slide-card:target") || document.querySelector(".slide-card");
    var sn = slide ? (slide.id || "").replace("slide-", "") : "";
    var provider = document.getElementById("providerSelect");
    var providerId = provider ? provider.value : "gemini";

    var recent = messages.slice(-20).map(function (m) {
      return { role: m.role, text: m.text };
    });

    fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: q,
        page_context: ctx,
        slide_number: sn,
        api_key: key,
        provider: providerId,
        history: recent
      })
    })
    .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
    .then(function (d) { hideTyping(); addMessage(d.answer || "عذراً، لا توجد إجابة.", "bot", d.sources || []); })
    .catch(function () { hideTyping(); addMessage("عذراً، حدث خطأ في الاتصال.", "err"); })
    .finally(function () { isWaiting = false; btn.disabled = false; inp.focus(); });
  }

  function toggleChat(open) {
    isOpen = open !== undefined ? open : !isOpen;
    var panel = document.getElementById("dr-panel");
    var bubble = document.getElementById("dr-bubble");
    if (!panel || !bubble) return;
    panel.classList.toggle("is-open", isOpen);
    bubble.classList.toggle("is-open", isOpen);
    document.body.classList.toggle("dr-open", isOpen);
    if (isOpen) {
      renderMessages();
      var sub = panel.querySelector(".dr-head-info span");
      if (sub) {
        var key = getActiveKey();
        var name = getActiveProvider();
        sub.textContent = key ? name + " · متصل" : "المساعد الذكي";
        sub.style.color = key ? "var(--primary,#1a73e8)" : "";
      }
    }
  }

  function init() {
    messages = loadMessages();
    window.DrSolutionChat = {
      setActiveSlide: function (n) { activeSlideNumber = n ? String(n) : null; }
    };

    var bubble = document.createElement("button");
    bubble.id = "dr-bubble";
    bubble.className = "dr-bubble";
    bubble.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.6l1.7 6.3L20 10.6l-6.3 1.7L12 18.6l-1.7-6.3L4 10.6l6.3-1.7z"/><path d="M18.4 3.4l.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2L16 6.3l2.2-.7z" opacity=".75"/></svg>';
    bubble.setAttribute("aria-label", "فتح المساعد");
    bubble.title = "المساعد الذكي";
    document.body.appendChild(bubble);

    var panel = document.createElement("div");
    panel.id = "dr-panel";
    panel.className = "dr-panel";
    panel.innerHTML =
      '<div class="dr-head"><div class="dr-avatar"><svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.6l1.7 6.3L20 10.6l-6.3 1.7L12 18.6l-1.7-6.3L4 10.6l6.3-1.7z"/><path d="M18.4 3.4l.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2L16 6.3l2.2-.7z" opacity=".75"/></svg></div><div class="dr-head-info"><strong>Dr. Solution.</strong><span>المساعد الذكي</span></div><button class="dr-head-close" id="dr-close" aria-label="إغلاق"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>' +
      '<div class="dr-msgs" id="dr-msgs"></div>' +
      '<div class="dr-inp-wrap"><textarea class="dr-inp" id="dr-inp" placeholder="اسأل عن السلايد، الشرح..." rows="1" aria-label="سؤال"></textarea><button class="dr-send" id="dr-send" aria-label="إرسال"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button></div>';
    document.body.appendChild(panel);
    renderMessages();

    bubble.addEventListener("click", function () { toggleChat(); });
    document.getElementById("dr-close").addEventListener("click", function () { toggleChat(false); });
    document.getElementById("dr-send").addEventListener("click", sendQuestion);
    document.getElementById("providerSelect")?.addEventListener("change", function () {
      if (isOpen) toggleChat(true);
    });
    var input = document.getElementById("dr-inp");
    input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); } });
    input.addEventListener("input", function () { this.style.height = "auto"; this.style.height = Math.min(this.scrollHeight, 110) + "px"; });
    window.addEventListener("resize", function () { if (window.innerWidth <= 600 && isOpen) toggleChat(false); });
    window.addEventListener("keychange", function () { if (isOpen) renderMessages(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
