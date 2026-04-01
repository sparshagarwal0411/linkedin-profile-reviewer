const form = document.getElementById("uploadForm");
const scoreEl = document.getElementById("score");
const suggestions = document.getElementById("suggestions");
const loading = document.getElementById("loading");
const loadingText = document.getElementById("loadingText");
const result = document.getElementById("result");
const errorBox = document.getElementById("errorBox");
const themeToggle = document.getElementById("themeToggle");
const connectionsEl = document.getElementById("connectionsCount");
const followersEl = document.getElementById("followersCount");
const profileStats = document.getElementById("profileStats");
const scoreCard = document.querySelector(".score-card");
const introLoader = document.getElementById("introLoader");
const scoreActions = document.getElementById("scoreActions");
const downloadCertBtn = document.getElementById("downloadCertificateBtn");
const shareLinkedInLink = document.getElementById("shareLinkedInLink");
const scoreBreakdownEl = document.getElementById("scoreBreakdown");
const hireProbBanner = document.getElementById("hireProbBanner");
const submitBtn = form ? form.querySelector('button[type="submit"]') : null;
const fileDrop = document.querySelector(".file-drop");
const backToTopBtn = document.getElementById("backToTopBtn");

const LOADING_MESSAGES = [
  "Analyzing your profile…",
  "Scoring keywords and impact…",
  "Comparing to strong profiles…",
  "Drafting recruiter-style notes…",
  "Building rewrites and your roadmap…",
];

let loadingIntervalId = null;

function startLoadingMessages() {
  if (!loadingText) return;
  let i = 0;
  loadingText.textContent = LOADING_MESSAGES[0];
  if (loadingIntervalId) clearInterval(loadingIntervalId);
  loadingIntervalId = setInterval(() => {
    i = (i + 1) % LOADING_MESSAGES.length;
    loadingText.textContent = LOADING_MESSAGES[i];
  }, 2200);
}

function stopLoadingMessages() {
  if (loadingIntervalId) {
    clearInterval(loadingIntervalId);
    loadingIntervalId = null;
  }
}

function scrollToScoreCard() {
  const scoreSection = document.querySelector(".score-card");
  if (!scoreSection) return;
  scoreSection.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

function bindFileDropEffects() {
  const fileInput = document.getElementById("pdf");
  if (!fileDrop || !fileInput) return;

  const setDrag = (active) => {
    fileDrop.classList.toggle("drag-over", active);
  };

  ["dragenter", "dragover"].forEach((eventName) => {
    fileDrop.addEventListener(eventName, (event) => {
      event.preventDefault();
      setDrag(true);
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    fileDrop.addEventListener(eventName, () => {
      setDrag(false);
    });
  });
}

function bindBackToTop() {
  if (!backToTopBtn) return;

  const onScroll = () => {
    const shouldShow = window.scrollY > 500;
    backToTopBtn.classList.toggle("show", shouldShow);
  };

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  backToTopBtn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("pdf");
  const targetRoleInput = document.getElementById("target_role");
  const experienceLevelInput = document.getElementById("experience_level");
  const dreamCompaniesInput = document.getElementById("dream_companies");

  clearError();

  if (!fileInput.files.length) {
    showError("Please select a LinkedIn PDF file.");
    return;
  }

  loading.hidden = false;
  startLoadingMessages();
  if (submitBtn) submitBtn.disabled = true;
  result.hidden = true;

  const formData = new FormData();
  formData.append("pdf", fileInput.files[0]);
  formData.append("target_role", targetRoleInput.value || "");
  formData.append("experience_level", experienceLevelInput.value || "");
  formData.append("dream_companies", dreamCompaniesInput.value || "");

  try {
    let res = null;
    let rawText = "";
    let data = null;
    const MAX_ATTEMPTS = 2;

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      res = await fetch("/review", {
        method: "POST",
        body: formData,
      });

      rawText = await res.text();
      data = null;
      if (rawText) {
        try {
          data = JSON.parse(rawText);
        } catch {
          data = null;
        }
      }

      const modelJsonParseError =
        data &&
        data.error &&
        String(data.error).toLowerCase().includes("model output was not valid json");

      // Auto-retry once for flaky model formatting responses.
      if (res.ok || !modelJsonParseError || attempt === MAX_ATTEMPTS) {
        break;
      }
    }

    if (!res.ok) {
      const serverMsg =
        data && data.error
          ? `${data.error}${data.details ? ` – ${String(data.details).slice(0, 300)}` : ""}`
          : null;
      const looksLikeHtmlError =
        typeof rawText === "string" &&
        /<html|<head|<body|internal server error/i.test(rawText);
      const fallback =
        looksLikeHtmlError
          ? `Server error (${res.status}). The backend likely timed out or crashed. Please retry once; if it persists, redeploy backend with updated timeout settings.`
          : rawText && rawText.trim()
          ? `Server error (${res.status}). Response: ${rawText.trim().slice(0, 300)}`
          : `Server error (${res.status}).`;
      throw new Error(serverMsg || fallback);
    }

    if (!data || typeof data !== "object") {
      throw new Error("Server returned a non-JSON success response.");
    }

    const review = data.review;
    renderReview(review);
    result.hidden = false;
    scrollToScoreCard();
  } catch (err) {
    console.error(err);
    const message =
      err instanceof Error ? err.message : "Failed to get review.";
    showError(message);
  } finally {
    stopLoadingMessages();
    loading.hidden = true;
    if (submitBtn) submitBtn.disabled = false;
  }
});

const THEME_KEY = "linkedin-reviewer-theme";

function applyTheme(theme) {
  const body = document.body;
  const iconSpan = themeToggle?.querySelector(".theme-icon");
  const labelSpan = themeToggle?.querySelector(".theme-label");

  if (theme === "dark") {
    body.classList.add("dark-theme");
    if (iconSpan) iconSpan.textContent = "🌙";
    if (labelSpan) labelSpan.textContent = "Dark mode on";
  } else {
    body.classList.remove("dark-theme");
    if (iconSpan) iconSpan.textContent = "☀️";
    if (labelSpan) labelSpan.textContent = "Dark mode";
  }
}

function getPreferredTheme() {
  const stored = window.localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  const systemPrefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return systemPrefersDark ? "dark" : "light";
}

if (themeToggle) {
  applyTheme(getPreferredTheme());

  themeToggle.addEventListener("click", () => {
    const isDark = document.body.classList.contains("dark-theme");
    const nextTheme = isDark ? "light" : "dark";
    applyTheme(nextTheme);
    try {
      window.localStorage.setItem(THEME_KEY, nextTheme);
    } catch {
      /* ignore */
    }
  });
}

function barRow(label, value) {
  const v = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  const pct = v != null ? v : 0;
  const display = v != null ? String(v) : "—";
  return `
    <div class="breakdown-row">
      <div class="breakdown-label"><span>${escapeHtml(label)}</span><span class="breakdown-num">${display}</span></div>
      <div class="breakdown-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
        <div class="breakdown-fill" style="width:${v != null ? pct : 0}%"></div>
      </div>
    </div>
  `;
}

function renderScoreBreakdown(review) {
  if (!scoreBreakdownEl) return;
  const sb = review.score_breakdown;
  if (!sb || typeof sb !== "object") {
    scoreBreakdownEl.hidden = true;
    scoreBreakdownEl.innerHTML = "";
    return;
  }
  const hasAny =
    typeof sb.keywords === "number" ||
    typeof sb.recruiter_visibility === "number" ||
    typeof sb.impact === "number" ||
    typeof sb.completeness === "number";
  if (!hasAny) {
    scoreBreakdownEl.hidden = true;
    scoreBreakdownEl.innerHTML = "";
    return;
  }
  scoreBreakdownEl.hidden = false;
  scoreBreakdownEl.innerHTML = `
    <h3 class="breakdown-title">Score breakdown</h3>
    ${barRow("Keywords & SEO fit", sb.keywords)}
    ${barRow("Recruiter visibility", sb.recruiter_visibility)}
    ${barRow("Impact & outcomes", sb.impact)}
    ${barRow("Completeness", sb.completeness)}
    ${
      sb.rationale
        ? `<p class="breakdown-rationale">${escapeHtml(sb.rationale)}</p>`
        : ""
    }
  `;
}

function renderHireBanner(review) {
  if (!hireProbBanner) return;
  const rp = review.recruiter_pov;
  const pct =
    rp && typeof rp.hire_probability_percent === "number"
      ? rp.hire_probability_percent
      : null;
  const reason = rp && rp.hire_probability_reason ? String(rp.hire_probability_reason) : "";
  if (pct == null && !reason) {
    hireProbBanner.hidden = true;
    hireProbBanner.innerHTML = "";
    return;
  }
  hireProbBanner.hidden = false;
  hireProbBanner.innerHTML = `
    <div class="hire-prob-inner">
      <span class="hire-prob-label">Recruiter hire probability</span>
      <span class="hire-prob-value">${pct != null ? escapeHtml(String(pct)) + "%" : "—"}</span>
    </div>
    ${reason ? `<p class="hire-prob-reason">${escapeHtml(reason)}</p>` : ""}
  `;
}

function renderReview(review) {
  const hasNumericScore = typeof review.score === "number";
  scoreEl.textContent = hasNumericScore ? String(review.score) : "—";

  if (scoreEl) {
    scoreEl.classList.remove(
      "score-excellent",
      "score-good",
      "score-average",
      "score-weak",
      "score-poor"
    );
    if (hasNumericScore) {
      const s = review.score;
      if (s >= 90) {
        scoreEl.classList.add("score-excellent");
      } else if (s >= 80) {
        scoreEl.classList.add("score-good");
      } else if (s >= 70) {
        scoreEl.classList.add("score-average");
      } else if (s >= 50) {
        scoreEl.classList.add("score-weak");
      } else {
        scoreEl.classList.add("score-poor");
      }
    }
  }

  renderScoreBreakdown(review);
  renderHireBanner(review);

  const fullName =
    typeof review.full_name === "string" && review.full_name.trim()
      ? review.full_name.trim()
      : "Your LinkedIn Profile";

  if (scoreActions) {
    scoreActions.hidden = !hasNumericScore;
  }

  if (hasNumericScore) {
    const scoreValue = review.score;

    if (downloadCertBtn) {
      downloadCertBtn.onclick = () => {
        const url = `/certificate?score=${encodeURIComponent(
          scoreValue
        )}&name=${encodeURIComponent(fullName)}`;
        window.open(url, "_blank");
      };
    }

    if (shareLinkedInLink) {
      const shareText = `I just scored ${scoreValue}/100 on my LinkedIn profile using this AI LinkedIn Profile Reviewer!`;
      const pageUrl = window.location.origin;
      const encodedUrl = encodeURIComponent(pageUrl);
      const encodedSummary = encodeURIComponent(shareText);

      shareLinkedInLink.href = `https://www.linkedin.com/sharing/share-offsite/?url=${encodedUrl}&mini=true&summary=${encodedSummary}`;
    }
  }

  if (scoreCard) {
    scoreCard.classList.remove("score-animate");
    void scoreCard.offsetWidth;
    scoreCard.classList.add("score-animate");
  }

  const hasConnections = typeof review.connections === "number";
  const hasFollowers = typeof review.followers === "number";

  if (profileStats) {
    if (connectionsEl) {
      connectionsEl.textContent = hasConnections
        ? String(review.connections)
        : "—";
    }
    if (followersEl) {
      followersEl.textContent = hasFollowers ? String(review.followers) : "—";
    }

    profileStats.hidden = false;
  }

  const headline = review.headline || {};
  const about = review.about || {};
  const skills = review.skills || {};
  const expList = Array.isArray(review.experience) ? review.experience : [];
  const keywords = Array.isArray(review.keywords) ? review.keywords : [];
  const rp = review.recruiter_pov || {};
  const bc = review.benchmark_comparison || {};
  const lc = review.linkedin_content || {};
  const rm = review.roadmap || {};

  const headlineBody = headline.rewrite || headline.suggestion || "";
  const aboutBody = about.rewrite || about.suggestion || "";
  const headlineWhy = headline.reason || headline.explanation || "";
  const aboutWhy = about.reason || about.explanation || "";

  const skillsMissing = Array.isArray(skills.missing)
    ? skills.missing.join(", ")
    : skills.missing
    ? String(skills.missing)
    : "Not specified";

  const strengths = Array.isArray(rp.strengths) ? rp.strengths : [];
  const redFlags = Array.isArray(rp.red_flags) ? rp.red_flags : [];

  const strengthsHtml =
    strengths.length === 0
      ? "<p class=\"muted\">No strengths listed.</p>"
      : `<ul class="reason-list">${strengths
          .map(
            (x) => `
        <li>
          <strong>${escapeHtml(x.point || "")}</strong>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const redHtml =
    redFlags.length === 0
      ? "<p class=\"muted\">No red flags flagged.</p>"
      : `<ul class="reason-list reason-list-warn">${redFlags
          .map(
            (x) => `
        <li>
          <strong>${escapeHtml(x.point || "")}</strong>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const skillGaps = Array.isArray(bc.skill_gaps) ? bc.skill_gaps : [];
  const missKw = Array.isArray(bc.missing_keywords) ? bc.missing_keywords : [];

  const skillGapsHtml =
    skillGaps.length === 0
      ? ""
      : `<h4 class="subhead">Skill gaps vs strong profiles</h4><ul class="reason-list">${skillGaps
          .map(
            (x) => `
        <li>
          <strong>${escapeHtml(x.gap || "")}</strong>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const missKwHtml =
    missKw.length === 0
      ? ""
      : `<h4 class="subhead">Missing keywords</h4><ul class="reason-list">${missKw
          .map(
            (x) => `
        <li>
          <strong>${escapeHtml(x.keyword || "")}</strong>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const postIdeas = Array.isArray(lc.post_ideas) ? lc.post_ideas : [];
  const weekly = Array.isArray(lc.weekly_plan) ? lc.weekly_plan : [];

  const postsHtml =
    postIdeas.length === 0
      ? "<p class=\"muted\">No post ideas returned.</p>"
      : `<ul class="reason-list">${postIdeas
          .map(
            (x) => `
        <li>
          <strong>${escapeHtml(x.idea || "")}</strong>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const weeklyHtml =
    weekly.length === 0
      ? "<p class=\"muted\">No weekly plan returned.</p>"
      : `<ul class="weekly-list">${weekly
          .map(
            (x) => `
        <li>
          <span class="weekly-day">${escapeHtml(x.day || "")}</span>
          <span class="weekly-task">${escapeHtml(x.task || "")}</span>
          <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
        </li>`
          )
          .join("")}</ul>`;

  const d30 = Array.isArray(rm.days_30) ? rm.days_30 : [];
  const d60 = Array.isArray(rm.days_60) ? rm.days_60 : [];
  const d90 = Array.isArray(rm.days_90) ? rm.days_90 : [];

  function roadmapCol(title, items) {
    if (!items.length)
      return `<div class="roadmap-col"><h4 class="subhead">${escapeHtml(title)}</h4><p class="muted">—</p></div>`;
    return `<div class="roadmap-col"><h4 class="subhead">${escapeHtml(title)}</h4><ul class="reason-list">${items
      .map(
        (x) => `
      <li>
        <strong>${escapeHtml(x.action || "")}</strong>
        <span class="reason-inline">${escapeHtml(x.reason || "")}</span>
      </li>`
      )
      .join("")}</ul></div>`;
  }

  const expHtml =
    expList.length === 0
      ? "<p class=\"muted\">No experience rewrites returned.</p>"
      : expList
          .map((item, idx) => {
            const body = item.rewrite || item.tips || "";
            const why = item.reason || "";
            const rid = `exp-rewrite-${idx}`;
            return `
          <div class="experience-item">
            <div class="card-header-row exp-header">
              <h4>${escapeHtml(item.role || "Role")}</h4>
              <button type="button" class="ghost-btn copy-section-btn" data-copy-id="${rid}">
                Copy rewrite
              </button>
            </div>
            <pre class="suggestion-main rewrite-block" id="${rid}">${escapeHtml(body)}</pre>
            ${
              why
                ? `<p class="suggestion-note"><strong>Why:</strong> ${escapeHtml(why)}</p>`
                : ""
            }
          </div>`;
          })
          .join("");

  const keywordsHtml =
    keywords.length === 0
      ? "<p class=\"muted\">No keywords reported.</p>"
      : `<p>${keywords.map((k) => `<span class="pill">${escapeHtml(k)}</span>`).join(" ")}</p>`;

  suggestions.innerHTML = `
    <section class="suggestion-block recruiter-block">
      <h3>Recruiter POV</h3>
      <div class="insight-grid">
        <div class="insight-card">
          <h4 class="insight-title">Strengths</h4>
          ${strengthsHtml}
        </div>
        <div class="insight-card insight-card-warn">
          <h4 class="insight-title">Red flags</h4>
          ${redHtml}
        </div>
      </div>
    </section>

    <section class="suggestion-block">
      <h3>Vs top profiles (benchmark)</h3>
      <p class="suggestion-note benchmark-intro">
        ${escapeHtml(bc.summary || "Compared to patterns from strong profiles in your target space.")}
      </p>
      ${skillGapsHtml}
      ${missKwHtml}
    </section>

    <section class="suggestion-block rewrite-block-wrap">
      <div class="card-header-row">
        <h3>Headline rewrite</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="headline">
          Copy
        </button>
      </div>
      <p class="suggestion-main" data-section-content="headline">${escapeHtml(headlineBody)}</p>
      <p class="suggestion-note">
        <strong>Why:</strong> ${escapeHtml(headlineWhy)}
      </p>
    </section>

    <section class="suggestion-block rewrite-block-wrap">
      <div class="card-header-row">
        <h3>About rewrite</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="about">
          Copy
        </button>
      </div>
      <p class="suggestion-main rewrite-multiline" data-section-content="about">${escapeHtml(aboutBody)}</p>
      <p class="suggestion-note">
        <strong>Why:</strong> ${escapeHtml(aboutWhy)}
      </p>
    </section>

    <section class="suggestion-block">
      <div class="card-header-row">
        <h3>Experience rewrites</h3>
      </div>
      ${expHtml}
    </section>

    <section class="suggestion-block">
      <h3>Skills</h3>
      <p><strong>Missing / gaps:</strong> ${escapeHtml(skillsMissing)}</p>
      <p><strong>Notes:</strong> ${escapeHtml(skills.notes || "")}</p>
    </section>

    <section class="suggestion-block">
      <h3>Keywords to reinforce</h3>
      ${keywordsHtml}
    </section>

    <section class="suggestion-block posts-card">
      <h3>LinkedIn content</h3>
      <h4 class="subhead">Post ideas</h4>
      ${postsHtml}
      <h4 class="subhead">Weekly plan</h4>
      ${weeklyHtml}
    </section>

    <section class="suggestion-block roadmap-block">
      <h3>Career roadmap</h3>
      <div class="roadmap-grid">
        ${roadmapCol("First 30 days", d30)}
        ${roadmapCol("31–60 days", d60)}
        ${roadmapCol("61–90 days", d90)}
      </div>
    </section>

    <section class="suggestion-block">
      <div class="card-header-row">
        <h3>Executive summary</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="summary">
          Copy
        </button>
      </div>
      <p class="suggestion-main" data-section-content="summary">
        ${escapeHtml(review.summary || "")}
      </p>
    </section>
  `;
}

suggestions.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (!target.classList.contains("copy-section-btn")) return;

  const copyId = target.getAttribute("data-copy-id");
  if (copyId) {
    const el = document.getElementById(copyId);
    const text = el ? el.textContent || "" : "";
    await copyWithFeedback(target, text);
    return;
  }

  const sectionKey = target.getAttribute("data-section");
  if (!sectionKey) return;

  const contentEl = suggestions.querySelector(
    `[data-section-content="${sectionKey}"]`
  );
  if (!contentEl) return;

  const text = contentEl.textContent || "";
  await copyWithFeedback(target, text);
});

async function copyWithFeedback(button, text) {
  if (!text.trim()) return;
  try {
    await navigator.clipboard.writeText(text.trim());
    const original = button.textContent;
    button.textContent = "Copied!";
    setTimeout(() => {
      button.textContent = original || "Copy";
    }, 1300);
  } catch {
    showError("Could not copy text to clipboard.");
  }
}

function showError(message) {
  if (!errorBox) return;
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  if (!errorBox) return;
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function escapeHtml(text) {
  if (!text) return "";
  return text.replace(/[&<>"']/g, function (c) {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c];
  });
}

if (introLoader) {
  window.addEventListener("load", () => {
    setTimeout(() => {
      introLoader.classList.add("hidden");
    }, 2400);
  });
}

bindFileDropEffects();
bindBackToTop();
