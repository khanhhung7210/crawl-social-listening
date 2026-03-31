async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function setupShellInteractions() {
  const shell = document.querySelector(".shell");
  const railToggle = document.getElementById("rail-toggle");
  const mobileRailToggle = document.getElementById("mobile-rail-toggle");

  railToggle?.addEventListener("click", () => {
    shell.classList.toggle("rail-collapsed");
  });

  mobileRailToggle?.addEventListener("click", () => {
    shell.classList.toggle("rail-open");
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1280) {
      shell.classList.remove("rail-open");
    }
  });
}

function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN").format(Number(value || 0));
}

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMetricCards(report) {
  const metrics = [
    { label: "Total buzz", value: report.totals.mentions, sub: `${formatNumber(report.totals.sources)} nguồn` },
    { label: "Posts analyzed", value: report.totals.posts, sub: `${formatNumber(report.totals.comments)} comments` },
    { label: "Positive ratio", value: formatPercent(report.sentiment_overview.positive_ratio), sub: `${formatNumber(report.sentiment_overview.positive)} positive` },
    { label: "Negative ratio", value: formatPercent(report.sentiment_overview.negative_ratio), sub: `${formatNumber(report.sentiment_overview.negative)} negative` },
  ];
  document.getElementById("metrics-grid").innerHTML = metrics.map((item) => `
    <article class="metric-card">
      <div class="metric-label">${escapeHtml(item.label)}</div>
      <div class="metric-value">${escapeHtml(item.value)}</div>
      <div class="metric-sub">${escapeHtml(item.sub)}</div>
    </article>
  `).join("");
}

function renderDonut(containerId, rows, labelKey, valueKey, totalLabel) {
  const palette = ["#1f4ca8", "#5d88d8", "#8bb9f3", "#cadcf9", "#dce7fb"];
  const total = rows.reduce((sum, row) => sum + Number(row[valueKey] || 0), 0);
  let current = 0;
  const segments = rows.map((row, index) => {
    const value = Number(row[valueKey] || 0);
    const start = (current / Math.max(total, 1)) * 360;
    current += value;
    const end = (current / Math.max(total, 1)) * 360;
    return `${palette[index % palette.length]} ${start}deg ${end}deg`;
  });

  document.getElementById(containerId).innerHTML = `
    <div class="donut-layout">
      <div class="donut" style="--segments:${segments.join(",")};">
        <div class="donut-center">
          <div>
            <strong>${formatNumber(total)}</strong>
            <span>${escapeHtml(totalLabel)}</span>
          </div>
        </div>
      </div>
      <div class="legend">
        ${rows.map((row, index) => `
          <div class="legend-row">
            <span class="swatch" style="background:${palette[index % palette.length]}"></span>
            <span>${escapeHtml(row[labelKey])}</span>
            <span>${formatPercent(row.ratio)}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderBarList(containerId, rows, labelKey, valueKey) {
  if (!rows.length) {
    document.getElementById(containerId).innerHTML = `
      <div class="empty-state"><div><strong>No sources</strong><span>Chưa có nguồn nào cho phim này.</span></div></div>
    `;
    return;
  }
  const maxValue = Math.max(...rows.map((row) => Number(row[valueKey] || 0)), 1);
  document.getElementById(containerId).innerHTML = `
    <div class="bar-list">
      ${rows.map((row) => {
        const value = Number(row[valueKey] || 0);
        const width = (value / maxValue) * 100;
        return `
          <div class="bar-row">
            <div class="bar-label" title="${escapeHtml(row[labelKey])}">${escapeHtml(row[labelKey])}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
            <div class="bar-value">${formatNumber(value)}</div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderTable(containerId, columns, rows) {
  const content = rows.length ? `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              ${columns.map((column) => `<td>${column.render ? column.render(row[column.key], row) : escapeHtml(row[column.key])}</td>`).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  ` : `<div class="empty-state"><div><strong>No data</strong><span>Chưa có dữ liệu cho phần này.</span></div></div>`;
  document.getElementById(containerId).innerHTML = content;
}

function renderFeedbackList(containerId, rows, tone) {
  const content = rows.length ? `
    <div class="feedback-list">
      ${rows.map((row) => `
        <div class="feedback-item">
          <div>${escapeHtml(row.text)}</div>
          <div class="feedback-meta ${tone === "positive" ? "text-positive" : "text-negative"}">
            ${escapeHtml(row.platform)} • ${escapeHtml(row.source)} • ${escapeHtml(row.topic)}
          </div>
        </div>
      `).join("")}
    </div>
  ` : `<div class="empty-state"><div><strong>No comments</strong><span>Chưa có comment phù hợp cho phần này.</span></div></div>`;
  document.getElementById(containerId).innerHTML = content;
}

function renderRuleList(containerId, items) {
  document.getElementById(containerId).innerHTML = `
    <div class="rule-list">
      ${items.map((item, index) => `
        <div class="rule-item">
          <strong>${index + 1}.</strong> ${escapeHtml(item)}
        </div>
      `).join("")}
    </div>
  `;
}

function hydrate(report) {
  document.getElementById("page-title").textContent = report.film_title || "No film data in database";
  document.getElementById("media-total").textContent = `${formatNumber(report.totals.sources)} sources`;
  document.getElementById("platform-total").textContent = `${formatNumber(report.totals.posts)} posts`;
  document.getElementById("hero-tags").innerHTML = `
    <span class="tag">Generated ${escapeHtml(new Date(report.generated_at).toLocaleString("vi-VN"))}</span>
    <span class="tag tag-muted">${formatNumber(report.totals.posts)} posts</span>
    <span class="tag tag-muted">${formatNumber(report.totals.comments)} comments</span>
    <span class="tag tag-muted">${formatNumber(report.totals.sources)} sources</span>
  `;

  renderMetricCards(report);
  renderDonut("media-type-card", report.media_type_breakdown, "type", "count", "sources");
  renderDonut("platform-share-card", report.platform_share, "platform", "count", "posts");
  renderBarList("top-sources-card", report.top_sources, "source", "buzz_volume");

  renderTable("platform-table", [
    { key: "platform", label: "Platform" },
    { key: "posts", label: "Posts", render: (value) => formatNumber(value) },
    { key: "total_comments", label: "Comments", render: (value) => formatNumber(value) },
    { key: "positive_ratio", label: "Positive", render: (value) => formatPercent(value) },
    { key: "negative_ratio", label: "Negative", render: (value) => formatPercent(value) },
    { key: "buzz_score", label: "Buzz", render: (value) => formatPercent(value) },
  ], report.platform_breakdown);

  renderDonut("sentiment-card", [
    { label: "Positive", count: report.sentiment_overview.positive, ratio: report.sentiment_overview.positive_ratio },
    { label: "Negative", count: report.sentiment_overview.negative, ratio: report.sentiment_overview.negative_ratio },
    { label: "Neutral", count: report.sentiment_overview.neutral, ratio: report.sentiment_overview.neutral_ratio },
  ], "label", "count", "comments");

  renderTable("topic-table", [
    { key: "topic", label: "Topic" },
    { key: "positive", label: "Positive", render: (value) => `<span class="text-positive">${formatNumber(value)}</span>` },
    { key: "negative", label: "Negative", render: (value) => `<span class="text-negative">${formatNumber(value)}</span>` },
    { key: "neutral", label: "Neutral", render: (value) => formatNumber(value) },
    { key: "total", label: "Total", render: (value) => formatNumber(value) },
  ], report.sentiment_by_topic);

  renderFeedbackList("positive-feedback", report.feedback_examples.positive || [], "positive");
  renderFeedbackList("negative-feedback", report.feedback_examples.negative || [], "negative");
  renderRuleList("positive-rules", report.methodology.positive_rules || []);
  renderRuleList("negative-rules", report.methodology.negative_rules || []);

  if (report.warning) {
    document.getElementById("metrics-grid").insertAdjacentHTML("afterbegin", `
      <article class="metric-card metric-warning">
        <div class="metric-label">Database status</div>
        <div class="metric-sub">${escapeHtml(report.warning)}</div>
      </article>
    `);
  }
}

async function populateFilms(selectedFilm) {
  const payload = await fetchJson("/api/films");
  const select = document.getElementById("film-title");
  const films = payload.films || [];
  if (!films.length) {
    select.innerHTML = `<option value="">No films found in DB</option>`;
    select.disabled = true;
    return;
  }
  select.disabled = false;
  select.innerHTML = films.map((film) => `
    <option value="${escapeHtml(film)}">${escapeHtml(film)}</option>
  `).join("");
  if (selectedFilm && films.includes(selectedFilm)) {
    select.value = selectedFilm;
  }
}

async function loadReport(filmTitle) {
  const refreshButton = document.getElementById("refresh-button");
  refreshButton.disabled = true;
  const query = filmTitle ? `?film_title=${encodeURIComponent(filmTitle)}` : "";
  try {
    const report = await fetchJson(`/api/report${query}`);
    hydrate(report);
    return report;
  } finally {
    refreshButton.disabled = false;
  }
}

async function bootstrap() {
  setupShellInteractions();
  const params = new URLSearchParams(window.location.search);
  const currentFilm = params.get("film_title") || "";
  await populateFilms(currentFilm);
  const initialFilm = document.getElementById("film-title").value || currentFilm;
  await loadReport(initialFilm);

  document.getElementById("filter-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const filmTitle = document.getElementById("film-title").value;
    const nextUrl = filmTitle ? `?film_title=${encodeURIComponent(filmTitle)}` : window.location.pathname;
    window.history.replaceState({}, "", nextUrl);
    await loadReport(filmTitle);
  });

  document.getElementById("film-title").addEventListener("change", async (event) => {
    const filmTitle = event.target.value;
    const nextUrl = filmTitle ? `?film_title=${encodeURIComponent(filmTitle)}` : window.location.pathname;
    window.history.replaceState({}, "", nextUrl);
    await loadReport(filmTitle);
    document.querySelector(".shell")?.classList.remove("rail-open");
  });

  if (window.innerWidth >= 1280) {
    document.querySelector(".shell")?.classList.add("rail-collapsed");
  }
}

bootstrap().catch((error) => {
  document.getElementById("page-title").textContent = "Failed to load report";
  document.getElementById("metrics-grid").innerHTML = `<div class="metric-card">${escapeHtml(error.message)}</div>`;
});
