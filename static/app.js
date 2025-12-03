const form = document.getElementById("uploadForm");
const scoreEl = document.getElementById("score");
const suggestions = document.getElementById("suggestions");
const loading = document.getElementById("loading");
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


form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("pdf");
  const targetRoleInput = document.getElementById("target_role");

  clearError();

  if (!fileInput.files.length) {
    showError("Please select a LinkedIn PDF file.");
    return;
  }

  loading.hidden = false;
  result.hidden = true;

  const formData = new FormData();
  formData.append("pdf", fileInput.files[0]);
  formData.append("target_role", targetRoleInput.value || "");

  try {
    const res = await fetch("/review", {
      method: "POST",
      body: formData,
    });

    let data;
    try {
      data = await res.json();
    } catch {
      throw { error: "Server returned an invalid response." };
    }

    if (!res.ok) {
      const msg =
        data && data.error
          ? `${data.error}${
              data.details ? ` – ${String(data.details).slice(0, 300)}` : ""
            }`
          : "Review failed. Please try again.";
      throw new Error(msg);
    }

    const review = data.review;
    renderReview(review);
    result.hidden = false;
  } catch (err) {
    console.error(err);
    const message =
      err instanceof Error ? err.message : "Failed to get review.";
    showError(message);
  } finally {
    loading.hidden = true;
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
      
    }
  });
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

  const skillsMissing = Array.isArray(skills.missing)
    ? skills.missing.join(", ")
    : skills.missing
    ? String(skills.missing)
    : "Not specified";

  const expHtml =
    expList.length === 0
      ? "<p>No specific experience suggestions returned.</p>"
      : expList
          .map(
            (item) => `
          <div class="experience-item">
            <h4>${escapeHtml(item.role || "Role")}</h4>
            <p>${escapeHtml(item.tips || "")}</p>
          </div>
        `
          )
          .join("");

  const keywordsHtml =
    keywords.length === 0
      ? "<p>No keywords reported.</p>"
      : `<p>${keywords.map((k) => `<span class="pill">${escapeHtml(k)}</span>`).join(" ")}</p>`;

  suggestions.innerHTML = `
    <section class="suggestion-block">
      <div class="card-header-row">
        <h3>Headline</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="headline">
          Copy text
        </button>
      </div>
      <p class="suggestion-main" data-section-content="headline">
        ${escapeHtml(headline.suggestion || "")}
      </p>
      <p class="suggestion-note">
        <strong>Why:</strong> ${escapeHtml(headline.explanation || "")}
      </p>
    </section>

    <section class="suggestion-block">
      <div class="card-header-row">
        <h3>About section</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="about">
          Copy text
        </button>
      </div>
      <p class="suggestion-main" data-section-content="about">
        ${escapeHtml(about.suggestion || "")}
      </p>
      <p class="suggestion-note">
        <strong>Why:</strong> ${escapeHtml(about.explanation || "")}
      </p>
    </section>

    <section class="suggestion-block">
      <h3>Experience</h3>
      ${expHtml}
    </section>

    <section class="suggestion-block">
      <h3>Skills</h3>
      <p><strong>Missing / gaps:</strong> ${escapeHtml(skillsMissing)}</p>
      <p><strong>Notes:</strong> ${escapeHtml(skills.notes || "")}</p>
    </section>

    <section class="suggestion-block">
      <h3>Keywords</h3>
      ${keywordsHtml}
    </section>

    <section class="suggestion-block">
      <div class="card-header-row">
        <h3>Summary</h3>
        <button type="button" class="ghost-btn copy-section-btn" data-section="summary">
          Copy text
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

  const sectionKey = target.getAttribute("data-section");
  if (!sectionKey) return;

  const contentEl = suggestions.querySelector(
    `[data-section-content="${sectionKey}"]`
  );
  if (!contentEl) return;

  const text = contentEl.textContent || "";
  if (!text.trim()) return;

  try {
    await navigator.clipboard.writeText(text.trim());
    const original = target.textContent;
    target.textContent = "Copied!";
    setTimeout(() => {
      target.textContent = original || "Copy text";
    }, 1300);
  } catch {
    showError("Could not copy text to clipboard.");
  }
});

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
  return text.replace(/[&<>\"']/g, function (c) {
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