"""
Scrape Play Store reviews for Myntra and Ajio, then filter Myntra reviews
by return/apparel-quality-related keywords.

Target Outputs:
- /data/myntra_reviews.csv (3000 newest reviews)
- /data/ajio_reviews.csv (1000 newest reviews)
- /data/myntra_filtered.csv (Filtered Myntra reviews matching keywords)
Columns: [review_id, text, rating, date]
"""

import os
import sys
from pathlib import Path
import pandas as pd
# pyrefly: ignore [missing-import]
from google_play_scraper import Sort, reviews

# Target directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# App configurations
APPS = {
    "myntra": {
        "app_id": "com.myntra.android",
        "count": 3000,
        "filename": "myntra_reviews.csv",
    },
    "ajio": {
        "app_id": "com.ril.ajio",
        "count": 1000,
        "filename": "ajio_reviews.csv",
    },
}

# Keywords for filtering Myntra reviews
KEYWORDS = [
    "return",
    "refund",
    "size",
    "fit",
    "exchange",
    "wrong item",
    "quality",
    "damaged",
]


def scrape_app_reviews(app_id: str, count: int, country: str = "in", lang: str = "en") -> pd.DataFrame:
    """
    Fetch newest reviews from Google Play Store for a given app.
    
    Returns DataFrame with columns: ['review_id', 'text', 'rating', 'date']
    """
    print(f"[*] Scraping {count} newest reviews for {app_id} (country='{country}', lang='{lang}')...")
    
    raw_reviews, _ = reviews(
        app_id,
        lang=lang,
        country=country,
        sort=Sort.NEWEST,
        count=count,
        filter_score_with=None,
    )
    
    print(f"[+] Successfully fetched {len(raw_reviews)} reviews.")
    
    df = pd.DataFrame(raw_reviews)
    
    # Rename columns to standard requested schema
    column_mapping = {
        "reviewId": "review_id",
        "content": "text",
        "score": "rating",
        "at": "date",
    }
    
    df = df.rename(columns=column_mapping)
    df = df[["review_id", "text", "rating", "date"]]
    
    return df


def filter_reviews_by_keywords(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """
    Filter reviews whose text contains any of the specified keywords (case-insensitive).
    """
    # Create regex pattern for any keyword match
    pattern = "|".join(keywords)
    mask = df["text"].str.contains(pattern, case=False, na=False)
    filtered = df[mask].copy()
    return filtered


def print_keyword_breakdown(df: pd.DataFrame, keywords: list[str]) -> None:
    """Print count of reviews matching each individual keyword."""
    print("\n--- Keyword Frequency Breakdown (Myntra Filtered) ---")
    for kw in keywords:
        kw_count = df["text"].str.contains(kw, case=False, na=False).sum()
        print(f"  - '{kw}': {kw_count} reviews")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Scrape Myntra
    myntra_cfg = APPS["myntra"]
    myntra_df = scrape_app_reviews(
        app_id=myntra_cfg["app_id"],
        count=myntra_cfg["count"],
        country="in",
        lang="en",
    )
    myntra_path = DATA_DIR / myntra_cfg["filename"]
    myntra_df.to_csv(myntra_path, index=False, encoding="utf-8")
    print(f"[+] Saved Myntra reviews to: {myntra_path}")

    # 2. Scrape Ajio
    ajio_cfg = APPS["ajio"]
    ajio_df = scrape_app_reviews(
        app_id=ajio_cfg["app_id"],
        count=ajio_cfg["count"],
        country="in",
        lang="en",
    )
    ajio_path = DATA_DIR / ajio_cfg["filename"]
    ajio_df.to_csv(ajio_path, index=False, encoding="utf-8")
    print(f"[+] Saved Ajio reviews to: {ajio_path}")

    # 3. Filter Myntra Reviews
    print(f"\n[*] Filtering Myntra reviews using keywords: {KEYWORDS}")
    filtered_df = filter_reviews_by_keywords(myntra_df, KEYWORDS)
    filtered_path = DATA_DIR / "myntra_filtered.csv"
    filtered_df.to_csv(filtered_path, index=False, encoding="utf-8")
    print(f"[+] Saved filtered Myntra reviews to: {filtered_path}")

    # Summary
    print("\n================ SUMMARY ================")
    print(f"Total Myntra reviews scraped : {len(myntra_df)}")
    print(f"Total Ajio reviews scraped   : {len(ajio_df)}")
    print(f"Filtered Myntra reviews      : {len(filtered_df)} ({len(filtered_df)/len(myntra_df)*100:.1f}% of total)")
    print(f"Myntra date range            : {myntra_df['date'].min()} to {myntra_df['date'].max()}")
    print(f"Ajio date range              : {ajio_df['date'].min()} to {ajio_df['date'].max()}")
    
    print_keyword_breakdown(filtered_df, KEYWORDS)
    print("=========================================\n")


if __name__ == "__main__":
    main()
