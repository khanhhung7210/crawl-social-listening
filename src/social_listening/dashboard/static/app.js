let REPORT = null;
let CURRENT_SCREEN = "overview";
let GLOBAL_QUERY = "";
let FEED_QUERY = "";
let CURRENT_THEME = "default";
let CURRENT_LANGUAGE = "vi";
let CURRENT_VIEW = "all";
let CURRENT_SCOPE = "brand";
let CURRENT_BRANCH = "all";
let SOURCE_CONFIG = { completed: false, sources: [] };

const SOURCE_PLATFORM_OPTIONS = [
  ["facebook", "Facebook"],
  ["tiktok", "TikTok"],
  ["instagram", "Instagram"],
  ["threads", "Threads"],
  ["google_maps", "Google Maps"],
  ["youtube", "YouTube"],
  ["grabfood", "GrabFood"],
  ["shopeefood", "ShopeeFood"],
];

const SOURCE_TYPE_OPTIONS = [
  ["official_brand", "Official brand"],
  ["store_branch", "Store / branch"],
  ["community_source", "Community source"],
  ["competitor", "Competitor"],
];

const SOURCE_PRIORITY_OPTIONS = [
  ["core", "Core"],
  ["secondary", "Secondary"],
  ["reference_only", "Reference only"],
];

const UI_COPY = {
  vi: {
    brandSubtitle: "Tập trung 5 screen thật sắc, dễ bán, không overpromise. Mọi insight/action đều phải có evidence có thể bấm mở link gốc.",
    noteTitle: "Nguyên tắc mới:",
    noteCopy: "1 module = 1 insight chính + 1 chart đúng vấn đề + diễn giải + suggested action.<br><br>Bản này đọc dữ liệu thật từ PostgreSQL và bẻ thành 5 screen theo mockup.",
    themeTitle: "Theme & Color Palette",
    themeCopy: "Chọn theme để xem dashboard theo nhiều mood: sales demo, crisis war room, executive report, premium brand.",
    brandLogoTitle: "ADD BRAND LOGO",
    brandSkinTitle: "Client Brand Skin",
    feedTitle: "Priority Action Detail",
    feedCopy: "Mỗi signal được trình bày gọn, đẹp và đúng hierarchy: việc gì xảy ra, vì sao quan trọng, ai xử lý, và bằng chứng nằm ở đâu.",
    searchPlaceholder: "⌕ Search pain, evidence, owner, CTA...",
    tableFilterPlaceholder: "Filter feed...",
    accountPrefix: "PostgreSQL",
    branches: "chi nhánh",
    marketingView: "Marketing View",
    allView: "All View",
    screenSubtitles: {
      overview: "Business Pain & Growth Radar - nhìn 5 giây biết vấn đề chính",
      listen: "Khách đang nói gì - pain, demand, positive theme",
      brand: "Điểm mạnh / điểm yếu của thương hiệu và ý nghĩa kinh doanh",
      reputation: "Review, rating, crisis, social proof",
      competitor: "Đối thủ đang hút khách bằng gì và Dotn nên phản ứng ra sao",
    },
  },
  en: {
    brandSubtitle: "Five sharp screens built for selling, without overpromising. Every insight and action must be backed by clickable evidence.",
    noteTitle: "New principle:",
    noteCopy: "1 module = 1 core insight + 1 issue-fit chart + interpretation + suggested action.<br><br>This version reads real PostgreSQL data and restructures it into 5 screens following the mockup.",
    themeTitle: "Theme & Color Palette",
    themeCopy: "Choose a theme to view the dashboard in different moods: sales demo, crisis war room, executive report, premium brand.",
    brandLogoTitle: "ADD BRAND LOGO",
    brandSkinTitle: "Client Brand Skin",
    feedTitle: "Priority Action Detail",
    feedCopy: "Each signal is presented with clean hierarchy: what happened, why it matters, who owns it, and where the proof lives.",
    searchPlaceholder: "⌕ Search pain, evidence, owner, CTA...",
    tableFilterPlaceholder: "Filter feed...",
    accountPrefix: "PostgreSQL",
    branches: "branches",
    marketingView: "Marketing View",
    allView: "All View",
    screenSubtitles: {
      overview: "Business Pain & Growth Radar - grasp the key issue in 5 seconds",
      listen: "What customers are saying - pain, demand, positive themes",
      brand: "Brand strengths / weaknesses and their business meaning",
      reputation: "Reviews, ratings, crisis, social proof",
      competitor: "What competitors are winning on and how Dotn should respond",
    },
  },
};

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json();
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("vi-VN");
}

function severityClass(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "high") return "high";
  if (normalized === "medium") return "medium";
  return "low";
}

function renderNav(report) {
  const copy = UI_COPY[CURRENT_LANGUAGE] || UI_COPY.vi;
  const screens = report.screens || {};
  const order = [
    ["overview", "0"],
    ["listen", "1"],
    ["brand", "2"],
    ["reputation", "3"],
    ["competitor", "4"],
  ];
  document.getElementById("nav").innerHTML = order.map(([key, number]) => {
    const screen = screens[key];
    if (!screen) return "";
    return `
      <button class="navBtn ${CURRENT_SCREEN === key ? "active" : ""}" type="button" data-screen="${escapeHtml(key)}">
        <span class="num ${navColor(number)}">${escapeHtml(number)}</span>
        <span>
          <b>${escapeHtml(screen.title)}</b>
          <span>${escapeHtml(copy.screenSubtitles[key] || screen.subtitle)}</span>
        </span>
      </button>
    `;
  }).join("");
  document.querySelectorAll(".navBtn[data-screen]").forEach((button) => {
    button.addEventListener("click", () => {
      CURRENT_SCREEN = button.dataset.screen;
      render();
    });
  });
}

function navColor(number) {
  if (number === "0" || number === "1" || number === "2") return "green";
  if (number === "3") return "red";
  return "purple";
}

function normalizeQuickCard(card) {
  if (!card || typeof card !== "object") return null;
  return {
    tag: card.tag || "",
    title: card.title || "",
    value: card.value || "",
    desc: card.desc || "",
    sev: card.severity || card.sev || "low",
    owner: card.owner || "",
    guardrail: card.guardrail || "",
    evidence_query: card.evidence_query || card.title || card.tag || "",
    cta_label: card.cta_label || (CURRENT_LANGUAGE === "en" ? "View evidence" : "Xem bằng chứng"),
  };
}

function simpleListModule(title, takeaway, rows, evidenceQuery) {
  return {
    title,
    takeaway,
    evidence_query: evidenceQuery || title,
    chart: "list",
    data: rows,
    analysis: [],
    action: { guardrail: "", owner: "", cta: "" },
  };
}

function synthesizeLegacyScreens(report) {
  const topCards = (report.overview?.top_cards || [])
    .map(normalizeQuickCard)
    .filter(Boolean);

  const platformRows = (report.platform_summary || []).map((row) => [
    row.platform || "",
    `${row.relevant_count || 0}/${row.mention_count || 0} relevant`,
    `Status: ${row.status || "unknown"}`,
  ]);

  const branchRows = (report.branches || []).map((row) => [
    row.branch_name || row.branch_slug || "",
    row.status || "mapped",
    [row.address_line, row.district, row.city].filter(Boolean).join(", "),
  ]);

  const evidenceRows = (report.evidence_cards || []).map((row) => [
    row.metric_label || row.platform || "",
    row.sentiment_label || "",
    row.evidence_quote || "",
  ]);

  const menuRows = (report.menu_highlights || []).slice(0, 8).map((row) => [
    row.item_name || "",
    row.branch_name || row.platform || "",
    row.price_label || row.price || "",
  ]);

  const feed = (report.mentions_feed || []).map((row) => ({
    title: row.title || row.metric_label || row.platform || "",
    platform: row.platform || "",
    severity: row.severity || row.sentiment_label || "Low",
    metric: row.metric || row.metric_label || "",
    owner: row.owner || "",
    status: row.status || "",
    summary: row.summary || row.evidence_quote || row.desc || "",
    source_url: row.source_url || row.url || "",
  }));

  const baseOverview = {
    title: "Overview",
    subtitle: "Business Pain & Growth Radar",
    headline: report.overview?.headline || "",
    topCards,
    modules: [
      simpleListModule("Platform Readiness", "Nguồn nào đang usable ngay và nguồn nào còn noisy.", platformRows, "Platform Readiness"),
      simpleListModule("Branch Coverage", "Bức tranh branch/store hiện có trong DB.", branchRows, "Branch Coverage"),
      simpleListModule("Evidence Snapshot", "Các bằng chứng hiện có trong payload fallback.", evidenceRows, "Evidence Snapshot"),
      simpleListModule("Menu Snapshot", "Menu/store metadata đã có thể dùng cho dashboard.", menuRows, "Menu Snapshot"),
    ],
    feed,
  };

  return {
    overview: baseOverview,
    listen: {
      title: "Dotn Listen",
      subtitle: "What customers are saying",
      headline: report.overview?.headline || "",
      topCards,
      modules: [
        simpleListModule("Signal Feed", "Nguồn tín hiệu đang đổ vào dashboard.", evidenceRows, "Signal Feed"),
        simpleListModule("Platform Readiness", "Tỷ lệ usable của từng platform.", platformRows, "Platform Readiness"),
      ],
      feed,
    },
    brand: {
      title: "Brand Health",
      subtitle: "Brand strengths and weaknesses",
      headline: report.overview?.headline || "",
      topCards,
      modules: [
        simpleListModule("Branch Coverage", "Coverage hiện có theo branch.", branchRows, "Branch Coverage"),
        simpleListModule("Menu Snapshot", "Menu/store metadata theo brand.", menuRows, "Menu Snapshot"),
      ],
      feed,
    },
    reputation: {
      title: "Reputation",
      subtitle: "Reviews, ratings, social proof",
      headline: report.overview?.headline || "",
      topCards,
      modules: [
        simpleListModule("Evidence Snapshot", "Review/evidence hiện có.", evidenceRows, "Evidence Snapshot"),
        simpleListModule("Branch Coverage", "Branch nào đang có pressure nhiều hơn.", branchRows, "Branch Coverage"),
      ],
      feed,
    },
    competitor: {
      title: "Competitor Radar",
      subtitle: "Competitive response",
      headline: report.overview?.headline || "",
      topCards,
      modules: [
        simpleListModule("Source Snapshot", "Tạm dùng source snapshot cho competitor proxy.", platformRows, "Source Snapshot"),
        simpleListModule("Action Queue", "Các row hành động hiện có.", feed.map((row) => [row.title, row.owner, row.summary]), "Action Queue"),
      ],
      feed,
    },
  };
}

function hydrateReport(report) {
  const next = JSON.parse(JSON.stringify(report || {}));
  if (!next.screens || !Object.keys(next.screens).length) {
    next.screens = synthesizeLegacyScreens(next);
  }
  next.source_config = next.source_config || { completed: false, sources: [] };
  next.source_config_completed = Boolean(next.source_config_completed || next.source_config?.completed);
  return next;
}

function blankSourceRow() {
  return {
    platform: "facebook",
    channel_name: "",
    source_url: "",
    source_type: "official_brand",
    priority: "core",
    include_in_dashboard: true,
    crawl_enabled: true,
  };
}

function normalizeSourceRow(row) {
  return {
    platform: String(row?.platform || "facebook").trim().toLowerCase(),
    channel_name: String(row?.channel_name || "").trim(),
    source_url: String(row?.source_url || "").trim(),
    source_type: String(row?.source_type || "official_brand").trim().toLowerCase(),
    priority: String(row?.priority || "core").trim().toLowerCase(),
    include_in_dashboard: Boolean(row?.include_in_dashboard ?? true),
    crawl_enabled: Boolean(row?.crawl_enabled ?? true),
    metadata: row?.metadata && typeof row.metadata === "object" ? row.metadata : {},
  };
}

function buildOptionMarkup(options, selectedValue) {
  return options.map(([value, label]) => `
    <option value="${escapeHtml(value)}" ${selectedValue === value ? "selected" : ""}>${escapeHtml(label)}</option>
  `).join("");
}

function syncSourceConfigBrand() {
  const brandName = REPORT?.brand?.brand_name || "Brand";
  document.getElementById("source-config-brand").textContent = brandName;
}

function renderSourceConfigRows() {
  const rows = Array.isArray(SOURCE_CONFIG.sources) && SOURCE_CONFIG.sources.length
    ? SOURCE_CONFIG.sources
    : [blankSourceRow()];
  SOURCE_CONFIG.sources = rows.map(normalizeSourceRow);
  document.getElementById("sourceConfigRows").innerHTML = SOURCE_CONFIG.sources.map((row, index) => `
    <div class="sourceConfigRow" data-row-index="${index}">
      <select data-field="platform">${buildOptionMarkup(SOURCE_PLATFORM_OPTIONS, row.platform)}</select>
      <input data-field="channel_name" type="text" value="${escapeHtml(row.channel_name)}" placeholder="Meili Official / Branch name">
      <input data-field="source_url" type="text" value="${escapeHtml(row.source_url)}" placeholder="https://...">
      <select data-field="source_type">${buildOptionMarkup(SOURCE_TYPE_OPTIONS, row.source_type)}</select>
      <select data-field="priority">${buildOptionMarkup(SOURCE_PRIORITY_OPTIONS, row.priority)}</select>
      <label class="sourceCheck"><input data-field="include_in_dashboard" type="checkbox" ${row.include_in_dashboard ? "checked" : ""}></label>
      <label class="sourceCheck"><input data-field="crawl_enabled" type="checkbox" ${row.crawl_enabled ? "checked" : ""}></label>
      <button class="sourceRemoveBtn" type="button" data-remove-row="${index}">×</button>
    </div>
  `).join("");
  document.querySelectorAll("[data-remove-row]").forEach((button) => {
    button.addEventListener("click", () => {
      SOURCE_CONFIG.sources.splice(Number(button.dataset.removeRow || "0"), 1);
      renderSourceConfigRows();
    });
  });
}

function collectSourceConfigRows() {
  const rows = [];
  document.querySelectorAll(".sourceConfigRow[data-row-index]").forEach((rowNode) => {
    rows.push(normalizeSourceRow({
      platform: rowNode.querySelector('[data-field="platform"]')?.value,
      channel_name: rowNode.querySelector('[data-field="channel_name"]')?.value,
      source_url: rowNode.querySelector('[data-field="source_url"]')?.value,
      source_type: rowNode.querySelector('[data-field="source_type"]')?.value,
      priority: rowNode.querySelector('[data-field="priority"]')?.value,
      include_in_dashboard: rowNode.querySelector('[data-field="include_in_dashboard"]')?.checked,
      crawl_enabled: rowNode.querySelector('[data-field="crawl_enabled"]')?.checked,
    }));
  });
  return rows.filter((row) => row.source_url);
}

function setSourceConfigError(message) {
  const target = document.getElementById("sourceConfigError");
  if (!message) {
    target.textContent = "";
    target.classList.add("hidden");
    return;
  }
  target.textContent = message;
  target.classList.remove("hidden");
}

function showSourceConfigOverlay() {
  syncSourceConfigBrand();
  renderSourceConfigRows();
  setSourceConfigError("");
  document.getElementById("sourceConfigOverlay").classList.remove("hidden");
}

function hideSourceConfigOverlay() {
  document.getElementById("sourceConfigOverlay").classList.add("hidden");
}

async function ensureSourceConfigLoaded() {
  if (REPORT?.source_config) {
    SOURCE_CONFIG = {
      completed: Boolean(REPORT.source_config_completed || REPORT.source_config?.completed),
      sources: Array.isArray(REPORT.source_config?.sources) ? REPORT.source_config.sources.map(normalizeSourceRow) : [],
    };
    return;
  }
  const payload = await fetchJson("/api/source-config");
  SOURCE_CONFIG = {
    completed: Boolean(payload?.completed),
    sources: Array.isArray(payload?.sources) ? payload.sources.map(normalizeSourceRow) : [],
  };
}

async function saveSourceConfig() {
  const rows = collectSourceConfigRows();
  if (!rows.length) {
    setSourceConfigError("Cần ít nhất 1 source có URL trước khi tiếp tục.");
    return;
  }
  const hasCoreSource = rows.some((row) => row.include_in_dashboard && row.crawl_enabled);
  if (!hasCoreSource) {
    setSourceConfigError("Cần ít nhất 1 source được bật cho dashboard và crawl.");
    return;
  }
  setSourceConfigError("");
  const saved = await postJson("/api/source-config", { sources: rows });
  SOURCE_CONFIG = {
    completed: Boolean(saved?.completed),
    sources: Array.isArray(saved?.sources) ? saved.sources.map(normalizeSourceRow) : rows,
  };
  if (REPORT) {
    REPORT.source_config_completed = SOURCE_CONFIG.completed;
    REPORT.source_config = SOURCE_CONFIG;
  }
  hideSourceConfigOverlay();
}

function renderQuick(cards) {
  document.getElementById("quick").innerHTML = (cards || []).map((card) => `
    <article class="qcard ${severityClass(card.sev || card.severity)}">
      <div class="qtop">
        <small>${escapeHtml(card.tag || "")}</small>
        <div class="qval">${escapeHtml(card.value || "")}</div>
      </div>
      <h3>${escapeHtml(card.title || "")}</h3>
      <p>${escapeHtml(card.desc || "")}</p>
      <button
        class="evidenceBtn"
        type="button"
        data-evidence-query="${escapeHtml(card.evidence_query || card.title || card.tag || "")}"
        data-evidence-kind="${escapeHtml(card.evidence_kind || "")}"
        data-evidence-branch="${escapeHtml(card.evidence_branch || "")}"
        data-evidence-platform="${escapeHtml(card.evidence_platform || "")}"
      >${escapeHtml(card.cta_label || (CURRENT_LANGUAGE === "en" ? "View evidence" : "Xem bằng chứng"))}</button>
      <div class="qcta">${escapeHtml(card.owner || "")} · ${escapeHtml(card.guardrail || "")}</div>
    </article>
  `).join("");
  document.querySelectorAll(".evidenceBtn[data-evidence-query]").forEach((button) => {
    button.addEventListener("click", () => {
      renderEvidencePanel(
        buildEvidencePayload({
          query: String(button.dataset.evidenceQuery || "").trim(),
          kind: String(button.dataset.evidenceKind || "").trim(),
          branch: String(button.dataset.evidenceBranch || "").trim(),
          platform: String(button.dataset.evidencePlatform || "").trim(),
        }),
      );
    });
  });
}

function matchesQuery(value, query) {
  return String(value || "").toLowerCase().includes(String(query || "").toLowerCase().trim());
}

function filterModules(modules) {
  if (!GLOBAL_QUERY) return modules || [];
  return (modules || []).filter((module) => {
    const haystack = [
      module.title,
      module.takeaway,
      ...(module.analysis || []),
      module.action?.guardrail,
      module.action?.owner,
      module.action?.cta,
      JSON.stringify(module.data || ""),
    ].join(" ");
    return matchesQuery(haystack, GLOBAL_QUERY);
  });
}

function filterFeed(rows) {
  if (!FEED_QUERY && !GLOBAL_QUERY) return rows || [];
  const query = FEED_QUERY || GLOBAL_QUERY;
  return (rows || []).filter((row) => {
    const haystack = [
      row.title,
      row.platform,
      row.metric,
      row.owner,
      row.status,
      row.summary,
    ].join(" ");
    return matchesQuery(haystack, query);
  });
}

function buildEvidencePayload(input) {
  const query = typeof input === "string" ? input : String(input?.query || "").trim();
  const kind = typeof input === "object" && input ? String(input.kind || "").trim() : "";
  const branch = typeof input === "object" && input ? String(input.branch || "").trim() : "";
  const platform = typeof input === "object" && input ? String(input.platform || "").trim().toLowerCase() : "";
  const searchAliases = {
    "competitive intelligence readiness": "competitive pressure radar",
    "competitor setup": "competitive pressure radar",
    "high-risk branches": "branch risk snapshot",
    "lowest rating": "review health heatmap",
    "negative evidence": "lost customer signals",
    "positive proof bank": "social proof pipeline",
    "facebook": "channel signal quality",
    "google maps": "channel signal quality",
    "tín hiệu f&b đã qua relevance": "qualified signal summary",
    "social volume đang kéo bởi facebook": "signal source mix",
    "proof bank bắt đầu dùng được": "social proof pipeline",
    "queue xử lý đã có owner": "priority action detail",
  };
  const search = searchAliases[query.toLowerCase()] || query.toLowerCase();
  const evidenceCards = Array.isArray(REPORT?.evidence_cards) ? REPORT.evidence_cards : [];
  const actionRows = Array.isArray(REPORT?.mentions_feed) ? REPORT.mentions_feed : [];
  const branches = Array.isArray(REPORT?.branch_intelligence) ? REPORT.branch_intelligence : [];
  const platforms = Array.isArray(REPORT?.platform_summary) ? REPORT.platform_summary : [];
  const menus = Array.isArray(REPORT?.menu_highlights) ? REPORT.menu_highlights : [];

  const synthetic = (platformName, metric, quote, sentiment = "operational", confidence = 0.72, sourceUrl = "") => ({
    platform: platformName || "",
    metric_label: metric || "",
    evidence_quote: quote || "",
    sentiment_label: sentiment,
    confidence_score: confidence,
    evidence_date: REPORT?.generated_at || "",
    source_url: sourceUrl || "",
  });

  const fromBranch = (row, quote, sentiment = "operational", confidence = 0.76) =>
    synthetic("branch", row?.branch_name || row?.branch_slug || "branch", quote, sentiment, confidence, "");

  const fromPlatform = (row, quote, sentiment = "operational", confidence = 0.72) =>
    synthetic(row?.platform || "", row?.platform || "", quote, sentiment, confidence, "");

  let matches = evidenceCards.filter((item) => {
    const haystack = [
      item.metric_label,
      item.platform,
      item.evidence_quote,
      item.sentiment_label,
    ].join(" ").toLowerCase();
    return !search || haystack.includes(search);
  });

  if (kind === "branch_negative" && branch) {
    matches = evidenceCards.filter((item) =>
      String(item.sentiment_label || "") === "negative" &&
      String(item.metric_label || "").toLowerCase().includes(branch.toLowerCase()),
    );
  } else if (kind === "action_focus") {
    matches = actionRows
      .filter((row) => {
        const hay = [row.title, row.summary, row.metric, row.platform].join(" ").toLowerCase();
        const q = search || String(query || "").toLowerCase();
        return !q || hay.includes(q);
      })
      .slice(0, 8)
      .map((row) => synthetic(row.platform || "", row.title || "", `${row.owner || "Owner"} · ${row.summary || ""}`, String(row.severity || "").toLowerCase() === "high" ? "negative" : "operational", 0.74, row.source_url || ""));
  } else if (kind === "brand_score") {
    matches = [
      ...branches.slice(0, 4).map((row) =>
        fromBranch(row, `${row.branch_name} đang góp vào Brand Health qua rating ${row.avg_rating || 0}, positive ${row.positive_count || 0} và negative ${row.negative_count || 0}.`, "operational", 0.8),
      ),
      ...evidenceCards.slice(0, 4),
    ].slice(0, 8);
  } else if (kind === "brand_delivery_drag") {
    matches = evidenceCards
      .filter((item) => {
        const quote = String(item.evidence_quote || "").toLowerCase();
        return String(item.sentiment_label || "") === "negative" && ["giao", "ship", "delivery", "nguội", "chậm"].some((word) => quote.includes(word));
      })
      .slice(0, 8);
  } else if (kind === "brand_value_perception") {
    matches = evidenceCards
      .filter((item) => {
        const quote = String(item.evidence_quote || "").toLowerCase();
        return ["giá", "đắt", "value", "không đáng", "budget"].some((word) => quote.includes(word));
      })
      .slice(0, 8);
  } else if (kind === "brand_growth_asset") {
    matches = [
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 6),
      ...menus.slice(0, 2).map((row) =>
        synthetic(row.platform || "menu", row.item_name || "", `${row.item_name || ""} tại ${row.branch_name || ""} đang là growth asset vì nối được taste proof với món signature thật.`, "positive", 0.71),
      ),
    ].slice(0, 8);
  } else if (kind === "brand_category_rank") {
    matches = [
      ...branches.slice(0, 3).map((row) =>
        fromBranch(row, `${row.branch_name} đang đại diện cho category story qua rating ${row.avg_rating || 0} và topic ${(row.top_topics || []).join(", ") || "mixed"}.`, "operational", 0.76),
      ),
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 3),
    ];
  } else if (kind === "brand_campaign_ready") {
    matches = [
      ...menus.slice(0, 4).map((row) =>
        synthetic(row.platform || "menu", row.item_name || "", `${row.item_name || ""} ở ${row.branch_name || ""} đang có fit tốt để dùng làm campaign test / value offer dựa trên menu reality.`, "positive", 0.69),
      ),
      ...evidenceCards.slice(0, 4),
    ].slice(0, 8);
  } else if (kind === "brand_sentiment") {
    matches = evidenceCards
      .filter((item) => ["positive", "negative", "mixed"].includes(String(item.sentiment_label || "")))
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0))
      .slice(0, 8);
  } else if (kind === "brand_best_branch" && branch) {
    matches = [
      ...branches
        .filter((row) => String(row.branch_name || "").toLowerCase() === branch.toLowerCase())
        .map((row) =>
          fromBranch(row, `${row.branch_name} đang là best branch pattern với topics ${(row.top_topics || []).join(", ") || "mixed"} và rating ${row.avg_rating || 0}.`, "positive", 0.84),
        ),
      ...evidenceCards.slice(0, 4),
    ].slice(0, 8);
  } else if (kind === "reputation_high_risk") {
    matches = branches
      .filter((row) => String(row.risk_level || "").toLowerCase() === "high")
      .slice(0, 8)
      .map((row) => fromBranch(row, `${row.branch_name} đang ở high-risk với rating ${row.avg_rating || 0}, ${row.review_count || 0} reviews và ${row.negative_count || 0} tín hiệu tiêu cực.`, "negative", 0.82));
  } else if (kind === "reputation_lowest_rating" && branch) {
    matches = [
      ...branches
        .filter((row) => String(row.branch_name || "").toLowerCase() === branch.toLowerCase())
        .map((row) => fromBranch(row, `${row.branch_name} hiện là branch có rating thấp nhất với watchout: ${row.watchout || "rating pressure"}.`, "negative", 0.84)),
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "negative").slice(0, 4),
    ].slice(0, 8);
  } else if (kind === "reputation_negative_proof") {
    matches = evidenceCards.filter((item) => String(item.sentiment_label || "") === "negative").slice(0, 8);
  } else if (kind === "reputation_positive_proof") {
    matches = evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 8);
  } else if (kind === "competitor_pressure") {
    matches = [
      ...branches.slice(0, 5).map((row) => fromBranch(row, `${row.branch_name} đang có pressure proxy từ value/rating ở mức ${row.avg_rating || 0}.`, "operational", 0.71)),
      ...evidenceCards.slice(0, 3),
    ].slice(0, 8);
  } else if (kind === "competitor_review_gap") {
    matches = branches
      .filter((row) => Number(row.review_count || 0) < 5)
      .slice(0, 8)
      .map((row) => fromBranch(row, `${row.branch_name} đang thiếu review depth để benchmark cạnh tranh chính xác.`, "operational", 0.68));
  } else if (kind === "competitor_noisy") {
    matches = platforms
      .filter((row) => String(row.status || "") === "noisy")
      .map((row) => fromPlatform(row, `${row.platform} là noisy input, chưa nên dùng để diễn giải competitor pressure mạnh.`, "operational", 0.66));
  } else if (kind === "competitor_metadata") {
    matches = platforms
      .filter((row) => String(row.status || "") === "metadata_only")
      .map((row) => fromPlatform(row, `${row.platform} hiện mới ở lớp metadata-only, chỉ nên xem là proxy của delivery layer.`, "operational", 0.66));
  } else if (kind === "growth_platform" && platform) {
    matches = evidenceCards.filter((item) =>
      String(item.platform || "").toLowerCase() === platform,
    );
  } else if (kind === "positive_proof") {
    matches = evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive");
  } else if (kind === "qualified_signal") {
    matches = [...evidenceCards]
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0))
      .slice(0, 8);
  } else if (kind === "action_queue") {
    const syntheticItems = actionRows.slice(0, 8).map((row) => ({
      platform: row.platform || "",
      metric_label: row.title || "",
      evidence_quote: row.summary || "",
      sentiment_label: String(row.severity || "").toLowerCase() === "high" ? "negative" : "operational",
      confidence_score: 0.72,
      evidence_date: REPORT?.generated_at || "",
      source_url: row.source_url || "",
    }));
    matches = syntheticItems;
  } else if (kind === "source_cleanup") {
    const noisyPlatforms = (Array.isArray(REPORT?.platform_summary) ? REPORT.platform_summary : [])
      .filter((row) => ["noisy", "metadata_only", "pending_filter"].includes(String(row.status || "")))
      .map((row) => row.platform);
    const syntheticItems = noisyPlatforms.map((name) => ({
      platform: name,
      metric_label: `${name} cleanup`,
      evidence_quote: `${name} đang ở trạng thái noisy hoặc metadata_only, cần cleanup trước khi dùng cho insight mạnh.`,
      sentiment_label: "operational",
      confidence_score: 0.68,
      evidence_date: REPORT?.generated_at || "",
      source_url: "",
    }));
    matches = syntheticItems;
  } else if (search === "pain priority matrix") {
    matches = evidenceCards
      .filter((item) => String(item.sentiment_label || "") === "negative")
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0));
  } else if (search === "revenue impact estimate") {
    matches = evidenceCards
      .filter((item) => ["negative", "mixed", "operational"].includes(String(item.sentiment_label || "")))
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0));
  } else if (search === "lost customer signals") {
    const lostKeywords = ["giá", "đắt", "không đáng", "ship", "giao", "delivery", "chậm", "đợi", "nguội", "nhạt", "mặn", "thái độ", "phục vụ"];
    matches = evidenceCards
      .filter((item) => {
        const quote = String(item.evidence_quote || "").toLowerCase();
        const sentiment = String(item.sentiment_label || "");
        return sentiment === "negative" || lostKeywords.some((keyword) => quote.includes(keyword));
      })
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0));
  } else if (search === "today's action timeline") {
    matches = actionRows.slice(0, 8).map((row) => ({
      platform: row.platform || "",
      metric_label: row.title || "",
      evidence_quote: row.summary || "",
      sentiment_label: String(row.severity || "").toLowerCase() === "high" ? "negative" : "operational",
      confidence_score: 0.72,
      evidence_date: REPORT?.generated_at || "",
      source_url: row.source_url || "",
    }));
  } else if (search === "qualified signal summary") {
    const totalMentions = platforms.reduce((sum, row) => sum + Number(row.mention_count || 0), 0);
    const totalRelevant = platforms.reduce((sum, row) => sum + Number(row.relevant_count || 0), 0);
    const totalNoise = Math.max(0, totalMentions - totalRelevant);
    const rows = [
      synthetic("pipeline", "Qualified signal", `${totalRelevant}/${totalMentions || totalRelevant} record đã qua relevance filter và hiện đủ sạch để đọc insight cấp dashboard.`, "positive", 0.9),
      synthetic("pipeline", "Noise blocked", `${totalNoise} record đang bị loại khỏi qualified layer vì nhiễu, metadata-only hoặc chưa đủ fit F&B.`, totalNoise > 0 ? "operational" : "positive", 0.8),
      ...platforms.slice(0, 4).map((row) =>
        fromPlatform(
          row,
          `${row.platform} có ${row.relevant_count || 0}/${row.mention_count || 0} tín hiệu relevant, readiness ${row.readiness_score || 0} và status ${row.status || "unknown"}.`,
          ["ready", "full_ref", "delivery_mapped"].includes(String(row.status || "")) ? "positive" : "operational",
          0.74,
        ),
      ),
    ];
    matches = rows;
  } else if (search === "marketing funnel leakage") {
    const risky = branches[0];
    const topNeg = evidenceCards.find((item) => String(item.sentiment_label || "") === "negative");
    const topPos = evidenceCards.find((item) => String(item.sentiment_label || "") === "positive");
    matches = [
      topNeg,
      risky ? fromBranch(risky, `${risky.branch_name} đang kéo leakage mạnh nhất vì risk ${risky.risk_score || 0}, rating ${risky.avg_rating || 0} và ${risky.negative_count || 0} tín hiệu tiêu cực.`,"negative",0.84) : null,
      topPos ? synthetic(topPos.platform, "Awareness asset", `${topPos.metric_label || topPos.platform} đang là nguồn proof giúp giữ awareness/consideration không rơi sâu hơn.`, "positive", 0.76, topPos.source_url || "") : null,
      ...platforms.slice(0, 3).map((row) =>
        fromPlatform(row, `${row.platform} readiness ${row.readiness_score || 0} với ${row.relevant_count || 0} tín hiệu relevant đang nuôi phần trên của funnel.`, "operational", 0.7),
      ),
    ].filter(Boolean);
  } else if (search === "channel signal quality") {
    matches = platforms.map((row) =>
      fromPlatform(
        row,
        `${row.platform} có ${row.relevant_count || 0}/${row.mention_count || 0} relevant, ${row.review_count || 0} reviews, readiness ${row.readiness_score || 0} và trạng thái ${row.status || "unknown"}.`,
        ["noisy", "pending_filter", "metadata_only"].includes(String(row.status || "")) ? "operational" : "positive",
        0.75,
      ),
    );
  } else if (search === "branch risk snapshot") {
    matches = branches.slice(0, 8).map((row) =>
      fromBranch(
        row,
        `${row.branch_name} có risk ${row.risk_score || 0}, rating ${row.avg_rating || 0}, ${row.review_count || 0} reviews và top topics: ${(row.top_topics || []).join(", ") || "mixed"}.`,
        String(row.risk_level || "").toLowerCase() === "high" ? "negative" : "operational",
        0.79,
      ),
    );
  } else if (search === "brand-wide vs branch-specific issue split") {
    const brandWide = {};
    branches.forEach((row) => {
      (row.top_topics || []).forEach((topic) => {
        brandWide[topic] = (brandWide[topic] || 0) + 1;
      });
    });
    matches = Object.entries(brandWide)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([topic, count]) =>
        synthetic(
          "issue",
          topic,
          count >= 2
            ? `Issue "${topic}" đang xuất hiện ở ${count} branch, nên nên xem như brand-wide issue trước khi fix riêng lẻ.`
            : `Issue "${topic}" mới thấy ở ${count} branch, phù hợp với local branch action hơn là brand-wide reaction.`,
          count >= 2 ? "negative" : "operational",
          0.73,
        ),
      );
  } else if (search === "topic health breakdown") {
    matches = evidenceCards
      .filter((item) => ["negative", "positive"].includes(String(item.sentiment_label || "")))
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0));
  } else if (search === "demand signal trend") {
    matches = evidenceCards
      .filter((item) => {
        const quote = String(item.evidence_quote || "").toLowerCase();
        return ["muốn", "combo", "lunch", "trưa", "set", "ăn", "thử"].some((keyword) => quote.includes(keyword));
      })
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0));
  } else if (search === "trend opportunity snapshot") {
    matches = [
      ...evidenceCards.slice(0, 6),
      ...menus.slice(0, 3).map((row) =>
        synthetic(row.platform || "menu", row.item_name || "", `${row.branch_name || ""} có menu highlight ${row.item_name || ""} ở mức ${row.price_text || ""}, phù hợp để đọc như trend/proof cue hơn là raw menu item.`, "positive", 0.69),
      ),
    ].slice(0, 8);
  } else if (search === "positive theme treemap") {
    matches = evidenceCards
      .filter((item) => String(item.sentiment_label || "") === "positive")
      .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0))
      .slice(0, 8);
  } else if (search === "behavior segment funnel") {
    matches = [
      ...evidenceCards.slice(0, 4),
      ...platforms.slice(0, 4).map((row) =>
        fromPlatform(row, `${row.platform} hiện đóng góp ${row.relevant_count || 0} tín hiệu relevant cho hành vi discovery/shortlist của khách.`, "operational", 0.7),
      ),
    ].slice(0, 8);
  } else if (search === "trend opportunity radar") {
    matches = [
      ...evidenceCards.slice(0, 6),
      ...menus.slice(0, 2).map((row) => synthetic(row.platform || "menu", row.item_name || "", `${row.item_name || ""} ở ${row.branch_name || ""} đang là cue có thể biến thành trend/test nếu fit thương hiệu và sentiment đủ an toàn.`, "positive", 0.68)),
    ].slice(0, 8);
  } else if (search === "topic lifecycle tracker") {
    matches = evidenceCards.slice(0, 8);
  } else if (search === "signal source mix") {
    matches = platforms.map((row) =>
      fromPlatform(row, `${row.platform} đang chiếm ${row.relevant_count || 0} relevant signals, ${row.review_count || 0} reviews và readiness ${row.readiness_score || 0}.`, "operational", 0.74),
    );
  } else if (search === "influencer signal watch lite") {
    matches = platforms
      .filter((row) => ["tiktok", "instagram", "facebook"].includes(String(row.platform || "").toLowerCase()))
      .map((row) => fromPlatform(row, `${row.platform} là proxy social signal watch với ${row.relevant_count || 0} relevant và status ${row.status || "unknown"}.`, "operational", 0.68));
  } else if (search === "creative trigger board") {
    matches = [
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 4),
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "negative").slice(0, 4),
    ];
  } else if (search === "topic x sentiment by branch") {
    matches = branches.slice(0, 8).map((row) =>
      fromBranch(row, `${row.branch_name} có positive ${row.positive_count || 0}, negative ${row.negative_count || 0} và topic coverage ${(row.top_topics || []).join(", ") || "mixed"}.`, "operational", 0.76),
    );
  } else if (search === "priority action detail") {
    matches = actionRows.slice(0, 8).map((row) => synthetic(row.platform || "", row.title || "", `${row.owner || "Owner"} · ${row.summary || ""}`, String(row.severity || "").toLowerCase() === "high" ? "negative" : "operational", 0.72, row.source_url || ""));
  } else if (search === "score waterfall") {
    matches = [
      ...branches.slice(0, 3).map((row) =>
        fromBranch(row, `${row.branch_name} đóng góp vào score hiện tại với rating ${row.avg_rating || 0}, positive ${row.positive_count || 0} và negative ${row.negative_count || 0}.`, "operational", 0.76),
      ),
      ...evidenceCards.slice(0, 4),
    ];
  } else if (search === "component trendline") {
    matches = platforms.slice(0, 5).map((row) =>
      fromPlatform(row, `${row.platform} đang góp phần vào trend visibility/reputation/opportunity qua relevant ${row.relevant_count || 0} và reviews ${row.review_count || 0}.`, "operational", 0.72),
    );
  } else if (search === "fix / amplify matrix") {
    matches = [
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "negative").slice(0, 4),
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 4),
    ];
  } else if (search === "proof of value gauge") {
    matches = [
      ...evidenceCards.slice(0, 6),
      ...menus.slice(0, 2).map((row) => synthetic(row.platform || "menu", row.item_name || "", `${row.item_name || ""} là menu cue có thể dùng để sales chứng minh dashboard đã chạm vào product reality.`, "positive", 0.66)),
    ];
  } else if (search === "category brand rank") {
    const best = branches[0];
    matches = [
      best ? fromBranch(best, `${best.branch_name} hiện là branch tốt nhất với rating ${best.avg_rating || 0}, risk ${best.risk_score || 0} và topics ${(best.top_topics || []).join(", ") || "mixed"}.`, "positive", 0.8) : null,
      ...evidenceCards
        .filter((item) => ["positive", "mixed"].includes(String(item.sentiment_label || "")))
        .slice(0, 5),
    ].filter(Boolean);
  } else if (search === "campaign readiness & benchmark") {
    matches = [
      ...platforms.slice(0, 4).map((row) =>
        fromPlatform(row, `${row.platform} đang có readiness ${row.readiness_score || 0}, relevant ${row.relevant_count || 0} và status ${row.status || "unknown"} để support campaign readiness.`, "operational", 0.74),
      ),
      ...evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 3),
    ];
  } else if (search === "ymi-style score decomposition") {
    matches = [
      ...branches.slice(0, 4).map((row) =>
        fromBranch(row, `${row.branch_name} đang tạo mix score qua positive ${row.positive_count || 0}, negative ${row.negative_count || 0} và rating ${row.avg_rating || 0}.`, String(row.risk_level || "").toLowerCase() === "high" ? "negative" : "operational", 0.78),
      ),
      ...evidenceCards.slice(0, 3),
    ];
  } else if (search === "brand equity & sentiment score") {
    matches = [
      ...evidenceCards
        .filter((item) => ["positive", "negative"].includes(String(item.sentiment_label || "")))
        .sort((a, b) => Number(b.confidence_score || 0) - Number(a.confidence_score || 0))
        .slice(0, 8),
    ];
  } else if (search === "proof of premium readiness") {
    matches = [
      ...evidenceCards
        .filter((item) => String(item.sentiment_label || "") === "positive")
        .slice(0, 6),
      ...menus.slice(0, 2).map((row) =>
        synthetic(row.platform || "menu", row.item_name || "", `${row.item_name || ""} ở ${row.branch_name || ""} là cue premium/readiness vì có thể nối taste proof với product reality.`, "positive", 0.68),
      ),
    ];
  } else if (search === "brand health by branch") {
    matches = branches.slice(0, 8).map((row) =>
      fromBranch(
        row,
        `${row.branch_name} có score proxy từ rating ${row.avg_rating || 0}, positive ${row.positive_count || 0}, negative ${row.negative_count || 0} và delivery drag ${row.delivery_issue_count || 0}.`,
        String(row.risk_level || "").toLowerCase() === "high" ? "negative" : "operational",
        0.79,
      ),
    );
  } else if (search === "best branch pattern") {
    const best = branches[0];
    const worst = branches[branches.length - 1];
    matches = [
      best ? fromBranch(best, `${best.branch_name} đang là best branch pattern với topics ${(best.top_topics || []).join(", ") || "mixed"} và rating ${best.avg_rating || 0}.`, "positive", 0.83) : null,
      worst ? fromBranch(worst, `${worst.branch_name} là branch cần học lại pattern vì risk ${worst.risk_score || 0} và rating ${worst.avg_rating || 0}.`, "negative", 0.82) : null,
      ...evidenceCards.slice(0, 4),
    ].filter(Boolean);
  } else if (search === "crisis spike monitor") {
    matches = evidenceCards.filter((item) => String(item.sentiment_label || "") === "negative").slice(0, 8);
  } else if (search === "review health heatmap") {
    matches = branches.slice(0, 8).map((row) =>
      fromBranch(row, `${row.branch_name} có rating ${row.avg_rating || 0}, ${row.review_count || 0} reviews và ${row.negative_count || 0} tín hiệu tiêu cực.`, "operational", 0.78),
    );
  } else if (search === "response sla donut") {
    matches = actionRows.slice(0, 8).map((row) => synthetic(row.platform || "", row.title || "", `${row.owner || "Owner"} đang giữ trạng thái ${row.status || "pending"} cho action "${row.title || ""}".`, "operational", 0.7, row.source_url || ""));
  } else if (search === "social proof pipeline") {
    matches = evidenceCards.filter((item) => String(item.sentiment_label || "") === "positive").slice(0, 8);
  } else if (search === "competitive pressure radar" || search === "winning pattern comparison" || search === "5-mode response map" || search === "7-day audit funnel") {
    matches = [
      ...platforms.slice(0, 5).map((row) =>
        fromPlatform(row, `${row.platform} hiện chỉ là competitor proxy từ source quality/readiness/status, chưa phải benchmark thật từ đối thủ.`, "operational", 0.62),
      ),
      ...evidenceCards.slice(0, 3),
    ].slice(0, 8);
  }

  const items = (matches.length ? matches : evidenceCards).slice(0, 8);
  const negativeCount = items.filter((item) => String(item.sentiment_label || "") === "negative").length;
  const positiveCount = items.filter((item) => String(item.sentiment_label || "") === "positive").length;
  const avgConfidence = items.length
    ? Math.round((items.reduce((sum, item) => sum + Number(item.confidence_score || 0), 0) / items.length) * 100)
    : 0;
  return {
    title: query || (CURRENT_LANGUAGE === "en" ? "Evidence detail" : "Chi tiết bằng chứng"),
    items,
    stats: [
      { label: "Sources", value: String(items.length) },
      { label: "Sentiment mix", value: `${negativeCount} neg / ${positiveCount} pos` },
      { label: "Avg confidence", value: `${avgConfidence}%` },
    ],
  };
}

function renderEvidencePanel(payload) {
  document.getElementById("evidence-title").textContent = `Evidence - ${payload.title}`;
  document.getElementById("evidence-subtitle").textContent =
    CURRENT_LANGUAGE === "en"
      ? "Every insight should have original links for verification. This mock shows the structure to keep when connecting real data."
      : "Mỗi insight phải có link gốc để khách kiểm chứng. Panel này mô phỏng cấu trúc cần build khi nối data thật.";
  document.getElementById("evidence-stats").innerHTML = (payload.stats || []).map((item) => `
    <div class="evidenceStat">
      <small>${escapeHtml(item.label || "")}</small>
      <strong>${escapeHtml(item.value || "")}</strong>
    </div>
  `).join("");
  document.getElementById("evidence-list").innerHTML = (payload.items || []).map((item) => `
    <article class="evidenceItem">
      <div class="evidenceItemTop">
        <div>
          <b>${escapeHtml(String(item.platform || "").replaceAll("_", " · "))}</b>
          <strong>${escapeHtml(item.metric_label || item.platform || "")}</strong>
        </div>
        <span class="evidenceSentiment ${escapeHtml(String(item.sentiment_label || "neutral"))}">
          ${escapeHtml(String(item.sentiment_label || "neutral").replace(/^./, (char) => char.toUpperCase()))}
        </span>
      </div>
      <p class="evidenceQuote">“${escapeHtml(item.evidence_quote || "")}”</p>
      <div class="evidenceMeta">
        <span class="evidencePill">${escapeHtml(formatDateTime(item.evidence_date || ""))}</span>
        <span class="evidencePill">${escapeHtml(`Confidence ${Math.round(Number(item.confidence_score || 0) * 100)}%`)}</span>
        <span class="evidencePill">${escapeHtml(item.metric_label || "")}</span>
      </div>
      ${item.source_url ? `<a class="evidenceLink" href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Open original source ↗</a>` : ""}
    </article>
  `).join("");
  document.getElementById("evidence-foot").innerHTML =
    CURRENT_LANGUAGE === "en"
      ? "<b>Product guardrail:</b> only make strong claims when there is enough evidence coverage, source freshness and confidence. Otherwise the insight must stay in Need more data."
      : "<b>Product guardrail:</b> chỉ kết luận mạnh nếu có đủ evidence coverage, source freshness và confidence. Nếu không đủ, insight phải hiện trạng thái Need more data.";
  document.getElementById("evidenceOverlay").classList.remove("hidden");
}

function closeEvidencePanel() {
  document.getElementById("evidenceOverlay").classList.add("hidden");
}

function isMarketingPlatform(value) {
  return ["facebook", "tiktok", "instagram", "threads"].includes(String(value || "").toLowerCase());
}

function applyViewToQuick(cards) {
  if (CURRENT_VIEW !== "marketing") return cards || [];
  return (cards || []).filter((card) => {
    const tag = String(card.tag || "").toLowerCase();
    return !["google_maps", "shopeefood", "branch", "review risk", "lowest rating"].includes(tag);
  });
}

function applyViewToFeed(rows) {
  if (CURRENT_VIEW !== "marketing") return rows || [];
  return (rows || []).filter((row) => isMarketingPlatform(row.platform));
}

function applyViewToModules(modules) {
  if (CURRENT_VIEW !== "marketing") return modules || [];
  return (modules || []).filter((module) => {
    const title = String(module.title || "").toLowerCase();
    return !title.includes("review") && !title.includes("rating") && !title.includes("delivery");
  });
}

function renderModules(modules) {
  document.getElementById("modules").innerHTML = (modules || []).map((module) => `
    <article class="module">
      <div class="mHead">
        <div>
          <h3>${escapeHtml(module.title || "")}</h3>
          <p class="takeaway">${escapeHtml(module.takeaway || "")}</p>
          <div class="proofRow">
            <span class="evidenceTag">Evidence-backed module</span>
            <button
              class="moduleEvidenceBtn"
              type="button"
              data-evidence-query="${escapeHtml(module.evidence_query || module.title || "")}"
            >${escapeHtml(CURRENT_LANGUAGE === "en" ? "Open evidence" : "Open evidence")}</button>
          </div>
        </div>
        <button class="askBtn" type="button">Ask why</button>
      </div>
      <div class="mBody">
        <div class="chartBox">${renderChart(module)}</div>
        <div class="analysisBox">
          <div class="analysis">
            <b>Analysis</b>
            <ul>${(module.analysis || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          </div>
          <div class="action">
            <b>Suggested Action</b>
            <div class="row"><span>Guardrail</span><span>${escapeHtml(module.action?.guardrail || "")}</span></div>
            <div class="row"><span>Owner</span><span>${escapeHtml(module.action?.owner || "")}</span></div>
            <div class="row"><span>CTA</span><span>${escapeHtml(module.action?.cta || "")}</span></div>
          </div>
        </div>
      </div>
    </article>
  `).join("");
  document.querySelectorAll(".moduleEvidenceBtn[data-evidence-query]").forEach((button) => {
    button.addEventListener("click", () => {
      renderEvidencePanel(buildEvidencePayload(String(button.dataset.evidenceQuery || "").trim()));
    });
  });
}

function renderChart(module) {
  const chart = module.chart;
  if (chart === "hbar") return renderHBar(module.data || []);
  if (chart === "revenueImpact") return renderRevenueImpact(module.data || {});
  if (chart === "matrix") return renderMatrix(module.data || []);
  if (chart === "waterfall") return renderWaterfall(module.data || []);
  if (chart === "timeline") return renderTimeline(module.data || []);
  if (chart === "groupedColumns") return renderGroupedColumns(module.data || {});
  if (chart === "list") return renderList(module.data || []);
  if (chart === "gauge") return renderGauge(module.data || {});
  if (chart === "donut") return renderDonut(module.data || {});
  if (chart === "pipeline") return renderPipeline(module.data || []);
  if (chart === "stacked") return renderStacked(module.data || []);
  if (chart === "line") return renderLine(module.data || {});
  if (chart === "table") return renderSimpleTable(module.data || []);
  if (chart === "modeMap") return renderModeMap(module.data || []);
  if (chart === "treemap") return renderTreemap(module.data || []);
  return `<div class="emptyChart">Chart pending</div>`;
}

function renderRevenueImpact(data) {
  const bars = Array.isArray(data.bars) ? data.bars : [];
  const chips = Array.isArray(data.chips) ? data.chips : [];
  return `
    <div class="revenueImpact">
      <div class="revenueBars">
        ${bars.map((row, index) => {
          const width = Math.max(24, Math.min(100, Number(row[1] || 0)));
          return `
            <div class="revTrack">
              <div class="revRow rev${index + 1}" style="width:${width}%">
                <span class="revLabel">${escapeHtml(row[0])}</span>
                <span class="revValue">${escapeHtml(`${row[1]}%`)}</span>
              </div>
            </div>
          `;
        }).join("")}
      </div>
      <div class="revChips">
        ${chips.map((chip) => `<span class="revChip">${escapeHtml(chip)}</span>`).join("")}
      </div>
    </div>
  `;
}

function renderHBar(rows) {
  const max = Math.max(...rows.map((row) => Number(row[1] || 0)), 1);
  return `<div class="hBar">${rows.map((row) => `
    <div class="hRow">
      <div class="hLabel">${escapeHtml(row[0])}</div>
      <div class="hTrack"><span style="width:${(Number(row[1] || 0) / max) * 100}%"></span></div>
      <div class="hValue">${escapeHtml(row[1])}</div>
    </div>
  `).join("")}</div>`;
}

function renderMatrix(rows) {
  const placed = [];
  const points = (rows || []).map((row, index) => {
    let urgency = Math.max(8, Math.min(92, Number(row[1] || 0)));
    let impact = Math.max(8, Math.min(92, Number(row[2] || 0)));
    let left = urgency;
    let top = impact;

    for (const prior of placed) {
      const dx = Math.abs(prior.left - left);
      const dy = Math.abs(prior.top - top);
      if (dx < 12 && dy < 12) {
        const direction = index % 2 === 0 ? 1 : -1;
        left = Math.max(10, Math.min(90, left + direction * (10 + index * 2)));
        top = Math.max(10, Math.min(90, top - direction * (6 + index * 2)));
      }
    }

    placed.push({ left, top });
    const tone = severityClass(row[3]);
    const shortLabel = String(row[0] || "").replace(/^MeiLi\s*-\s*/i, "");
    return `
      <div class="matrixPoint ${tone}" style="left:${left}%;top:${top}%">
        <span class="matrixDot"></span>
        <label title="${escapeHtml(row[0])}">${escapeHtml(shortLabel)}</label>
      </div>
    `;
  }).join("");
  return `
    <div class="matrixBoard">
      <div class="matrixQuadrant q1"></div>
      <div class="matrixQuadrant q2"></div>
      <div class="matrixQuadrant q3"></div>
      <div class="matrixQuadrant q4"></div>
      <div class="matrixAxis vertical"></div>
      <div class="matrixAxis horizontal"></div>
      <div class="matrixLegend tl">Low urgency</div>
      <div class="matrixLegend tr">High urgency</div>
      <div class="matrixLegend bl">High impact</div>
      <div class="matrixLegend br">High impact</div>
      ${points}
    </div>
  `;
}

function renderTimeline(rows) {
  return `<div class="timeline">${rows.map((row) => `
    <div class="timeRow">
      <div class="timeDot"></div>
      <div class="timeMeta">${escapeHtml(row[0])}</div>
      <div><b>${escapeHtml(row[1])}</b><span>${escapeHtml(row[2])}</span></div>
    </div>
  `).join("")}</div>`;
}

function renderWaterfall(rows) {
  const max = Math.max(...rows.map((row) => Math.abs(Number(row[1] || 0))), 1);
  return `<div class="waterfall">${rows.map((row) => {
    const value = Number(row[1] || 0);
    const tone = value < 0 ? "neg" : (row[0] === "Current" ? "total" : "pos");
    return `
      <div class="waterRow">
        <div class="waterLabel">${escapeHtml(row[0])}</div>
        <div class="waterTrack"><span class="${tone}" style="width:${(Math.abs(value) / max) * 100}%"></span></div>
        <div class="waterValue">${value > 0 && row[0] !== "Base" && row[0] !== "Current" ? "+" : ""}${escapeHtml(value)}</div>
      </div>
    `;
  }).join("")}</div>`;
}

function renderGroupedColumns(data) {
  const labels = data.labels || [];
  const series = data.series || [];
  const max = Math.max(1, ...series.flatMap((row) => row.values || []).map((value) => Number(value || 0)));
  return `
    <div class="gCols">
      ${labels.map((label, index) => `
        <div class="gCol">
          <div class="gBars">
            ${series.map((row) => `
              <span class="gBar" title="${escapeHtml(row.name)}: ${escapeHtml(row.values?.[index])}" style="height:${(Number(row.values?.[index] || 0) / max) * 160}px;background:${escapeHtml(row.color || "#1f66f5")}"></span>
            `).join("")}
          </div>
          <div class="gLabel">${escapeHtml(label)}</div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderList(rows) {
  return `<div class="listChart">${rows.map((row) => `
    <div class="listRow">
      <b>${escapeHtml(row[0])}</b>
      <span>${escapeHtml(row[1] || "")}</span>
      <p>${escapeHtml(row[2] || "")}</p>
    </div>
  `).join("")}</div>`;
}

function renderGauge(data) {
  const value = Number(data.value || 0);
  const detail = String(data.detail || "").trim();
  const badges = Array.isArray(data.badges) ? data.badges : [];
  const metricLabels = ["Core signal", "Coverage", "Blocked noise", "AI confidence"];
  return `
    <div class="gaugePanel">
      <div class="gaugeHero">
        <div class="gauge">
          <div class="gaugeRing" style="--pct:${value}">
            <strong>${value}%</strong>
          </div>
          <div class="gaugeLabel">${escapeHtml(data.label || "")}</div>
          ${detail ? `<div class="gaugeDetail">${escapeHtml(detail)}</div>` : ""}
        </div>
        <div class="gaugeStats">
          ${badges.map((item, index) => `
            <div class="gaugeStat">
              <small>${escapeHtml(metricLabels[index] || `Signal ${index + 1}`)}</small>
              <strong>${escapeHtml(item)}</strong>
            </div>
          `).join("")}
        </div>
      </div>
      <div class="gaugeMeta">
        ${badges.map((item, index) => `
          <div class="gaugeCard">
            <small>${escapeHtml(metricLabels[index] || `Signal ${index + 1}`)}</small>
            <strong>${escapeHtml(item)}</strong>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderDonut(data) {
  const values = Array.isArray(data.values) ? data.values : [];
  const labels = Array.isArray(data.labels) ? data.labels : [];
  const total = Math.max(1, values.reduce((sum, value) => sum + Number(value || 0), 0));
  const segments = ["#184A3A", "#C8A857", "#C3423F"];
  let cursor = 0;
  const gradient = values.map((value, index) => {
    const start = cursor;
    cursor += (Number(value || 0) / total) * 100;
    return `${segments[index % segments.length]} ${start}% ${cursor}%`;
  }).join(", ");
  return `
    <div class="donutWrap">
      <div class="donutRing" style="background:conic-gradient(${gradient})"><strong>${total}</strong></div>
      <div class="donutLegend">
        ${labels.map((label, index) => `
          <div class="donutItem">
            <i style="background:${segments[index % segments.length]}"></i>
            <span>${escapeHtml(label)}</span>
            <b>${escapeHtml(values[index])}</b>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderPipeline(rows) {
  const max = Math.max(...rows.map((row) => Number(row[1] || 0)), 1);
  return `
    <div class="pipeFlow">
      ${rows.map((row, index) => `
        <div class="pipeStep">
          <div class="pipeBox" style="width:${Math.max(22, (Number(row[1] || 0) / max) * 100)}%">
            <span>${escapeHtml(row[0])}</span>
            <b>${escapeHtml(row[1])}</b>
          </div>
          ${index < rows.length - 1 ? '<em>→</em>' : ''}
        </div>
      `).join("")}
    </div>
  `;
}

function renderStacked(rows) {
  const max = Math.max(...rows.map((row) => Number(row[1] || 0) + Number(row[2] || 0) + Number(row[3] || 0)), 1);
  return `<div class="stacked">${rows.map((row) => {
    const total = Number(row[1] || 0) + Number(row[2] || 0) + Number(row[3] || 0);
    return `
      <div class="stackRow">
        <div class="stackLabel">${escapeHtml(row[0])}</div>
        <div class="stackTrack">
          <span class="seg one" style="width:${(Number(row[1] || 0) / max) * 100}%"></span>
          <span class="seg two" style="width:${(Number(row[2] || 0) / max) * 100}%"></span>
          <span class="seg three" style="width:${(Number(row[3] || 0) / max) * 100}%"></span>
        </div>
        <div class="stackValue">${total}</div>
      </div>
    `;
  }).join("")}</div>`;
}

function renderLine(data) {
  const labels = data.labels || [];
  const series = data.series || [];
  return `<div class="lineLegend">${series.map((row) => `<span><i style="background:${escapeHtml(row.color || "#1f66f5")}"></i>${escapeHtml(row.name)}</span>`).join("")}</div>
    <div class="lineTable">${labels.map((label, index) => `
      <div class="lineRow">
        <b>${escapeHtml(label)}</b>
        ${series.map((row) => `<span>${escapeHtml(row.name)}: ${escapeHtml(row.values?.[index])}</span>`).join("")}
      </div>
    `).join("")}</div>`;
}

function renderSimpleTable(rows) {
  return `<div class="simpleTable">${rows.map((row) => `
    <div class="simpleRow">${row.map((cell) => `<span>${escapeHtml(cell)}</span>`).join("")}</div>
  `).join("")}</div>`;
}

function renderModeMap(rows) {
  return `<div class="modeMap">${rows.map((row) => `
    <div class="modeRow">
      <b>${escapeHtml(row[0])}</b>
      <span>${escapeHtml(row[1])}</span>
      <p>${escapeHtml(row[2])}</p>
    </div>
  `).join("")}</div>`;
}

function renderTreemap(rows) {
  const total = Math.max(1, rows.reduce((sum, row) => sum + Number(row[1] || 0), 0));
  const palette = ["#184A3A", "#2d6b54", "#3f7e67", "#5f927f", "#87a69c", "#b2c5be"];
  return `
    <div class="treemap">
      ${rows.map((row, index) => {
        const size = Math.max(16, Math.round((Number(row[1] || 0) / total) * 100));
        return `
          <div class="treeCell" style="--span:${size};--bg:${palette[index % palette.length]}">
            <b>${escapeHtml(row[0])}</b>
            <span>${escapeHtml(row[1])}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderFeed(rows) {
  const target = document.getElementById("feedTable");
  target.innerHTML = `
    <div class="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Signal</th>
            <th>Platform</th>
            <th>Severity</th>
            <th>Metric</th>
            <th>Owner</th>
            <th>Status</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          ${(rows || []).map((row) => `
            <tr>
              <td><b>${escapeHtml(row.title || "")}</b></td>
              <td>${escapeHtml(row.platform || "")}</td>
              <td><span class="sev ${escapeHtml(row.severity || "Low")}">${escapeHtml(row.severity || "Low")}</span></td>
              <td>${escapeHtml(row.metric || "")}</td>
              <td>${escapeHtml(row.owner || "")}</td>
              <td>${escapeHtml(row.status || "")}</td>
              <td>${escapeHtml(row.summary || "")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function applyTheme(themeName) {
  const nextTheme = themeName || "default";
  CURRENT_THEME = nextTheme;
  document.body.dataset.theme = nextTheme;
  const select = document.getElementById("themeSelect");
  if (select && select.value !== nextTheme) select.value = nextTheme;
  try {
    window.localStorage.setItem("meili-dashboard-theme", nextTheme);
  } catch (_error) {
    // Ignore storage issues in restricted browsers.
  }
}

function applyLanguage(language) {
  const nextLanguage = language || "vi";
  const copy = UI_COPY[nextLanguage] || UI_COPY.vi;
  CURRENT_LANGUAGE = nextLanguage;
  document.documentElement.lang = nextLanguage;
  document.getElementById("brand-subtitle").textContent = copy.brandSubtitle;
  document.getElementById("note-title").textContent = copy.noteTitle;
  document.getElementById("note-copy").innerHTML = copy.noteCopy;
  document.getElementById("theme-title").innerHTML = copy.themeTitle;
  document.getElementById("theme-copy").textContent = copy.themeCopy;
  document.getElementById("brand-logo-title").textContent = copy.brandLogoTitle;
  document.getElementById("brand-skin-title").textContent = copy.brandSkinTitle;
  document.getElementById("branch-scope-title").textContent = "Branch Intelligence Layer";
  document.getElementById("branch-scope-copy").textContent =
    CURRENT_LANGUAGE === "en"
      ? "Choose Brand / Region / Branch to understand whether the issue is system-wide or limited to one branch."
      : "Chọn Brand / Region / Branch để biết vấn đề là toàn hệ thống hay chỉ xảy ra ở một chi nhánh.";
  document.getElementById("feed-title").textContent = copy.feedTitle;
  document.getElementById("feed-copy").textContent = copy.feedCopy;
  document.getElementById("search").placeholder = copy.searchPlaceholder;
  document.getElementById("tableFilter").placeholder = copy.tableFilterPlaceholder;
  document.getElementById("filter-type").options[0].text = "All type";
  document.getElementById("filter-severity").options[0].text = "All severity";
  document.getElementById("filter-owner").options[0].text = "All owner";
  document.getElementById("filter-guardrail").options[0].text = "All guardrail";
  document.getElementById("reset-button").textContent = nextLanguage === "en" ? "Reset" : "Reset";
  const languageSelect = document.getElementById("languageSelect");
  if (languageSelect.value !== nextLanguage) languageSelect.value = nextLanguage;
  try {
    window.localStorage.setItem("meili-dashboard-language", nextLanguage);
  } catch (_error) {
    // Ignore storage issues in restricted browsers.
  }
}

function applyViewMode(viewName) {
  const nextView = viewName || "all";
  CURRENT_VIEW = nextView;
  document.body.dataset.view = nextView;
  const viewSelect = document.getElementById("viewSelect");
  if (viewSelect.value !== nextView) viewSelect.value = nextView;
  try {
    window.localStorage.setItem("meili-dashboard-view", nextView);
  } catch (_error) {
    // Ignore storage issues in restricted browsers.
  }
}

function applyScope(scopeName) {
  CURRENT_SCOPE = scopeName || "brand";
  const select = document.getElementById("scopeSelect");
  if (select && select.value !== CURRENT_SCOPE) select.value = CURRENT_SCOPE;
}

function applyBranch(branchSlug) {
  CURRENT_BRANCH = branchSlug || "all";
  const select = document.getElementById("branchSelect");
  if (select && select.value !== CURRENT_BRANCH) select.value = CURRENT_BRANCH;
}

function render() {
  if (!REPORT) return;
  const screen = REPORT.screens?.[CURRENT_SCREEN];
  if (!screen) return;
  const copy = UI_COPY[CURRENT_LANGUAGE] || UI_COPY.vi;
  const brandName = REPORT.brand?.brand_name || "Meili";
  const branches = Array.isArray(REPORT.branches) ? REPORT.branches : [];
  const modules = applyViewToModules(filterModules(screen.modules || []));
  const feed = applyViewToFeed(filterFeed(screen.feed || []));
  const quickCards = applyViewToQuick(screen.topCards || []);
  document.getElementById("brand-title").textContent = "DOTN GROWTH INTELLIGENCE";
  document.getElementById("title").textContent = screen.title;
  document.getElementById("subtitle").textContent = copy.screenSubtitles[CURRENT_SCREEN] || screen.subtitle;
  document.getElementById("headline").textContent = CURRENT_VIEW === "marketing" ? `${copy.marketingView} · ${screen.headline || ""}` : (screen.headline || "");
  document.getElementById("account-pill").textContent = `${copy.accountPrefix} · ${brandName}`;
  document.getElementById("generated-pill").textContent = formatDateTime(REPORT.generated_at);
  document.getElementById("branch-pill").textContent = `${(REPORT.branches || []).length} ${copy.branches}`;
  document.getElementById("fromDate").value = REPORT.date_range?.from || "";
  document.getElementById("toDate").value = REPORT.date_range?.to || "";
  document.getElementById("brand-logo-caption").textContent = `${brandName} / Client Logo`;
  document.getElementById("brand-skin-copy").textContent = CURRENT_LANGUAGE === "en"
    ? `${brandName} uses DOTN's hybrid skin: warmer palette, premium F&B feel, and a brand-personalized dashboard layer.`
    : `${brandName} đang dùng hybrid skin của DOTN: palette ấm, cảm giác F&B premium và dashboard cá nhân hóa theo brand.`;
  const branchSelect = document.getElementById("branchSelect");
  branchSelect.innerHTML = [
    `<option value="all">All branches</option>`,
    ...branches.map((row) => `<option value="${escapeHtml(row.branch_slug || "")}">${escapeHtml(row.branch_name || row.branch_slug || "")}</option>`),
  ].join("");
  branchSelect.value = CURRENT_BRANCH;
  const selectedBranch = branches.find((row) => row.branch_slug === CURRENT_BRANCH);
  const scopeText = CURRENT_SCOPE === "branch"
    ? (selectedBranch?.branch_name || "Selected branch")
    : CURRENT_SCOPE === "region"
      ? "Region view"
      : "All brand";
  document.getElementById("branchContextBadge").textContent = `Scope: ${scopeText}`;
  renderNav(REPORT);
  renderQuick(quickCards);
  renderModules(modules);
  renderFeed(feed);
}

async function bootstrap() {
  REPORT = hydrateReport(await fetchJson("/api/report"));
  await ensureSourceConfigLoaded();
  const themeSelect = document.getElementById("themeSelect");
  const languageSelect = document.getElementById("languageSelect");
  const viewSelect = document.getElementById("viewSelect");
  const scopeSelect = document.getElementById("scopeSelect");
  const branchSelect = document.getElementById("branchSelect");
  const aiFab = document.getElementById("aiFab");
  const addSourceRow = document.getElementById("addSourceRow");
  const saveSourceConfigButton = document.getElementById("saveSourceConfig");
  const savedTheme = window.localStorage.getItem("meili-dashboard-theme") || "default";
  const savedLanguage = window.localStorage.getItem("meili-dashboard-language") || "vi";
  const savedView = window.localStorage.getItem("meili-dashboard-view") || "all";
  applyTheme(savedTheme);
  applyLanguage(savedLanguage);
  applyViewMode(savedView);
  applyScope("brand");
  applyBranch("all");
  themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value || "default");
  });
  languageSelect.addEventListener("change", (event) => {
    applyLanguage(event.target.value || "vi");
    render();
  });
  viewSelect.addEventListener("change", (event) => {
    applyViewMode(event.target.value || "all");
    render();
  });
  scopeSelect.addEventListener("change", (event) => {
    applyScope(event.target.value || "brand");
    render();
  });
  branchSelect.addEventListener("change", (event) => {
    applyBranch(event.target.value || "all");
    if ((event.target.value || "all") !== "all") applyScope("branch");
    render();
  });
  document.getElementById("search").addEventListener("input", (event) => {
    GLOBAL_QUERY = event.target.value || "";
    render();
  });
  document.getElementById("tableFilter").addEventListener("input", (event) => {
    FEED_QUERY = event.target.value || "";
    render();
  });
  document.getElementById("evidence-close").addEventListener("click", closeEvidencePanel);
  document.querySelectorAll("[data-close-evidence='1']").forEach((node) => {
    node.addEventListener("click", closeEvidencePanel);
  });
  addSourceRow.addEventListener("click", () => {
    SOURCE_CONFIG.sources.push(blankSourceRow());
    renderSourceConfigRows();
  });
  saveSourceConfigButton.addEventListener("click", async () => {
    try {
      await saveSourceConfig();
    } catch (error) {
      setSourceConfigError(error.message || "Không thể lưu source config.");
    }
  });
  aiFab.addEventListener("click", () => {
    renderEvidencePanel(buildEvidencePayload("CEO summary"));
  });
  render();
  if (!SOURCE_CONFIG.completed) {
    showSourceConfigOverlay();
  }
}

bootstrap().catch((error) => {
  document.getElementById("title").textContent = "Failed to load dashboard";
  document.getElementById("headline").textContent = error.message;
});
