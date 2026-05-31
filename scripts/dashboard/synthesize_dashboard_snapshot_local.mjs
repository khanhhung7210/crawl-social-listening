import { execFileSync } from 'child_process';

import { BRAND_SLUG, PGDATABASE, SCHEMA, runPsqlText, sqlJson, sqlStr } from './dashboard_local_lib.mjs';

async function main() {
  const basePayload = loadBasePayload();
  const snapshot = buildLocalSnapshot(basePayload);
  const brandId = fetchBrandId();
  upsertSnapshot(brandId, snapshot);
  console.log(
    JSON.stringify(
      {
        mode: 'local',
        pg_database: PGDATABASE,
        schema: SCHEMA,
        brand_slug: BRAND_SLUG,
        snapshot_written: true,
        overview_cards: (snapshot.overview?.top_cards || []).length,
        overview_modules: (snapshot.screens?.overview?.modules || []).length,
      },
      null,
      2,
    ),
  );
}

function loadBasePayload() {
  const code = `
import json
from social_listening.dashboard.repository import PostgresDashboardRepository
repo = PostgresDashboardRepository(database='${PGDATABASE}', schema='${SCHEMA}', brand_slug='${BRAND_SLUG}')
print(json.dumps(repo.get_dashboard_payload(), ensure_ascii=False))
  `.trim();
  const text = execFileSync('python3', ['-c', code], {
    cwd: process.cwd(),
    env: { ...process.env, PYTHONPATH: `${process.cwd()}/src` },
    encoding: 'utf8',
  });
  return JSON.parse(text);
}

function buildLocalSnapshot(payload) {
  const platformSummary = payload.platform_summary || [];
  const branchRows = payload.branch_intelligence || [];
  const evidenceCards = payload.evidence_cards || [];
  const actionFeed = payload.mentions_feed || [];
  const topRisk = branchRows[0] || {};
  const strongestSocial = [...platformSummary]
    .filter((row) => ['facebook', 'tiktok', 'instagram', 'threads'].includes(String(row.platform || '')))
    .sort((left, right) => Number(right.relevant_count || 0) - Number(left.relevant_count || 0))[0] || {};
  const trustedReview = [...platformSummary]
    .filter((row) => Number(row.review_count || 0) > 0)
    .sort((left, right) => Number(right.review_count || 0) - Number(left.review_count || 0))[0] || {};
  const totalRelevant = platformSummary.reduce((sum, row) => sum + Number(row.relevant_count || 0), 0);
  const totalMentions = platformSummary.reduce((sum, row) => sum + Number(row.mention_count || 0), 0);
  const negativeEvidence = evidenceCards.filter((row) => String(row.sentiment_label || '') === 'negative');
  const positiveEvidence = evidenceCards.filter((row) => String(row.sentiment_label || '') === 'positive');
  const topNegative = negativeEvidence[0] || {};
  const blockedSources = platformSummary.filter((row) => ['metadata_only', 'noisy', 'pending_filter'].includes(String(row.status || '')));
  const actionFeedCount = actionFeed.length;

  const overviewHeadline = buildOverviewHeadline(topRisk, strongestSocial, trustedReview);
  const listenHeadline = buildListenHeadline(topRisk, strongestSocial, totalRelevant, negativeEvidence.length);

  return {
    overview: {
      headline: overviewHeadline,
      top_cards: buildTopCards(
        topRisk,
        strongestSocial,
        trustedReview,
        totalRelevant,
        totalMentions,
        negativeEvidence.length,
        positiveEvidence.length,
        topNegative,
        blockedSources.length,
        actionFeedCount,
        branchRows,
      ),
    },
    screens: {
      overview: {
        headline: overviewHeadline,
        modules: [
          buildLostCustomerSignalsModule(branchRows, evidenceCards),
          buildActionTimelineModule(topRisk, strongestSocial, trustedReview, actionFeed),
        ],
      },
      listen: {
        headline: listenHeadline,
      },
    },
  };
}

function buildOverviewHeadline(topRisk, strongestSocial, trustedReview) {
  const branchName = topRisk.branch_name || 'branch cần theo dõi';
  const riskScore = Number(topRisk.risk_score || 0);
  const socialPlatform = String(strongestSocial.platform || 'social');
  const socialRelevant = Number(strongestSocial.relevant_count || 0);
  const reviewPlatform = String(trustedReview.platform || 'google_maps');
  const reviewCount = Number(trustedReview.review_count || 0);
  return `Pain rõ nhất đang nằm ở ${branchName} (risk ${riskScore}), trong khi ${socialPlatform} đang kéo ${socialRelevant} tín hiệu discovery và ${reviewPlatform} giữ ${reviewCount} review trust để đội vận hành chốt thứ tự ưu tiên.`;
}

function buildListenHeadline(topRisk, strongestSocial, totalRelevant, negativeEvidenceCount) {
  const branchName = topRisk.branch_name || 'branch risk';
  const socialPlatform = String(strongestSocial.platform || 'social');
  return `Dotn Listen hiện đang đọc ${totalRelevant} tín hiệu đủ sạch; ${socialPlatform} đang nuôi demand tốt nhất, còn ${branchName} và ${negativeEvidenceCount} negative evidence là hai vùng cần khóa hành động trước khi amplify proof.`;
}

function buildTopCards(
  topRisk,
  strongestSocial,
  trustedReview,
  totalRelevant,
  totalMentions,
  negativeEvidenceCount,
  positiveEvidenceCount,
  topNegative,
  blockedSourceCount,
  actionFeedCount,
  branchRows,
) {
  const socialRows = [strongestSocial].filter((row) => row && row.platform);
  const socialVolume = socialRows.reduce((sum, row) => sum + Number(row.relevant_count || 0), 0);
  const qualifiedRatio = totalMentions ? Math.round((totalRelevant / totalMentions) * 100) : 0;
  const branchTotal = branchRows.length;
  const ratedBranchCount = branchRows.filter((row) => Number(row.avg_rating || 0) > 0 || Number(row.review_count || 0) > 0).length;
  const reviewTrustCount = branchRows.reduce((sum, row) => sum + Number(row.review_count || 0), 0);
  const trustCoverageRatio = branchTotal ? ratedBranchCount / branchTotal : 0;
  return [
    {
      tag: 'RỦI RO DANH TIẾNG',
      title: `${topRisk.branch_name || 'Chi nhánh'} cần theo dõi`,
      value: Number(topRisk.risk_score || 0) >= 30 ? 'Cao' : 'Vừa',
      desc: `Rating ${topRisk.avg_rating || 0} và ${topRisk.negative_count || 0} tín hiệu tiêu cực đang kéo risk lên.`,
      severity: severityFromRisk(topRisk.risk_level),
      owner: 'Vận hành',
      guardrail: 'Ưu tiên sửa trước',
      evidence_query: 'Branch Risk Snapshot',
      evidence_kind: 'branch_negative',
      evidence_branch: topRisk.branch_name || '',
      evidence_platform: '',
    },
    {
      tag: 'CLEANUP NGUỒN',
      title: 'Dọn nhiễu trước khi scale insight',
      value: blockedSourceCount >= 2 ? 'Cao' : (blockedSourceCount === 1 ? 'Vừa' : 'Ổn'),
      desc: `${blockedSourceCount} nguồn còn noisy hoặc thiếu review depth, chưa nên dùng để kết luận mạnh.`,
      severity: blockedSourceCount ? 'high' : 'low',
      owner: 'Listening',
      guardrail: 'Theo dõi trước',
      evidence_query: 'Channel Signal Quality',
      evidence_kind: 'source_cleanup',
    },
    {
      tag: 'CƠ HỘI TĂNG TRƯỞNG',
      title: `Social volume đang kéo bởi ${titleCasePreserve(strongestSocial.platform || 'social')}`,
      value: socialVolume >= 100 ? 'Sẵn sàng' : 'Theo dõi',
      desc: `${socialVolume} tín hiệu social liên quan đang đủ để đọc demand/theme rõ hơn.`,
      severity: socialVolume ? 'medium' : 'low',
      owner: 'Marketing',
      guardrail: 'Sẵn sàng chạy campaign',
      evidence_query: 'Channel Signal Quality',
      evidence_kind: 'growth_platform',
      evidence_branch: '',
      evidence_platform: strongestSocial.platform || '',
    },
    {
      tag: 'BẰNG CHỨNG TÍCH CỰC',
      title: 'Proof bank bắt đầu dùng được',
      value: positiveEvidenceCount >= 3 ? 'Mạnh' : 'Mỏng',
      desc: `${positiveEvidenceCount} quote tích cực có thể đưa vào social proof hoặc recovery narrative.`,
      severity: 'low',
      owner: 'Marketing',
      guardrail: 'An toàn để khuếch đại',
      evidence_query: 'Social Proof Pipeline',
      evidence_kind: 'positive_proof',
    },
    {
      tag: 'QUALIFIED SIGNAL',
      title: 'Tín hiệu F&B đã qua relevance',
      value: `${qualifiedRatio}%`,
      desc: `${totalRelevant}/${totalMentions || totalRelevant} record đang đủ chuẩn để đọc insight thay vì vanity volume.`,
      severity: qualifiedRatio >= 70 ? 'low' : 'medium',
      owner: 'Strategy',
      guardrail: 'Đọc insight trên signal sạch',
      evidence_query: 'Qualified Signal Summary',
      evidence_kind: 'qualified_signal',
    },
    {
      tag: 'ACTION FEED',
      title: 'Queue xử lý đã có owner',
      value: String(actionFeedCount),
      desc: `${negativeEvidenceCount} negative evidence và ${actionFeedCount} dòng hành động đã sẵn để mở task thật.`,
      severity: actionFeedCount ? 'medium' : 'low',
      owner: 'Ops + CS',
      guardrail: 'Mở case theo evidence',
      evidence_query: 'Priority Action Detail',
      evidence_kind: 'action_queue',
    },
    {
      tag: 'REVIEW TRUST',
      title: 'Review trust đã phủ chi nhánh',
      value: `${ratedBranchCount}/${branchTotal || 0}`,
      desc: `${reviewTrustCount} review trust đang nối được với ${ratedBranchCount}/${branchTotal || 0} chi nhánh để đối chiếu branch risk.`,
      severity: trustCoverageRatio >= 0.75 ? 'low' : (trustCoverageRatio > 0 ? 'medium' : 'high'),
      owner: 'CX + Ops',
      guardrail: 'Bổ sung review depth',
      evidence_query: 'Review Health Heatmap',
      evidence_kind: '',
    },
  ];
}

function buildLostCustomerSignalsModule(branchRows, evidenceCards) {
  const topicWeights = new Map();
  for (const branch of branchRows.slice(0, 6)) {
    for (const topic of branch.top_topics || []) {
      topicWeights.set(topic, (topicWeights.get(topic) || 0) + Number(branch.negative_count || 0) + 1);
    }
  }
  const evidenceByPlatform = new Map();
  for (const card of evidenceCards) {
    if (String(card.sentiment_label || '') !== 'negative') continue;
    const key = String(card.platform || 'unknown');
    evidenceByPlatform.set(key, (evidenceByPlatform.get(key) || 0) + 1);
  }
  const rows = [...topicWeights.entries()]
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4)
    .map(([topic, value]) => [humanizeTopic(topic), value]);
  for (const [platform, value] of [...evidenceByPlatform.entries()].sort((left, right) => right[1] - left[1]).slice(0, 2)) {
    rows.push([titleCasePreserve(platform), value]);
  }
  const data = rows.slice(0, 6);
  return {
    title: 'Lost Customer Signals',
    takeaway: 'Nhìn thẳng vào các tín hiệu đang làm khách chùn tay hoặc không muốn quay lại để tránh nói chuyện bằng vanity metrics.',
    chart: 'hbar',
    data,
    analysis: [
      `${data[0]?.[0] || 'Delivery / value'} đang là lost signal mạnh nhất trong tập dữ liệu hiện tại, vì vừa xuất hiện ở branch risk vừa lặp lại trong negative evidence.`,
      'Nhóm loss signal này nên được xem là input cho vận hành và nội dung phản hồi, không chỉ là phần mô tả insight.',
      'Khi pipeline chạy định kỳ 30 phút, module này sẽ phản ứng đủ nhanh để phát hiện branch nào đang bắt đầu trượt trải nghiệm.',
    ],
    action: {
      guardrail: 'Use customer-language pain before proposing campaigns',
      owner: 'Ops + CX + Marketing',
      cta: 'Open Lost Signal Detail',
    },
    evidence_query: 'Lost Customer Signals',
  };
}

function buildActionTimelineModule(topRisk, strongestSocial, trustedReview, actionFeed) {
  const branchName = topRisk.branch_name || 'branch risk';
  const sourceName = titleCasePreserve(strongestSocial.platform || 'social');
  const reviewSource = titleCasePreserve(trustedReview.platform || 'review source');
  const firstFeed = actionFeed[0] || {};
  return {
    title: "Today's Action Timeline",
    takeaway: 'Biến data thành nhịp hành động cụ thể trong ngày thay vì dừng ở phần đọc chart.',
    chart: 'timeline',
    data: [
      ['1h', 'Listening', `Rà lại card ${firstFeed.title || branchName} và xác nhận owner xử lý pain ngay trong ca hiện tại.`],
      ['24h', 'Ops + CX', `Khóa plan xử lý cho ${branchName}, ưu tiên response với quote tiêu cực và kiểm tra lại flow giao hàng/menu.`],
      ['7 ngày', 'Marketing', `Dùng ${sourceName} để test creative/copy, còn ${reviewSource} làm lớp proof trust sau khi pain nóng đã hạ.`],
    ],
    analysis: [
      'Timeline này cố ý đi từ chặn pain, phản hồi evidence, rồi mới đến amplify social proof để tránh dashboard thành vanity deck.',
      'Nếu nguồn review trust còn mỏng, nên ưu tiên crawl/coverage trước khi scale campaign narrative quá mạnh.',
      'Action loop này phù hợp cho cadence 30 phút vì vừa đủ nhanh để bắt spike, vừa đủ chậm để không gây nhiễu thao tác.',
    ],
    action: {
      guardrail: 'One owner, one deadline, one proof source per action',
      owner: 'Cross-functional',
      cta: 'Assign Tasks',
    },
    evidence_query: "Today's Action Timeline",
  };
}

function fetchBrandId() {
  const sql = `
SELECT brand_id::text
FROM ${SCHEMA}.brands
WHERE brand_slug = ${sqlStr(BRAND_SLUG)}
LIMIT 1;
`;
  return runPsqlText(sql).trim();
}

function upsertSnapshot(brandId, payload) {
  const sql = `
INSERT INTO ${SCHEMA}.dashboard_snapshots (
  brand_id, snapshot_date, scope_type, scope_key, payload
)
VALUES (
  ${sqlStr(brandId)},
  CURRENT_DATE,
  'brand',
  'all',
  ${sqlJson(payload)}::jsonb
)
ON CONFLICT (brand_id, snapshot_date, scope_type, scope_key)
DO UPDATE SET payload = EXCLUDED.payload, created_at = NOW();
`;
  runPsqlText(sql);
}

function severityFromRisk(value) {
  const lowered = String(value || '').toLowerCase();
  if (lowered === 'high') return 'high';
  if (lowered === 'medium') return 'medium';
  return 'low';
}

function humanizeTopic(value) {
  const labels = {
    delivery: 'Delivery friction',
    price_value: 'Price / value',
    staff_service: 'Staff service',
    branch_experience: 'Branch experience',
    menu_variety: 'Menu expectation',
    cleanliness: 'Cleanliness',
    location: 'Location / branch',
    general_buzz: 'General buzz',
  };
  return labels[String(value || '')] || titleCasePreserve(String(value || 'unknown'));
}

function titleCasePreserve(value) {
  return String(value || '')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
