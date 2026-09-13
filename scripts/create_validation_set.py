"""
Create Validation Set by Randomly Sampling 100 Reviews.

Requirements:
- Input: /data/myntra_tagged.csv
- Sample 100 reviews randomly (reproducible seed)
- Rename existing `category` -> `ground_truth_category`
- Columns: review_id, text, ground_truth_category, baseline_category, genai_category
- Output: /data/validation_set.csv
- Print comparative evaluation & agreement rates for the 100 validation reviews
"""

import sys
from pathlib import Path
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
TAGGED_PATH = BASE_DIR / "data" / "myntra_tagged.csv"
VALIDATION_PATH = BASE_DIR / "data" / "validation_set.csv"


def create_validation_set(sample_size: int = 100, random_state: int = 42):
    print("=" * 80)
    print("CREATING VALIDATION SET (RANDOM SAMPLE OF 100 REVIEWS)")
    print("=" * 80)

    if not TAGGED_PATH.exists():
        print(f"[!] Error: {TAGGED_PATH} does not exist.")
        sys.exit(1)

    df = pd.read_csv(TAGGED_PATH)
    print(f"[*] Loaded {len(df)} reviews from: {TAGGED_PATH}")

    required_cols = ["review_id", "text", "category", "baseline_category", "genai_category"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[!] Error: Missing required columns in {TAGGED_PATH.name}: {missing}")
        sys.exit(1)

    # Randomly sample 100 reviews
    df_sample = df.sample(n=min(sample_size, len(df)), random_state=random_state).copy()

    # Rename category to ground_truth_category
    df_sample.rename(columns={"category": "ground_truth_category"}, inplace=True)

    # Select specified columns
    output_cols = ["review_id", "text", "ground_truth_category", "baseline_category", "genai_category"]
    df_validation = df_sample[output_cols].copy()

    # Save to /data/validation_set.csv
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_validation.to_csv(VALIDATION_PATH, index=False, encoding="utf-8")
    print(f"[✓] Successfully saved {len(df_validation)} sample reviews to: {VALIDATION_PATH}")

    # Compute comparative agreement rates on the 100 validation reviews
    baseline_matches = (df_validation["baseline_category"] == df_validation["ground_truth_category"]).sum()
    genai_matches = (df_validation["genai_category"] == df_validation["ground_truth_category"]).sum()
    total = len(df_validation)

    baseline_acc = (baseline_matches / total) * 100.0
    genai_acc = (genai_matches / total) * 100.0

    print("\n" + "-" * 55)
    print("VALIDATION SET (N=100) AGREEMENT BENCHMARKS")
    print("-" * 55)
    print(f"  Total Validation Reviews : {total}")
    print(f"  Naive Baseline Matches   : {baseline_matches:>3} / {total} ({baseline_acc:>5.2f}%)")
    print(f"  GenAI Model Matches      : {genai_matches:>3} / {total} ({genai_acc:>5.2f}%)")
    print(f"  Performance Delta        : +{genai_acc - baseline_acc:.2f}% improvement")

    print("\n--- Validation Set Distribution by Ground Truth ---")
    dist = df_validation["ground_truth_category"].value_counts()
    for cat, count in dist.items():
        b_match = ((df_validation["ground_truth_category"] == cat) & (df_validation["baseline_category"] == cat)).sum()
        g_match = ((df_validation["ground_truth_category"] == cat) & (df_validation["genai_category"] == cat)).sum()
        print(f"  {cat:<42}: {count:>2} reviews | Baseline: {b_match:>2}/{count:<2} | GenAI: {g_match:>2}/{count:<2}")
    print("=" * 80)


if __name__ == "__main__":
    create_validation_set()
