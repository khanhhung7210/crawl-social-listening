import { MongoClient } from 'mongodb';

function buildMongoUri() {
  const rawUri = String(process.env.MONGO_URI || '').trim();
  if (rawUri) return rawUri;

  const host = (process.env.MONGO_HOST || 'localhost').trim();
  const port = (process.env.MONGO_PORT || '27018').trim();
  const dbName = (process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const user = String(process.env.MONGO_USER || '').trim();
  const password = String(process.env.MONGO_PASSWORD || '');
  const authSource = String(process.env.MONGO_AUTH_SOURCE || dbName).trim() || dbName;
  const appName = String(process.env.MONGO_APP_NAME || 'tblsocial-migration').trim() || 'tblsocial-migration';

  const credentials =
    user && password
      ? `${encodeURIComponent(user)}:${encodeURIComponent(password)}@`
      : '';

  const query = new URLSearchParams({
    authSource,
    appName,
  });

  return `mongodb://${credentials}${host}:${port}/${dbName}?${query.toString()}`;
}

function normalizeComments(value, fallback) {
  const source = Array.isArray(value) ? value : Array.isArray(fallback) ? fallback : [];
  return source
    .map((item) => {
      if (typeof item === 'string') return item.trim();
      if (item && typeof item === 'object') {
        return String(
          item.text ??
            item.comment_text ??
            item.message ??
            item.body ??
            item.content ??
            ''
        ).trim();
      }
      return String(item || '').trim();
    })
    .filter(Boolean);
}

function normalizeCommentsRaw(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}

function normalizeCreatedAtComment(doc) {
  const direct = String(doc.created_at_comment || '').trim();
  if (direct) return direct;
  return '';
}

function coalesce(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    if (typeof value === 'string' && !value.trim()) continue;
    return value;
  }
  return '';
}

function buildCanonicalDocument(doc) {
  const film_title = String(doc.film_title || doc.title || '').trim();
  const comments = normalizeCommentsRaw(doc.comments);
  const comments_ = normalizeComments(doc.comments_, comments);

  return {
    id: coalesce(doc.id, doc.post_id),
    platform: String(doc.platform || '').trim(),
    post_id: coalesce(doc.post_id, doc.id),
    page_id: coalesce(doc.page_id, ''),
    page_name: String(doc.page_name || '').trim(),
    post_text: String(doc.post_text || '').trim(),
    comments_: comments_,
    comments,
    created_at_comment: normalizeCreatedAtComment(doc),
    film_title,
  };
}

async function main() {
  const dbName = String(process.env.MONGO_DB || 'CRM').trim() || 'CRM';
  const sourceCollectionName =
    String(process.env.MONGO_SOURCE_COLLECTION || process.env.MONGO_COLLECTION || 'social').trim() ||
    'social';
  const targetCollectionName =
    String(process.env.MONGO_TARGET_COLLECTION || process.env.MONGO_SOCIAL_COLLECTION || 'tblSocial').trim() ||
    'tblSocial';

  const client = new MongoClient(buildMongoUri());
  await client.connect();

  try {
    const db = client.db(dbName);
    const sourceCollection = db.collection(sourceCollectionName);
    const targetCollection = db.collection(targetCollectionName);
    const migrationFlagField =
      String(process.env.MIGRATION_FLAG_FIELD || 'migrated_to_tblsocial').trim() || 'migrated_to_tblsocial';
    const migrationAtField =
      String(process.env.MIGRATION_AT_FIELD || 'migrated_to_tblsocial_at').trim() || 'migrated_to_tblsocial_at';
    const cursor = sourceCollection.find(
      {
        [migrationFlagField]: { $ne: true },
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
          comments: 1,
          comments_: 1,
          created_at_comment: 1,
          film_title: 1,
          title: 1,
        },
      }
    );

    let scanned = 0;
    let upserted = 0;
    let modified = 0;
    let flagged = 0;
    const targetOps = [];
    const sourceOps = [];

    for await (const doc of cursor) {
      scanned += 1;

      const canonical = buildCanonicalDocument(doc);
      if (!canonical.platform || canonical.post_id === '' || canonical.post_id === null) {
        continue;
      }

      targetOps.push({
        updateOne: {
          filter: {
            platform: canonical.platform,
            post_id: canonical.post_id,
          },
          update: {
            $set: canonical,
            $unset: {
              title: '',
              post_created_at: '',
              post_keyword_match: '',
              parent_keyword_match: '',
              post_url: '',
              source: '',
              source_file: '',
              synced_at: '',
              updated_at: '',
            },
          },
          upsert: true,
        },
      });

      sourceOps.push({
        updateOne: {
          filter: { _id: doc._id },
          update: {
            $set: {
              [migrationFlagField]: true,
              [migrationAtField]: new Date().toISOString(),
            },
          },
        },
      });

      if (targetOps.length === 500) {
        const result = await targetCollection.bulkWrite(targetOps, { ordered: false });
        upserted += result.upsertedCount;
        modified += result.modifiedCount;
        targetOps.length = 0;

        const sourceResult = await sourceCollection.bulkWrite(sourceOps, { ordered: false });
        flagged += sourceResult.modifiedCount;
        sourceOps.length = 0;
      }
    }

    if (targetOps.length) {
      const result = await targetCollection.bulkWrite(targetOps, { ordered: false });
      upserted += result.upsertedCount;
      modified += result.modifiedCount;

      const sourceResult = await sourceCollection.bulkWrite(sourceOps, { ordered: false });
      flagged += sourceResult.modifiedCount;
    }

    console.log(
      JSON.stringify(
        {
          db: dbName,
          source_collection: sourceCollectionName,
          target_collection: targetCollectionName,
          scanned,
          upserted,
          modified,
          flagged,
          migration_flag_field: migrationFlagField,
          migration_at_field: migrationAtField,
        },
        null,
        2
      )
    );
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
