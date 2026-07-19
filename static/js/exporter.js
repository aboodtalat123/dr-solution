(function () {
  const PALETTES = {
    emerald: { accent: "#5a7d6c", accentDark: "#3d5a4e", soft: "#e8efe7", second: "#2f65f5" },
    blue: { accent: "#2f65f5", accentDark: "#2149b8", soft: "#eaf0ff", second: "#e45d48" },
    coral: { accent: "#d95742", accentDark: "#a33b2b", soft: "#fdeae6", second: "#167a66" },
  };

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

  function safeImage(value = "") {
    return value.startsWith("data:image/") ? escapeHTML(value) : "";
  }

  function questionTypeLabel(type) {
    return {
      multiple_choice: "اختيار متعدد",
      true_false: "صح أو خطأ",
      short_answer: "إجابة قصيرة",
      essay: "مقالي",
    }[type] || "سؤال";
  }

  function renderSlides(slides) {
    return slides.map((slide) => `
      <article class="slide" id="slide-${slide.page_number}">
        <header class="slide__head"><span>سلايد ${String(slide.page_number).padStart(2, "0")}</span><h2>${escapeHTML(slide.title)}</h2></header>
        <div class="slide__body">
          <section class="slide__trans">
            <b class="label">الترجمة</b>
            <p>${richText(slide.translation || "لا توجد ترجمة إضافية.")}</p>
          </section>
          <figure><img src="${safeImage(slide.preview_data_url)}" alt="السلايد ${slide.page_number}" loading="lazy" /></figure>
        </div>
        <section class="slide__explain">
          <b class="label">شرح السلايد</b>
          <p>${richText(slide.explanation)}</p>
          ${(slide.key_points || []).length ? `<ul>${slide.key_points.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>` : ""}
        </section>
        <div class="slide__insights">
          <section><h3>شرح الصورة</h3><p>${richText(slide.image_description || "لا توجد تفاصيل إضافية.")}</p></section>
          <section><h3>تحليل المحتوى</h3><p>${richText(slide.content_analysis)}</p></section>
          <section class="is-summary"><h3>خلاصة السلايد</h3><p>${richText(slide.slide_summary)}</p></section>
        </div>
      </article>`).join("");
  }

  function renderSummary(chapter) {
    return `
      <section class="summary-section" id="chapter-summary">
        <span class="section-number">المراجعة النهائية</span>
        <h2>خلاصة المادة</h2>
        <div class="summary-grid">
          <article class="summary-main"><h3>الصورة العامة</h3><p>${richText(chapter.chapter_overview)}</p><h3>الخلاصة</h3><p>${richText(chapter.chapter_summary)}</p></article>
          <aside><h3>أهداف التعلم</h3><ul>${(chapter.learning_objectives || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul><h3>المصطلحات</h3><dl>${(chapter.glossary || []).map((item) => `<div><dt>${escapeHTML(item.term)}</dt><dd>${escapeHTML(item.meaning)}</dd></div>`).join("")}</dl></aside>
        </div>
      </section>`;
  }

  function renderQuestions(questions) {
    if (!questions.length) {
      return '<section class="quiz-section" id="quiz"><span class="section-number">الاختبار</span><h2>لم يتم إنشاء أسئلة لهذه المادة</h2></section>';
    }
    return `
      <section class="quiz-section" id="quiz">
        <span class="section-number">اختبر فهمك</span>
        <div class="quiz-title"><h2>اختبار المادة</h2><button id="gradeQuiz" type="button">تصحيح الأسئلة الموضوعية</button></div>
        <p class="score" id="score">${questions.length} أسئلة</p>
        <div class="questions">${questions.map((question, index) => renderQuestion(question, index)).join("")}</div>
      </section>`;
  }

  function renderQuestion(question, index) {
    const options = question.options?.length
      ? `<div class="options">${question.options.map((option) => `<button type="button" data-option="${escapeHTML(option)}">${escapeHTML(option)}</button>`).join("")}</div>`
      : '<textarea placeholder="اكتب إجابتك هنا..."></textarea>';
    return `
      <article class="question" data-correct="${escapeHTML(question.correct_answer)}" data-type="${escapeHTML(question.type)}">
        <div class="question__meta"><b>سؤال ${index + 1}</b><span>${questionTypeLabel(question.type)}</span><span>${escapeHTML(question.difficulty)}</span></div>
        <h3>${escapeHTML(question.question)}</h3>
        ${options}
        <button class="reveal" type="button">كشف الإجابة</button>
        <div class="answer"><b>الإجابة النموذجية:</b> ${richText(question.correct_answer)}${question.explanation ? `<p>${richText(question.explanation)}</p>` : ""}</div>
      </article>`;
  }

  function buildHTML(payload, themeName) {
    const chapter = payload.result;
    const palette = PALETTES[themeName] || PALETTES.emerald;
    const direction = payload.target_language === "ar" ? "rtl" : "ltr";
    const navSlides = chapter.slides.map((slide) => `<a href="#slide-${slide.page_number}"><span>${slide.page_number}</span>${escapeHTML(slide.title)}</a>`).join("");
    return `<!doctype html>
<html lang="${escapeHTML(payload.target_language)}" dir="${direction}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="description" content="شرح أكاديمي تفاعلي صادر من Dr. Solution." />
  <title>${escapeHTML(chapter.chapter_title)} | Dr. Solution.</title>
  <style>
    :root{color-scheme:light;--bg:#f6f8f7;--surface:#fff;--soft:#eef2ef;--ink:#17191f;--text:#444b51;--muted:#767d82;--line:#dce2de;--accent:${palette.accent};--accent-dark:${palette.accentDark};--accent-soft:${palette.soft};--second:${palette.second};--radius:12px;--sidebar:270px}
    [data-theme="dark"]{color-scheme:dark;--bg:#141817;--surface:#1d2220;--soft:#272d2a;--ink:#f5f8f5;--text:#d1d7d3;--muted:#9da6a0;--line:#37403b;--accent:${palette.accent};--accent-dark:#9fe1ca;--accent-soft:#183930}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--bg);font-family:"Segoe UI",Tahoma,Arial,sans-serif;letter-spacing:0}button,textarea{font:inherit;letter-spacing:0}button{cursor:pointer}.top{position:fixed;z-index:30;inset:0 0 auto;height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(14px)}.brand{display:flex;align-items:center;gap:10px}.brand__mark{width:36px;height:36px;display:grid;place-items:center;border-radius:8px;color:#fff;background:var(--accent);font-weight:800}.brand strong{display:block;font-size:15px}.brand small{color:var(--muted);font-size:10px}.commands{display:flex;gap:7px}.commands button,.quiz-title button{min-height:38px;padding:0 13px;border:1px solid var(--line);border-radius:6px;color:var(--ink);background:var(--surface);font-weight:600}.commands button:hover{border-color:var(--accent);color:var(--accent-dark)}aside.nav{position:fixed;z-index:20;inset:68px 0 0 auto;width:var(--sidebar);overflow:auto;padding:20px 14px;border-left:1px solid var(--line);background:var(--soft)}.nav h2{margin:0 8px 14px;font-size:12px;color:var(--muted)}.nav a{display:flex;align-items:center;gap:9px;padding:9px;border-radius:6px;color:var(--text);text-decoration:none;font-size:12px;line-height:1.35}.nav a:hover,.nav a.is-active{color:var(--accent-dark);background:var(--surface)}.nav a span{width:24px;height:24px;display:grid;place-items:center;flex:0 0 auto;border-radius:5px;background:var(--accent-soft);font-size:10px;font-weight:700}.nav .nav-special{margin-top:8px;border-top:1px solid var(--line);padding-top:12px}.content{width:min(1160px,calc(100% - var(--sidebar) - 64px));margin:0 0 0 32px;padding:110px 0 64px}.hero{margin-bottom:28px}.hero .eyebrow,.section-number{display:block;margin-bottom:7px;color:var(--accent-dark);font-size:11px;font-weight:700}.hero h1{margin-bottom:8px;font-size:30px;line-height:1.3}.hero p{color:var(--text);font-size:16px;line-height:1.8;max-width:700px}.hero__meta{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:10px;color:var(--muted);font-size:12px}.hero__meta span{display:inline-flex;align-items:center;gap:5px}.slide,.summary-section,.quiz-section{margin-top:28px}.slide{border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);overflow:hidden;margin-bottom:20px;box-shadow:0 6px 20px rgba(0,0,0,0.04);scroll-margin-top:80px}.slide__head{display:flex;align-items:center;gap:14px;padding:14px 20px;border-bottom:1px solid var(--line);background:linear-gradient(135deg,var(--surface) 60%,var(--soft))}.slide__head span{min-width:72px;padding:6px 12px;border-radius:6px;color:#fff;background:var(--accent);font-size:11px;font-weight:700;text-align:center}.slide__head h2{margin:0;font-size:18px;font-weight:600}.slide__body{display:grid;grid-template-columns:1fr 1fr;align-items:stretch}.slide__trans{padding:24px 22px;background:linear-gradient(160deg,var(--accent-soft) 0%,var(--surface) 80%);border-left:1px solid var(--line)}.slide__trans .label{color:var(--second)}.slide__trans p{color:var(--text);font-size:16px;line-height:2;white-space:pre-wrap}.slide figure{min-height:380px;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 70% 30%,color-mix(in srgb,var(--accent) 4%,transparent) 0%,transparent 70%),var(--soft)}.slide figure img{width:100%;max-height:520px;object-fit:contain;border:1px solid var(--line);border-radius:6px;background:#fff;box-shadow:0 14px 30px rgba(0,0,0,0.08)}.slide__explain{padding:26px 24px;border-top:1px solid var(--line)}.label{display:flex;align-items:center;gap:6px;margin-bottom:12px;color:var(--accent-dark);font-size:12px;font-weight:700}.slide__explain p{color:var(--text);font-size:16px;line-height:2;white-space:pre-wrap}.slide__explain ul{margin-top:18px;padding:18px 0 0;border-top:1px solid var(--line);list-style:none}.slide__explain li{position:relative;padding-right:22px;color:var(--text);font-size:14px;line-height:1.7;margin-bottom:8px}.slide__explain li::before{content:"";position:absolute;top:10px;right:2px;width:7px;height:7px;border-radius:50%;background:var(--second);box-shadow:0 0 0 3px color-mix(in srgb,var(--second) 15%,transparent)}.slide__insights{display:grid;grid-template-columns:1fr 1fr 1.2fr;border-top:1px solid var(--line)}.slide__insights section{padding:20px;border-left:1px solid var(--line);border-top:1px solid var(--line)}.slide__insights section:first-child,.slide__insights section:nth-child(2){border-top:0}.slide__insights section:last-child{border-left:0}.slide__insights h3{display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:13px;color:var(--ink)}.slide__insights p{margin:0;font-size:13px;color:var(--text);line-height:1.8;white-space:pre-wrap}.slide__insights .is-summary{background:linear-gradient(135deg,var(--accent-soft) 0%,color-mix(in srgb,var(--accent-soft) 60%,var(--surface)) 100%);border-top:2px solid color-mix(in srgb,var(--accent) 20%,transparent);grid-column:1/-1}.slide__insights .is-summary h3,.slide__insights .is-summary p{color:var(--accent-dark)}.summary-section{margin-bottom:28px}.summary-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,0.65fr);gap:18px;align-items:start}.summary-main,.summary-aside{display:grid;gap:18px}.summary-aside h3{margin-bottom:10px;font-size:14px}.summary-aside ul{padding-right:16px;color:var(--text);line-height:1.7}.summary-aside dl div{display:grid;gap:3px;padding-bottom:10px;border-bottom:1px solid var(--line)}.summary-aside dl div:last-child{padding-bottom:0;border-bottom:0}.summary-aside dt{font-weight:700;color:var(--ink);font-size:13px}.summary-aside dd{color:var(--muted);font-size:12px;line-height:1.6;margin:0}.quiz-section{margin-bottom:40px}.quiz-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:16px}.score{color:var(--muted);margin-bottom:14px;font-size:13px}.questions{display:grid;gap:14px}.question{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:var(--surface)}.question__meta{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);color:var(--muted);font-size:11px}.question__meta b{color:var(--accent-dark)}.question__meta span:last-child{margin-right:auto}.question h3{padding:16px;margin:0;font-size:16px;line-height:1.75}.options{display:grid;gap:8px;padding:0 16px 16px}.options button{min-height:44px;display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line);border-radius:6px;color:var(--text);background:var(--soft);text-align:right}.options button::before{content:"";width:15px;height:15px;flex:0 0 auto;border:2px solid var(--line);border-radius:50%;background:var(--surface)}.options button.is-selected{border-color:var(--second);background:color-mix(in srgb,var(--second) 10%,var(--surface))}.options button.is-selected::before{border:4px solid var(--second)}.options button.is-correct{border-color:var(--accent);color:var(--accent-dark);background:var(--accent-soft)}.options button.is-wrong{border-color:#c94343;color:#c94343;background:color-mix(in srgb,#c94343 8%,var(--surface))}.question textarea{width:100%;min-height:92px;margin:0 16px 16px;resize:vertical;padding:12px;border:1px solid var(--line);border-radius:6px;background:var(--soft);font:inherit;line-height:1.7}.question .reveal{display:block;margin:0 16px 16px;padding:6px 12px;border:0;border-radius:5px;color:var(--muted);background:transparent;font-size:12px}.question .reveal:hover{color:var(--accent-dark)}.answer{display:none;margin:0 16px 16px;padding:14px;border-right:3px solid var(--accent);color:var(--text);background:var(--accent-soft);line-height:1.7}.answer.is-visible{display:block}.answer b{color:var(--accent-dark)}.footer{text-align:center;padding:40px 0;color:var(--muted);font-size:12px}@media(max-width:850px){:root{--sidebar:0px}.top{padding:0 12px}.brand small{display:none}aside.nav{display:none}.content{width:auto;margin:0;padding:96px 14px 40px}.hero h1{font-size:26px}.slide__body,.summary-grid{grid-template-columns:1fr}.slide figure{min-height:300px;border-bottom:1px solid var(--line);border-left:0}.slide__trans{border-left:0;border-bottom:1px solid var(--line)}.slide__insights{grid-template-columns:1fr}.slide__insights section{border-bottom:1px solid var(--line);border-left:0;border-top:0}.slide__insights section:last-child{border-bottom:0}.quiz-title{align-items:stretch;flex-direction:column}.commands button span{display:none}}@media print{.top,aside.nav,.quiz-title button,.reveal{display:none!important}.content{width:100%;margin:0;padding:0}.slide,.summary-section,.quiz-section{break-inside:avoid;box-shadow:none}.slide{break-after:page}.answer{display:block}body{background:#fff}}.content{width:auto;max-width:1160px;margin-right:calc(var(--sidebar) + 32px);margin-left:32px}@media(max-width:850px){.content{max-width:none;margin:0;padding:96px 14px 40px}}
  </style>...
<body>
  <header class="top"><div class="brand"><span class="brand__mark">Dr</span><div dir="ltr"><strong>Dr. Solution.</strong><small dir="rtl">صفحة دراسة تفاعلية</small></div></div><div class="commands"><button id="themeToggle" type="button"><span>تبديل المظهر</span></button><button type="button" onclick="window.print()"><span>طباعة</span></button></div></header>
  <aside class="nav"><h2>صفحات المادة</h2>${navSlides}<div class="nav-special"><a href="#chapter-summary"><span>خ</span>خلاصة المادة</a><a href="#quiz"><span>س</span>الاختبار</a></div></aside>
  <main class="content">
    <section class="hero"><span class="eyebrow">شرح تفاعلي جاهز للدراسة</span><h1>${escapeHTML(chapter.chapter_title)}</h1><p>${richText(chapter.chapter_overview)}</p><div class="hero__meta"><span>${chapter.slides.length} سلايد</span><span>${chapter.questions.length} سؤال</span><span>${escapeHTML(payload.model)}</span><span>${escapeHTML(payload.filename)}</span></div></section>
    <section class="slides">${renderSlides(chapter.slides)}</section>
    ${renderSummary(chapter)}
    ${renderQuestions(chapter.questions)}
    <footer class="footer">صُنعت هذه الصفحة بواسطة Dr. Solution.</footer>
  </main>
  <script>
    const root=document.documentElement;
    document.getElementById('themeToggle').addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark'});
    document.querySelectorAll('.question').forEach(question=>{
      question.querySelectorAll('[data-option]').forEach(option=>option.addEventListener('click',()=>{
        question.querySelectorAll('[data-option]').forEach(item=>item.classList.remove('is-selected','is-correct','is-wrong'));
        option.classList.add('is-selected');
      }));
      question.querySelector('.reveal').addEventListener('click',()=>question.querySelector('.answer').classList.toggle('is-visible'));
    });
    document.getElementById('gradeQuiz')?.addEventListener('click',()=>{
      const questions=[...document.querySelectorAll('.question[data-type="multiple_choice"],.question[data-type="true_false"]')];let score=0;
      questions.forEach(question=>{const expected=question.dataset.correct.trim();const selected=question.querySelector('.is-selected');question.querySelectorAll('[data-option]').forEach(option=>{if(option.dataset.option.trim()===expected)option.classList.add('is-correct')});if(selected){if(selected.dataset.option.trim()===expected)score++;else selected.classList.add('is-wrong')}});
      document.getElementById('score').textContent=questions.length?'النتيجة: '+score+' من '+questions.length+' في الأسئلة الموضوعية':'راجع إجاباتك مع النماذج';
    });
    const links=[...document.querySelectorAll('.nav a[href^="#slide-"]')];
    const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){links.forEach(link=>link.classList.toggle('is-active',link.hash==='#'+entry.target.id))}}),{rootMargin:'-25% 0px -65%'});
    document.querySelectorAll('.slide').forEach(slide=>observer.observe(slide));
  <\/script>
</body>
</html>`;
  }

  function download(payload, themeName = "emerald") {
    const html = buildHTML(payload, themeName);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeName = (payload.result.chapter_title || "dr-solution-study").replace(/[\\/:*?"<>|]/g, "-");
    link.href = url;
    link.download = `${safeName}.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  window.DrSolutionExporter = { buildHTML, download };
})();
