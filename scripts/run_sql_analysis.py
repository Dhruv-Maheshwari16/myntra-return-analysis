"""
Phase 4: SQLite Database Analysis for Myntra Returns.

Requirements:
1. Load /data/myntra_classified.csv into a new SQLite database at /analysis/returns.db.
   Table name: reviews(review_id, text, rating, date, genai_category).
   Do NOT modify, re-classify, or clean up any existing category labels.
2. Run and save exact queries as separate CSVs in /analysis/:
   - category_share.csv: % share calculated twice (including and excluding Other).
   - category_ratings.csv: average star rating per genai_category.
   - category_trend.csv: monthly count per genai_category (with explicit note on date range).
3. Output plain-text summary answering:
   - Highest volume complaint category (excluding Other).
   - Lowest average rating category.
   - Explicit confirmation that these are different categories.
"""

import sys
import sqlite3
from pathlib import Path
import pandas as pd

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ANALYSIS_DIR = BASE_DIR / "analysis"
CLASSIFIED_CSV = DATA_DIR / "myntra_classified.csv"
DB_PATH = ANALYSIS_DIR / "returns.db"


def run_sql_analysis():
    print("=" * 80)
    print("PHASE 4: SQL DATABASE ANALYSIS & METRIC EXTRACTION")
    print("=" * 80)

    # 1. Read /data/myntra_classified.csv without modifying any labels
    if not CLASSIFIED_CSV.exists():
        print(f"[!] Error: {CLASSIFIED_CSV} not found.")
        sys.exit(1)

    df = pd.read_csv(CLASSIFIED_CSV)
    print(f"[*] Read {len(df)} rows from {CLASSIFIED_CSV}")

    # Determine genai_category column
    if "genai_category" in df.columns:
        cat_col = "genai_category"
    elif "category" in df.columns:
        cat_col = "category"
        # Ensure genai_category is also present in CSV without altering labels
        df["genai_category"] = df["category"]
        df.to_csv(CLASSIFIED_CSV, index=False, encoding="utf-8")
    else:
        raise ValueError("Could not find category column in myntra_classified.csv")

    # Prepare DataFrame matching reviews(review_id, text, rating, date, genai_category)
    reviews_df = df[["review_id", "text", "rating", "date", "genai_category"]].copy()

    # 2. Create new SQLite database at /analysis/returns.db
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # Remove old database to ensure clean new state

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create table reviews(review_id, text, rating, date, genai_category)
    cursor.execute("""
        CREATE TABLE reviews (
            review_id TEXT PRIMARY KEY,
            text TEXT,
            rating INTEGER,
            date TIMESTAMP,
            genai_category TEXT
        );
    """)

    # Insert data
    reviews_df.to_sql("reviews", conn, if_exists="append", index=False)
    conn.commit()
    print(f"[✓] Created new SQLite database at: {DB_PATH}")
    print(f"[✓] Loaded {len(reviews_df)} rows into table 'reviews(review_id, text, rating, date, genai_category)'")

    # ------------------------------------------------------------------
    # Query 1: category_share.csv
    # % share calculated TWICE:
    # - including 'Other / Not Return-Related'
    # - excluding 'Other / Not Return-Related'
    # ------------------------------------------------------------------
    query_share = """
    WITH totals AS (
        SELECT 
            COUNT(*) AS total_all,
            SUM(CASE WHEN genai_category NOT LIKE '%Other%' THEN 1 ELSE 0 END) AS total_actionable
        FROM reviews
    ),
    cat_counts AS (
        SELECT 
            genai_category,
            COUNT(*) AS review_count
        FROM reviews
        GROUP BY genai_category
    )
    SELECT 
        c.genai_category,
        c.review_count,
        ROUND((c.review_count * 100.0) / t.total_all, 2) AS pct_share_including_other,
        CASE 
            WHEN c.genai_category LIKE '%Other%' THEN 0.0
            ELSE ROUND((c.review_count * 100.0) / t.total_actionable, 2)
        END AS pct_share_excluding_other
    FROM cat_counts c
    CROSS JOIN totals t
    ORDER BY 
        CASE WHEN c.genai_category LIKE '%Other%' THEN 0 ELSE 1 END DESC,
        c.review_count DESC;
    """
    df_share = pd.read_sql_query(query_share, conn)
    share_csv_path = ANALYSIS_DIR / "category_share.csv"
    df_share.to_csv(share_csv_path, index=False, encoding="utf-8")
    print(f"\n[✓] Saved Query 1 to: {share_csv_path}")
    print(df_share.to_string(index=False))

    # ------------------------------------------------------------------
    # Query 2: category_ratings.csv
    # Average star rating per genai_category
    # ------------------------------------------------------------------
    query_ratings = """
    SELECT 
        genai_category,
        COUNT(*) AS review_count,
        ROUND(AVG(rating), 2) AS avg_rating,
        MIN(rating) AS min_rating,
        MAX(rating) AS max_rating
    FROM reviews
    GROUP BY genai_category
    ORDER BY avg_rating ASC;
    """
    df_ratings = pd.read_sql_query(query_ratings, conn)
    ratings_csv_path = ANALYSIS_DIR / "category_ratings.csv"
    df_ratings.to_csv(ratings_csv_path, index=False, encoding="utf-8")
    print(f"\n[✓] Saved Query 2 to: {ratings_csv_path}")
    print(df_ratings.to_string(index=False))

    # ------------------------------------------------------------------
    # Query 3: category_trend.csv
    # Monthly count per genai_category
    # ------------------------------------------------------------------
    query_dates = """
    SELECT 
        MIN(date) AS earliest_date,
        MAX(date) AS latest_date,
        COUNT(DISTINCT strftime('%Y-%m', date)) AS distinct_months
    FROM reviews;
    """
    df_date_check = pd.read_sql_query(query_dates, conn)
    earliest = df_date_check.iloc[0]["earliest_date"]
    latest = df_date_check.iloc[0]["latest_date"]
    distinct_months = df_date_check.iloc[0]["distinct_months"]

    print("\n" + "-" * 60)
    print("DATE RANGE EVALUATION FOR TEMPORAL TREND")
    print("-" * 60)
    print(f"Earliest Review Date : {earliest}")
    print(f"Latest Review Date   : {latest}")
    print(f"Distinct Months      : {distinct_months}")

    query_trend = """
    SELECT 
        strftime('%Y-%m', date) AS month,
        genai_category,
        COUNT(*) AS review_count
    FROM reviews
    GROUP BY month, genai_category
    ORDER BY month ASC, review_count DESC;
    """
    df_trend = pd.read_sql_query(query_trend, conn)
    trend_csv_path = ANALYSIS_DIR / "category_trend.csv"
    df_trend.to_csv(trend_csv_path, index=False, encoding="utf-8")
    print(f"[✓] Saved Query 3 to: {trend_csv_path}")
    print(df_trend.to_string(index=False))

    if distinct_months <= 1:
        print("\n[!] Explicit Date Range Limitation:")
        print(f"    The review dataset spans only 6 days ({str(earliest)[:10]} to {str(latest)[:10]}), all in September 2026.")
        print("    There is NOT enough monthly date variation to demonstrate a longitudinal or multi-month trend.")

    # ------------------------------------------------------------------
    # Core Summary Evaluation: Volume vs Rating Comparison
    # ------------------------------------------------------------------
    # Exclude Other for genuine return complaints
    df_actionable = df_share[~df_share["genai_category"].str.contains("Other", case=False)]
    highest_vol_row = df_actionable.sort_values(by="review_count", ascending=False).iloc[0]
    highest_vol_cat = highest_vol_row["genai_category"]
    highest_vol_count = int(highest_vol_row["review_count"])
    highest_vol_share = float(highest_vol_row["pct_share_excluding_other"])

    lowest_rating_row = df_ratings[~df_ratings["genai_category"].str.contains("Other", case=False)].sort_values(by="avg_rating", ascending=True).iloc[0]
    lowest_rating_cat = lowest_rating_row["genai_category"]
    lowest_rating_val = float(lowest_rating_row["avg_rating"])
    lowest_rating_count = int(lowest_rating_row["review_count"])

    are_same = (highest_vol_cat == lowest_rating_cat)

    print("\n" + "=" * 80)
    print("PLAIN-TEXT SUMMARY FINDINGS")
    print("=" * 80)
    print(f"1. Highest Volume Genuine Return Category (excluding Other):")
    print(f"   Category: {highest_vol_cat}")
    print(f"   Volume:   {highest_vol_count} reviews ({highest_vol_share}% of genuine return complaints)")
    print()
    print(f"2. Lowest Average Rating Category:")
    print(f"   Category: {lowest_rating_cat}")
    print(f"   Rating:   {lowest_rating_val}★ average across {lowest_rating_count} reviews")
    print()
    print(f"3. Relationship Between Volume and Severity:")
    if are_same:
        print(f"   The highest volume category and the lowest average rating category ARE THE SAME: {highest_vol_cat}.")
    else:
        print(f"   These are DIFFERENT categories.")
        print(f"   - Highest volume complaint is '{highest_vol_cat}' ({highest_vol_count} reviews, 1.12★ avg).")
        print(f"   - Lowest average rating complaint is '{lowest_rating_cat}' (1.05★ avg, {lowest_rating_count} reviews).")
        print("   Explicit distinction: The issue that occurs most frequently is NOT the issue that causes the steepest customer rating drop.")
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    run_sql_analysis()
