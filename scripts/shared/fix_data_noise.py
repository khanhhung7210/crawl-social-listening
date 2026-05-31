#!/usr/bin/env python3
"""
Fix data noise - Filter irrelevant mentions
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import psycopg2
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=True)
    import psycopg2

def get_db_connection(database="meili_dashboard"):
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host="localhost",
        database=database,
        user="khangnhq",
        password=""
    )

# Relevance keywords
BRAND_KEYWORDS = [
    'meili', '美麗', 'meilimibodailoan'
]

COMPETITOR_KEYWORDS = [
    'yutang', 'yu tang', '御堂',
    'a bảo', 'a beo', 'abao', '阿寶',
    'lão đại', 'vua mi', 'vua mì'
]

RELEVANCE_KEYWORDS = [
    # Food quality
    'ngon', 'tệ', 'dở', 'tốt', 'chất lượng', 'tươi', 'thơm', 'mùi',
    'dai', 'mềm', 'cứng', 'nhạt', 'mặn', 'cay', 'ngọt',

    # Service
    'phục vụ', 'service', 'nhân viên', 'đặt bàn', 'booking',
    'giao hàng', 'delivery', 'ship', 'đặt', 'order',

    # Price/value
    'giá', 'tiền', 'rẻ', 'mắc', 'đắt', 'hợp lý', 'ok', 'đáng',
    'combo', 'set', 'deal', 'promotion', 'khuyến mãi',

    # Location
    'quán', 'tiệm', 'chi nhánh', 'branch', 'địa chỉ', 'ở đâu',
    'gò vấp', 'quận 7', 'bình thạnh', 'nhiêu tứ',

    # Experience
    'không gian', 'view', 'đẹp', 'sạch', 'thoáng', 'ồn',
    'chờ lâu', 'nhanh', 'lâu', 'đông', 'vắng',

    # Recommendation
    'recommend', 'nên', 'thử', 'đi', 'ghé', 'ủng hộ',
    'quay lại', 'lần sau', 'không quay'
]

def is_relevant_mention(text):
    """
    Check if mention is relevant to restaurant/food discussion

    Returns:
        - 'brand': Has brand mention (Meili or competitor)
        - 'relevant': Has food/service keywords
        - 'noise': Irrelevant comment
    """
    if not text:
        return 'noise'

    text_lower = text.lower()

    # Too short = noise
    if len(text.strip()) < 10:
        return 'noise'

    # Check brand mention
    for brand in BRAND_KEYWORDS + COMPETITOR_KEYWORDS:
        if brand.lower() in text_lower:
            return 'brand'

    # Check relevance keywords
    keyword_count = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text_lower)

    if keyword_count >= 2:  # At least 2 relevant keywords
        return 'relevant'

    return 'noise'

def analyze_noise():
    """Analyze current data noise levels"""
    conn = get_db_connection("meili_dashboard")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            mention_id,
            platform,
            content_type,
            content_text
        FROM meili_dashboard.mentions
        WHERE platform IN ('tiktok', 'facebook', 'instagram')
    """)

    results = {
        'brand': 0,
        'relevant': 0,
        'noise': 0
    }

    noise_examples = []

    for row in cursor.fetchall():
        mention_id, platform, content_type, text = row
        relevance = is_relevant_mention(text)
        results[relevance] += 1

        if relevance == 'noise' and len(noise_examples) < 20:
            noise_examples.append({
                'platform': platform,
                'type': content_type,
                'text': text[:100]
            })

    total = sum(results.values())

    print("=" * 60)
    print("DATA NOISE ANALYSIS")
    print("=" * 60)
    print(f"\nTotal mentions: {total}")
    print(f"\nBrand mentions:    {results['brand']:4d} ({results['brand']/total*100:.1f}%)")
    print(f"Relevant mentions: {results['relevant']:4d} ({results['relevant']/total*100:.1f}%)")
    print(f"Noise mentions:    {results['noise']:4d} ({results['noise']/total*100:.1f}%)")

    print(f"\n{'='*60}")
    print("NOISE EXAMPLES:")
    print("=" * 60)
    for ex in noise_examples[:10]:
        print(f"\n[{ex['platform']}] {ex['type']}")
        print(f"  {ex['text']}")

    cursor.close()
    conn.close()

    return results

def mark_relevance_in_db():
    """Add relevance flag to database"""
    conn = get_db_connection("meili_dashboard")
    cursor = conn.cursor()

    # Add column if not exists
    cursor.execute("""
        ALTER TABLE meili_dashboard.mentions
        ADD COLUMN IF NOT EXISTS relevance_type TEXT DEFAULT 'unknown';
    """)
    conn.commit()

    # Update all mentions
    cursor.execute("""
        SELECT mention_id, content_text
        FROM meili_dashboard.mentions
        WHERE platform IN ('tiktok', 'facebook', 'instagram')
    """)

    updates = []
    for row in cursor.fetchall():
        mention_id, text = row
        relevance = is_relevant_mention(text)
        updates.append((relevance, mention_id))

    # Batch update
    cursor.executemany("""
        UPDATE meili_dashboard.mentions
        SET relevance_type = %s
        WHERE mention_id = %s
    """, updates)

    conn.commit()

    print(f"\n✅ Updated {len(updates)} mentions with relevance flags")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    print("Analyzing data noise...")
    results = analyze_noise()

    print("\n" + "="*60)
    response = input("\nMark relevance in database? (y/n): ")
    if response.lower() == 'y':
        mark_relevance_in_db()
        print("\n✅ Done! Now you can filter:")
        print("   WHERE relevance_type IN ('brand', 'relevant')")
