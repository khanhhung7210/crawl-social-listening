import { MongoClient } from 'mongodb';
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'fs';
import { resolve } from 'path';
import { createHash } from 'crypto';

const POSITIVE_WORDS = [
  'hay',
  'dinh',
  'đỉnh',
  'tuyet',
  'tuyệt',
  'ok',
  'thich',
  'thích',
  'ngon',
  'rat ngon',
  'rất ngon',
  'ngon lam',
  'ngon lắm',
  'ngon qua',
  'ngon quá',
  'gion',
  'giòn',
  'gion rum',
  'giòn rụm',
  'gion ngon',
  'giòn ngon',
  'dam vi',
  'đậm vị',
  'vua mieng',
  'vừa miệng',
  'hop vi',
  'hợp vị',
  'thom',
  'thơm',
  'chat luong',
  'chất lượng',
  'on ap',
  'ổn áp',
  'dang tien',
  'đáng tiền',
  'gia hop ly',
  'giá hợp lý',
  'phuc vu tot',
  'phục vụ tốt',
  'nhan vien de thuong',
  'nhân viên dễ thương',
  'nhan vien nhiet tinh',
  'nhân viên nhiệt tình',
  'giao hang nhanh',
  'giao hàng nhanh',
  'se quay lai',
  'sẽ quay lại',
  'me luon',
  'mê luôn',
  'me xiu',
  'mê xỉu',
];

const NEGATIVE_WORDS = [
  'do',
  'dở',
  'te',
  'tệ',
  'chan',
  'chán',
  'nham',
  'nhảm',
  'fail',
  'khong ngon',
  'không ngon',
  'khong hop',
  'không hợp',
  'do ec',
  'dở ẹc',
  'man',
  'mặn',
  'qua man',
  'quá mặn',
  'nhat',
  'nhạt',
  'kho',
  'khô',
  'nguoi',
  'nguội',
  'tanh',
  'hoi dau',
  'hôi dầu',
  'ngay',
  'ngấy',
  'it sot',
  'ít sốt',
  'nhan vien thai do',
  'nhân viên thái độ',
  'phuc vu cham',
  'phục vụ chậm',
  'giao hang cham',
  'giao hàng chậm',
  'doi lau',
  'đợi lâu',
  'gia cao',
  'giá cao',
  'dat',
  'đắt',
  'khong dang tien',
  'không đáng tiền',
  'that vong',
  'thất vọng',
  'te qua',
  'tệ quá',
  'rac',
  'rác',
  'trash',
];

function buildMongoUri() {
  const rawUri = String(process.env.MONGO_URI || '').trim();
  if (rawUri) return rawUri;

  const host = String(process.env.MONGO_HOST || 'localhost').trim() || 'localhost';
  const port = String(process.env.MONGO_PORT || '27018').trim() || '27018';
  const dbName = String(process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const user = String(process.env.MONGO_USER || '').trim();
  const password = String(process.env.MONGO_PASSWORD || '');
  const authSource = String(process.env.MONGO_AUTH_SOURCE || dbName).trim() || dbName;
  const appName =
    String(process.env.MONGO_APP_NAME || 'tblsocial-sentiment-unsynced-job').trim() ||
    'tblsocial-sentiment-unsynced-job';

  const query = new URLSearchParams({
    directConnection: 'true',
    appName,
  });

  if (user && password) {
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

function chunkArray(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function commentHash(text) {
  return createHash('sha1').update(text).digest('hex');
}

function loadCache(cachePath) {
  if (!existsSync(cachePath)) return {};
  try {
    const payload = JSON.parse(readFileSync(cachePath, 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch {
    return {};
  }
}

function saveCache(cachePath, cache) {
  writeFileSync(cachePath, JSON.stringify(cache, null, 2), 'utf8');
}

function extractResponseText(payload) {
  if (typeof payload.output_text === 'string' && payload.output_text.trim()) {
    return payload.output_text.trim();
  }

  const outputs = Array.isArray(payload.output) ? payload.output : [];
  for (const item of outputs) {
    const contents = Array.isArray(item.content) ? item.content : [];
    for (const content of contents) {
      if (typeof content.text === 'string' && content.text.trim()) {
        return content.text.trim();
      }
    }
  }
  return '';
}

async function classifyCommentsWithOpenAI(comments, options) {
  const {
    apiKey,
    model,
    batchSize,
    cachePath,
  } = options;

  const cache = loadCache(cachePath);
  const results = new Map();
  const pending = [];

  for (const text of comments) {
    const key = commentHash(text);
    const cached = cache[key];
    if (cached && ['positive', 'negative', 'neutral'].includes(cached.sentiment)) {
      results.set(text, cached);
      continue;
    }
    pending.push({ key, text });
  }

  if (!pending.length) {
    return { results, cacheHits: comments.length, apiClassified: 0 };
  }

  let apiClassified = 0;
  const batches = chunkArray(pending, batchSize);
  for (const batch of batches) {
    const inputLines = batch.map((item, index) => `${index + 1}. ${item.text}`);
    const response = await fetch('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        input: [
          {
            role: 'system',
            content: [
              {
                type: 'input_text',
                text:
                  'Classify each comment sentiment as positive, negative, or neutral. Return strict JSON only. Consider slang, sarcasm, mixed Vietnamese-English, and short casual comments. Do not explain outside JSON.',
              },
            ],
          },
          {
            role: 'user',
            content: [
              {
                type: 'input_text',
                text: `Return JSON with this exact shape: {"items":[{"index":1,"sentiment":"positive|negative|neutral","confidence":0.0,"reason":"short"}]}. Comments:\n${inputLines.join('\n')}`,
              },
            ],
          },
        ],
        text: {
          format: {
            type: 'json_schema',
            name: 'comment_sentiment_batch',
            strict: true,
            schema: {
              type: 'object',
              additionalProperties: false,
              properties: {
                items: {
                  type: 'array',
                  items: {
                    type: 'object',
                    additionalProperties: false,
                    properties: {
                      index: { type: 'integer' },
                      sentiment: {
                        type: 'string',
                        enum: ['positive', 'negative', 'neutral'],
                      },
                      confidence: { type: 'number' },
                      reason: { type: 'string' },
                    },
                    required: ['index', 'sentiment', 'confidence', 'reason'],
                  },
                },
              },
              required: ['items'],
            },
          },
        },
      }),
    });

    if (!response.ok) {
      throw new Error(`OpenAI API error ${response.status}: ${await response.text()}`);
    }

    const payload = await response.json();
    const rawText = extractResponseText(payload);
    const parsed = JSON.parse(rawText);
    const items = Array.isArray(parsed.items) ? parsed.items : [];

    for (const item of items) {
      const batchIndex = Number(item.index) - 1;
      const source = batch[batchIndex];
      if (!source) continue;
      const record = {
        sentiment: item.sentiment,
        confidence: Number(item.confidence || 0),
        reason: String(item.reason || '').trim(),
        provider: 'openai',
        model,
      };
      cache[source.key] = record;
      results.set(source.text, record);
      apiClassified += 1;
    }
  }

  saveCache(cachePath, cache);
  return { results, cacheHits: comments.length - pending.length, apiClassified };
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
  const dbName = String(process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const socialCollectionName =
    String(process.env.MONGO_SOCIAL_COLLECTION || process.env.SOCIAL_COLLECTION_NAME || 'tblSocial').trim() ||
    'tblSocial';
  const sentimentCollectionName =
    String(process.env.MONGO_SENTIMENT_COLLECTION || process.env.SENTIMENT_COLLECTION_NAME || 'tblSentiment').trim() ||
    'tblSentiment';
  const syncField = String(process.env.SYNC_FIELD || 'synctblSentiment').trim() || 'synctblSentiment';
  const syncAtField = String(process.env.SYNC_AT_FIELD || 'synctblSentimentAt').trim() || 'synctblSentimentAt';
  const openAiApiKey = String(process.env.OPENAI_API_KEY || '').trim();
  const openAiModel = String(process.env.OPENAI_MODEL || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
  const openAiBatchSize = Math.max(1, Number(process.env.OPENAI_BATCH_SIZE || 20));

  const client = new MongoClient(buildMongoUri());
  await client.connect();

  try {
    const db = client.db(dbName);
    const collection = db.collection(socialCollectionName);
    const sentimentCollection = db.collection(sentimentCollectionName);

    const outputDir = resolve(process.cwd(), 'tmp', 'tblsocial-sentiment');
    mkdirSync(outputDir, { recursive: true });
    const cachePath = resolve(outputDir, 'openai_comment_cache.json');

    const rows = await collection
      .find(
        {
          [syncField]: { $ne: true },
        },
        {
          projection: {
            _id: 1,
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
        },
      )
      .toArray();

    const processedIds = [];
    const commentRows = [];
    const byPost = new Map();
    const byFilmPlatform = new Map();
    const uniqueComments = [];
    const uniqueCommentSet = new Set();

    for (const raw of rows) {
      processedIds.push(raw._id);

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
        if (!uniqueCommentSet.has(cleanComment)) {
          uniqueCommentSet.add(cleanComment);
          uniqueComments.push(cleanComment);
        }
      }
    }

    let openAiResults = new Map();
    let openAiCacheHits = 0;
    let openAiApiClassified = 0;
    let classifierMode = 'keywords';

    if (openAiApiKey && uniqueComments.length) {
      try {
        const openAiClassification = await classifyCommentsWithOpenAI(uniqueComments, {
          apiKey: openAiApiKey,
          model: openAiModel,
          batchSize: openAiBatchSize,
          cachePath,
        });
        openAiResults = openAiClassification.results;
        openAiCacheHits = openAiClassification.cacheHits;
        openAiApiClassified = openAiClassification.apiClassified;
        classifierMode = 'openai';
      } catch (error) {
        console.error(`openai sentiment fallback to keywords: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

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

        const classification = openAiResults.get(cleanComment);
        const polarity = classification?.sentiment || sentiment(cleanComment);
        commentRows.push({
          id: raw.id ?? null,
          platform,
          post_id: postId,
          page_id: pageId,
          page_name: pageName,
          title,
          clean_comment: cleanComment,
          sentiment: polarity,
          sentiment_provider: classification?.provider || 'keywords',
          sentiment_model: classification?.model || '',
          sentiment_confidence: classification?.confidence ?? null,
          sentiment_reason: classification?.reason || '',
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
              source: 'tblsocial_sentiment_unsynced_job',
            },
          },
          upsert: true,
        },
      }));

      await sentimentCollection.bulkWrite(bulkOps, { ordered: false });
    }

    if (processedIds.length) {
      await collection.updateMany(
        { _id: { $in: processedIds } },
        {
          $set: {
            [syncField]: true,
            [syncAtField]: new Date().toISOString(),
          },
        },
      );
    }

    writeFileSync(resolve(outputDir, 'comments.json'), JSON.stringify(commentRows, null, 2), 'utf8');
    writeFileSync(resolve(outputDir, 'post_summary.json'), JSON.stringify(postSummary, null, 2), 'utf8');
    writeFileSync(resolve(outputDir, 'film_summary.json'), JSON.stringify(filmSummary, null, 2), 'utf8');

    console.log(
      JSON.stringify(
        {
          db: dbName,
          social_collection: socialCollectionName,
          sentiment_collection: sentimentCollectionName,
          matched_posts: rows.length,
          unique_comments: uniqueComments.length,
          classified_comments: commentRows.length,
          upserted_sentiment_rows: filmSummary.length,
          marked_synced_posts: processedIds.length,
          classifier_mode: classifierMode,
          openai_cache_hits: openAiCacheHits,
          openai_api_classified: openAiApiClassified,
          openai_model: openAiApiKey ? openAiModel : '',
          sync_field: syncField,
          sync_at_field: syncAtField,
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
