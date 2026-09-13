"""
Evaluate Agreement Rate between LLM Classification and Ground Truth.

Compares:
- /data/myntra_classified.csv (LLM classified predictions)
- /data/ground_truth.csv (Ground truth annotations)

Calculates:
- Overall agreement rate (% where manual_category == category)
- Category-level breakdown and confusion matrix
- Detailed row-by-row match report
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CLASSIFIED_PATH = BASE_DIR / "data" / "myntra_classified.csv"
DEFAULT_GROUND_TRUTH_PATH = BASE_DIR / "data" / "ground_truth.csv"


def evaluate_agreement(
    classified_path: Path,
    ground_truth_path: Path,
) -> float:
    print(f"[*] Reading ground truth from : {ground_truth_path}")
    df_gt = pd.read_csv(ground_truth_path)

    print(f"[*] Reading classifications from: {classified_path}")
    df_cl = pd.read_csv(classified_path)

    # Determine ground truth category column
    if "manual_category" in df_gt.columns:
        gt_cat_col = "manual_category"
    elif "sample_category" in df_gt.columns:
        gt_cat_col = "sample_category"
    else:
        gt_cat_col = "category"

    # Merge on review_id
    merged = pd.merge(
        df_gt[["review_id", "text", "rating", gt_cat_col]],
        df_cl[["review_id", "category"]],
        on="review_id",
        suffixes=("_manual", "_classified"),
    )

    total_overlap = len(merged)
    if total_overlap == 0:
        print("[!] Error: No overlapping review_ids found between the two datasets.")
        return 0.0

    manual_col = f"{gt_cat_col}" if f"{gt_cat_col}" != "category" else "category_manual"
    classified_col = "category" if "category" in merged.columns else "category_classified"

    # Compute matches
    merged["is_match"] = merged[manual_col] == merged[classified_col]
    matches = merged["is_match"].sum()
    agreement_rate = (matches / total_overlap) * 100.0

    print("\n" + "=" * 95)
    print(f"AGREEMENT RATE EVALUATION SUMMARY")
    print("=" * 95)
    print(f"Total Ground Truth Reviews     : {len(df_gt)}")
    print(f"Total Classified Reviews       : {len(df_cl)}")
    print(f"Overlapping Reviews Evaluated  : {total_overlap}")
    print(f"Exact Matches (manual == model): {matches} / {total_overlap}")
    print(f"Overall Agreement Rate         : {agreement_rate:.2f}%")
    print("=" * 95)

    # Category-level breakdown
    print("\n--- Category-Level Agreement Breakdown ---")
    cat_summary = []
    for cat in sorted(df_gt[gt_cat_col].unique()):
        cat_rows = merged[merged[manual_col] == cat]
        cat_total = len(cat_rows)
        cat_matches = cat_rows["is_match"].sum()
        cat_rate = (cat_matches / cat_total * 100.0) if cat_total > 0 else 0.0
        cat_summary.append({
            "Category": cat,
            "Total GT": cat_total,
            "Matches": cat_matches,
            "Agreement %": f"{cat_rate:.1f}%",
        })

    df_cat_summary = pd.DataFrame(cat_summary)
    print(df_cat_summary.to_string(index=False))

    # Row-by-row comparison
    print("\n--- Detailed Review-by-Review Comparison ---")
    for idx, row in merged.iterrows():
        status = "✅ MATCH" if row["is_match"] else "❌ MISMATCH"
        short_id = row["review_id"][:8]
        rating = row.get("rating", "")
        text_snippet = str(row["text"]).replace("\n", " ")[:75]
        print(f"[{idx + 1:2d}] {status} | ID: {short_id}... | ({rating}★) \"{text_snippet}...\"")
        print(f"     Ground Truth : {row[manual_col]}")
        print(f"     Classified   : {row[classified_col]}\n")

    return agreement_rate


def main():
    parser = argparse.ArgumentParser(description="Calculate agreement rate between classified reviews and ground truth.")
    parser.add_argument("--classified", default=str(DEFAULT_CLASSIFIED_PATH), help="Path to classified CSV")
    parser.add_argument("--ground-truth", default=str(DEFAULT_GROUND_TRUTH_PATH), help="Path to ground truth CSV")

    args = parser.parse_args()
    evaluate_agreement(
        classified_path=Path(args.classified),
        ground_truth_path=Path(args.ground_truth),
    )


if __name__ == "__main__":
    main()
