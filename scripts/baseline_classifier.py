"""
Rule-Based Baseline Classifier for Customer Return Reviews.

Implements a naive first-match keyword classifier across the 6 categories
defined in /docs/taxonomy.md.

For each category, checks 2-4 obvious keywords.
- If a review matches multiple categories, assigns the first match.
- If no keywords match, assigns 'Unclassified'.
Saves output with 'baseline_category' to /data/myntra_tagged.csv.
"""

import sys
from pathlib import Path
import pandas as pd

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
FILTERED_PATH = BASE_DIR / "data" / "myntra_filtered.csv"
CLASSIFIED_PATH = BASE_DIR / "data" / "myntra_classified.csv"
GROUND_TRUTH_PATH = BASE_DIR / "data" / "ground_truth.csv"
OUTPUT_TAGGED_PATH = BASE_DIR / "data" / "myntra_tagged.csv"

# Category keyword mappings derived from taxonomy definitions & obvious terms
CATEGORY_RULES = [
    (
        "Size & Fit Discrepancy",
        ["size", "fit", "tight", "loose"],
    ),
    (
        "Defective, Damaged & Counterfeit Items",
        ["quality", "material", "stitching", "damaged", "defective", "torn", "fake"],
    ),
    (
        "Incorrect / Wrong Item Delivered",
        ["wrong", "incorrect", "different item", "different product"],
    ),
    (
        "Return & Exchange Logistics & QC Friction",
        ["pickup", "pick up", "exchange", "courier", "delivery boy", "agent"],
    ),
    (
        "Refund Processing & Settlement Disputes",
        ["refund", "money", "amount", "bank", "account"],
    ),
    (
        "Other / Not Return-Related",
        ["good", "best", "nice", "love", "awesome"],
    ),
]


def classify_review_baseline(text: str) -> str:
    """Classify review using simple first-match keyword rules."""
    if not isinstance(text, str) or not text.strip():
        return "Unclassified"
    
    text_lower = text.lower()
    for category_name, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in text_lower:
                return category_name
    return "Unclassified"


def run_baseline_classifier():
    print("=" * 80)
    print("RUNNING NAIVE RULE-BASED BASELINE CLASSIFIER")
    print("=" * 80)

    # 1. Load source data
    if CLASSIFIED_PATH.exists():
        print(f"[*] Loading classified dataset: {CLASSIFIED_PATH}")
        df = pd.read_csv(CLASSIFIED_PATH)
    else:
        print(f"[*] Loading filtered dataset: {FILTERED_PATH}")
        df = pd.read_csv(FILTERED_PATH)
        if "category" not in df.columns:
            df["category"] = "Unassigned"

    # Ensure notes column exists
    if "notes" not in df.columns:
        if "rationale" in df.columns:
            df["notes"] = df["rationale"]
        else:
            df["notes"] = ""

    # 2. Apply rule-based classification
    print("[*] Applying first-match keyword classification...")
    df["baseline_category"] = df["text"].apply(classify_review_baseline)

    # Organize column ordering
    preferred_cols = ["review_id", "text", "rating", "date", "category", "baseline_category", "notes"]
    final_cols = [c for c in preferred_cols if c in df.columns]
    for c in df.columns:
        if c not in final_cols:
            final_cols.append(c)

    df_output = df[final_cols]

    # 3. Save to /data/myntra_tagged.csv
    OUTPUT_TAGGED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_output.to_csv(OUTPUT_TAGGED_PATH, index=False, encoding="utf-8")
    print(f"[✓] Saved {len(df_output)} reviews to: {OUTPUT_TAGGED_PATH}")

    # 4. Print Distribution
    print("\n" + "-" * 45)
    print("BASELINE CATEGORY DISTRIBUTION")
    print("-" * 45)
    dist = df_output["baseline_category"].value_counts()
    for cat, count in dist.items():
        pct = (count / len(df_output)) * 100.0
        print(f"  {cat:<42} : {count:>3} ({pct:>5.1f}%)")

    # 5. Agreement with Primary Category (if present)
    if "category" in df_output.columns and (df_output["category"] != "Unassigned").any():
        matches = (df_output["baseline_category"] == df_output["category"]).sum()
        total = len(df_output)
        acc = (matches / total) * 100.0
        print("\n" + "-" * 45)
        print("BASELINE VS PRIMARY CATEGORY AGREEMENT")
        print("-" * 45)
        print(f"  Total Reviews Evaluated : {total}")
        print(f"  Exact Matches           : {matches}")
        print(f"  Baseline Agreement Rate : {acc:.2f}%")

    # 6. Agreement against Ground Truth (if exists)
    if GROUND_TRUTH_PATH.exists():
        df_gt = pd.read_csv(GROUND_TRUTH_PATH)
        gt_col = "manual_category" if "manual_category" in df_gt.columns else "category"
        merged = pd.merge(
            df_gt[["review_id", gt_col]],
            df_output[["review_id", "baseline_category"]],
            on="review_id",
        )
        if len(merged) > 0:
            gt_matches = (merged[gt_col] == merged["baseline_category"]).sum()
            gt_total = len(merged)
            gt_acc = (gt_matches / gt_total) * 100.0
            print("\n" + "-" * 45)
            print("BASELINE VS GROUND TRUTH AGREEMENT")
            print("-" * 45)
            print(f"  Overlapping GT Reviews  : {gt_total}")
            print(f"  Exact Matches           : {gt_matches}")
            print(f"  GT Baseline Agreement   : {gt_acc:.2f}%")
    print("=" * 80)


if __name__ == "__main__":
    run_baseline_classifier()
