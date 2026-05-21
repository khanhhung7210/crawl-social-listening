import { MongoClient } from 'mongodb';
import { writeFileSync, mkdirSync } from 'fs';
import { resolve } from 'path';

const TARGET_TITLES = [
  'Bonchon Vietnam',
  'Don Chicken Vietnam',
  'Popeyes Viet Nam',
  'Jollibee Vietnam',
];

const POSITIVE_WORDS = [
  'hay',
  'đỉnh',
  'tuyệt',
  'ok',
  'thích',
  'ngon',
  'rất ngon',
  'ngon lắm',
  'ngon quá',
  'giòn',
  'giòn rụm',
  'giòn ngon',
  'đậm vị',
  'vừa miệng',
  'hợp vị',
  'thơm',
  'chất lượng',
  'ổn áp',
  'đáng tiền',
  'giá hợp lý',
  'phục vụ tốt',
  'nhân viên dễ thương',
  'nhân viên nhiệt tình',
  'giao hàng nhanh',
  'sẽ quay lại',
  'mê luôn',
  'mê xỉu',
];

const NEGATIVE_WORDS = [
  'dở',
  'tệ',
  'chán',
  'nhảm',
  'fail',
  'không ngon',
  'không hợp',
  'dở ẹc',
  'mặn',
  'quá mặn',
  'nhạt',
  'khô',
  'nguội',
  'tanh',
  'hôi dầu',
  'ngấy',
  'ít sốt',
  'nhân viên thái độ',
  'phục vụ chậm',
  'giao hàng chậm',
  'đợi lâu',
  'giá cao',
  'đắt',
  'không đáng tiền',
  'thất vọng',
  'tệ quá',
  'rác',
  'trash',
];

function buildMongoUri() {
  const rawUri = (process.env.MONGO_URI || '').trim();
  if (rawUri) return rawUri;

  const host = (process.env.MONGO_HOST || 'localhost').trim();
  const port = (process.env.MONGO_PORT || '27018').trim();
  const dbName = (process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const user = (process.env.MONGO_USER || '').trim();
  const password = process.env.MONGO_PASSWORD || '';
  const authSource = (process.env.MONGO_AUTH_SOURCE || dbName).trim() || dbName;
  const appName = (process.env.MONGO_APP_NAME || 'facebook-sentiment-job').trim() || 'facebook-sentiment-job';

  const query = new URLSearchParams({
    directConnection: 'true',
    appName,
  });

  if (user || password) {
    query.set('authSource', authSource);
    return `mongodb://${encodeURIComponent(user)}:${encodeURIComponent(password)}@${host}:${port}/${dbName}?${query.toString()}`;
  }

  return `mongodb://${host}:${port}/${dbName}?${query.toString()}`;
}

function normalizeText(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/http\S+/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractCommentText(comment) {
  if (typeof comment === 'string') return comment;
  if (comment && typeof comment === 'object') {
    return String(comment.text ?? comment.comment_text ?? comment.message ?? comment.body ?? comment.content ?? '');
  }
  return '';
}

function sentiment(text) {
  const pos = POSITIVE_WORDS.reduce((count, word) => count + (text.includes(word) ? 1 : 0), 0);
  const neg = NEGATIVE_WORDS.reduce((count, word) => count + (text.includes(word) ? 1 : 0), 0);

  if (pos > neg) return 'positive';
  if (neg > pos) return 'negative';
  return 'neutral';
}

function safeRatio(numerator, denominator) {
  return denominator ? numerator / denominator : 0;
}

function createEmptyPostAggregate(row) {
  return {
    title: row.title,
    platform: row.platform,
    post_id: row.post_id,
    page_id: row.page_id,
    page_name: row.page_name,
    post_text: row.post_text,
    total_comments: 0,
    positive: 0,
    negative: 0,
    neutral: 0,
    positive_ratio: 0,
    negative_ratio: 0,
  };
}

function createEmptyFilmAggregate(row) {
  return {
    title: row.title,
    platform: row.platform,
    total_comments: 0,
    positive: 0,
    negative: 0,
    neutral: 0,
    positive_ratio: 0,
    negative_ratio: 0,
    buzz_score: 0,
  };
}

function normalizeTitle(raw) {
  return String(raw || '').trim();
}

async function main() {
  const dbName = (process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const socialCollectionName = (process.env.MONGO_SOCIAL_COLLECTION || process.env.SOCIAL_COLLECTION_NAME || 'tblSocial').trim() || 'tblSocial';
  const sentimentCollectionName = (process.env.MONGO_SENTIMENT_COLLECTION || process.env.SENTIMENT_COLLECTION_NAME || 'tblSentiment').trim() || 'tblSentiment';

  const client = new MongoClient(buildMongoUri());
  await client.connect();

  try {
    const db = client.db(dbName);
    const collection = db.collection(socialCollectionName);
    const sentimentCollection = db.collection(sentimentCollectionName);

    const query = {
      platform: 'facebook',
      $or: [{ title: { $in: TARGET_TITLES } }, { film_title: { $in: TARGET_TITLES } }],
    };

    const rows = await collection
      .find(query, {
        projection: {
          _id: 0,
          id: 1,
          platform: 1,
          post_id: 1,
          page_id: 1,
          page_name: 1,
          post_text: 1,
          title: 1,
          film_title: 1,
          comments_: 1,
          comments: 1,
        },
      })
      .toArray();

    const commentRows = [];
    const byPost = new Map();
    const byFilmPlatform = new Map();

    for (const raw of rows) {
      const title = normalizeTitle(raw.title || raw.film_title);
      if (!title) continue;

      const platform = String(raw.platform || '').trim();
      const postId = String(raw.post_id || raw.id || '').trim();
      const pageId = String(raw.page_id || '').trim();
      const pageName = String(raw.page_name || '').trim();
      const postText = String(raw.post_text || '').trim();
      const sourceComments = Array.isArray(raw.comments_)
        ? raw.comments_
        : Array.isArray(raw.comments)
          ? raw.comments
          : [];

      for (const item of sourceComments) {
        const commentText = extractCommentText(item);
        const cleanComment = normalizeText(commentText);
        if (!cleanComment) continue;

        const polarity = sentiment(cleanComment);
        commentRows.push({
          id: raw.id ?? null,
          platform,
          post_id: postId,
          page_id: pageId,
          page_name: pageName,
          title,
          clean_comment: cleanComment,
          sentiment: polarity,
        });

        const postKey = `${platform}::${postId}`;
        const postAgg = byPost.get(postKey) || createEmptyPostAggregate({
          title,
          platform,
          post_id: postId,
          page_id: pageId,
          page_name: pageName,
          post_text: postText,
        });

        postAgg.total_comments += 1;
        postAgg[polarity] += 1;
        byPost.set(postKey, postAgg);

        const filmKey = `${title}::${platform}`;
        const filmAgg = byFilmPlatform.get(filmKey) || createEmptyFilmAggregate({ title, platform });
        filmAgg.total_comments += 1;
        filmAgg[polarity] += 1;
        byFilmPlatform.set(filmKey, filmAgg);
      }
    }

    const postSummary = Array.from(byPost.values())
      .map((row) => ({
        ...row,
        positive_ratio: safeRatio(row.positive, row.total_comments),
        negative_ratio: safeRatio(row.negative, row.total_comments),
      }))
      .sort((a, b) => b.total_comments - a.total_comments);

    const maxComments = Math.max(...Array.from(byFilmPlatform.values()).map((row) => row.total_comments), 0);

    const filmSummary = Array.from(byFilmPlatform.values())
      .map((row) => ({
        ...row,
        positive_ratio: safeRatio(row.positive, row.total_comments),
        negative_ratio: safeRatio(row.negative, row.total_comments),
        buzz_score:
          0.7 * safeRatio(row.positive, row.total_comments) +
          0.3 * safeRatio(row.total_comments, maxComments),
      }))
      .sort((a, b) => {
        if (b.buzz_score !== a.buzz_score) return b.buzz_score - a.buzz_score;
        return b.total_comments - a.total_comments;
      });

    if (filmSummary.length) {
      const bulkOps = filmSummary.map((row) => ({
        updateOne: {
          filter: {
            platform: row.platform,
            $or: [{ title: row.title }, { film_title: row.title }],
          },
          update: {
            $set: {
              platform: row.platform,
              total_comments: row.total_comments,
              positive: row.positive,
              negative: row.negative,
              neutral: row.neutral,
              positive_ratio: row.positive_ratio,
              negative_ratio: row.negative_ratio,
              buzz_score: row.buzz_score,
              title: row.title,
              film_title: row.title,
              updated_at: new Date().toISOString(),
              source: 'tblSocial_keyword_sentiment',
            },
          },
          upsert: true,
        },
      }));

      await sentimentCollection.bulkWrite(bulkOps, { ordered: false });
    }

    const outputDir = resolve(process.cwd(), 'tmp', 'brand-sentiment');
    mkdirSync(outputDir, { recursive: true });

    writeFileSync(resolve(outputDir, 'comments.json'), JSON.stringify(commentRows, null, 2), 'utf8');
    writeFileSync(resolve(outputDir, 'post_summary.json'), JSON.stringify(postSummary, null, 2), 'utf8');
    writeFileSync(resolve(outputDir, 'film_summary.json'), JSON.stringify(filmSummary, null, 2), 'utf8');

    console.log(
      JSON.stringify(
        {
          db: dbName,
          social_collection: socialCollectionName,
          sentiment_collection: sentimentCollectionName,
          titles: TARGET_TITLES,
          matched_posts: rows.length,
          classified_comments: commentRows.length,
          upserted_sentiment_rows: filmSummary.length,
          output_dir: outputDir,
        },
        null,
        2,
      ),
    );
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
