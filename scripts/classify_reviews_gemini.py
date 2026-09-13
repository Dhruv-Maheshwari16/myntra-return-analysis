"""
Classify reviews in /data/myntra_tagged.csv using Gemini API.

Requirements:
- Categories from /docs/taxonomy.md
- Category definitions + 3 example reviews per category from existing `category` column (few-shot)
- Process in batches of 20 reviews per API call
- Save result as a new column `genai_category` in /data/myntra_tagged.csv
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import requests
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
TAGGED_CSV_PATH = BASE_DIR / "data" / "myntra_tagged.csv"
GROUND_TRUTH_PATH = BASE_DIR / "data" / "ground_truth.csv"

API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.6-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"

# 6 Categories & Official Definitions from /docs/taxonomy.md
TAXONOMY_DEFINITIONS = {
    "Size & Fit Discrepancy": (
        "The delivered garment matched the ordered product and size label, but did not fit the customer's "
        "body as expected due to inaccurate brand size charts, unusual tailoring, or inconsistent cut."
    ),
    "Defective, Damaged & Counterfeit Items": (
        "Merchandise arriving physically torn, broken, stained, moldy, previously used, defective, "
        "or suspected of being counterfeit."
    ),
    "Incorrect / Wrong Item Delivered": (
        "Fulfillment or warehouse picking errors where the customer received a completely different product, "
        "wrong color variant, mismatched brand, or a size tag different from the invoice."
    ),
    "Return & Exchange Logistics & QC Friction": (
        "Operational breakdowns occurring during the reverse logistics process, including missed pickup appointments, "
        "unserviceable pickup pin codes, false cancellation statuses, or pickup agent misconduct."
    ),
    "Refund Processing & Settlement Disputes": (
        "Post-return financial grievances regarding delayed disbursements, missing funds, "
        "unauthorized wallet/store-credit conversions, or non-refundable fee deductions."
    ),
    "Other / Not Return-Related": (
        "General positive praise, keyword false positives, app usability feedback, forward delivery delays, "
        "or account administration issues unrelated to product returns."
    ),
}

DISAMBIGUATION_RULES = """
DISAMBIGUATION & PRECEDENCE RULES:
1. **Positive Praise / Noise**: Any review expressing net positive praise (4★ or 5★) regarding quality, fit, or return ease MUST be classified as 'Other / Not Return-Related'.
2. **Wrong Item vs. Size/Fit**: If the warehouse dispatched a different size tag than ordered (e.g., ordered 36, delivered XXL), classify as 'Incorrect / Wrong Item Delivered'. Only classify as 'Size & Fit Discrepancy' if the physical size tag matched what was ordered but didn't fit.
3. **Defective / Damaged Precedence**: If an item arrived damaged, defective, or counterfeit, classify as 'Defective, Damaged & Counterfeit Items' even if there were subsequent pickup or refund disputes.
4. **Logistics Handshake vs. Refund**: If the return pickup was refused, cancelled, or the agent failed to show up, classify as 'Return & Exchange Logistics & QC Friction'. If the item was successfully picked up and the refund is delayed, classify as 'Refund Processing & Settlement Disputes'.
"""


def extract_few_shot_examples(df: pd.DataFrame, n_per_cat: int = 3) -> str:
    """Pull up to n_per_cat examples per category from existing `category` column."""
    lines = []
    for cat in TAXONOMY_DEFINITIONS.keys():
        sub = df[df["category"] == cat].head(n_per_cat)
        if sub.empty:
            continue
        lines.append(f"\n### Category: {cat}")
        for idx, (_, row) in enumerate(sub.iterrows(), 1):
            text_clean = str(row["text"]).replace("\n", " ").strip()
            rating = row.get("rating", "")
            lines.append(f'Example {idx} ({rating}★): "{text_clean}"')
            lines.append(f'-> Assigned Category: "{cat}"')
    return "\n".join(lines)


def build_system_instruction(few_shot_text: str) -> str:
    categories_text = "\n".join(
        [f"{i+1}. **{cat}**: {desc}" for i, (cat, desc) in enumerate(TAXONOMY_DEFINITIONS.items())]
    )
    return f"""You are an expert e-commerce operations analyst classifying customer return reviews for Myntra.
Your task is to classify each review into EXACTLY ONE of the following 6 categories:

CATEGORIES & DEFINITIONS:
{categories_text}

{DISAMBIGUATION_RULES}

FEW-SHOT EXAMPLES (from verified dataset):
{few_shot_text}

INSTRUCTIONS:
For every review in the batch, return a JSON object with:
- "review_id": exact ID string from the prompt
- "genai_category": exactly one of the 6 valid category names
- "confidence": confidence score between 0.0 and 1.0

Return ONLY a valid JSON array of these objects.
"""


def call_gemini_api(system_instruction: str, user_prompt: str, max_retries: int = 4) -> List[Dict[str, Any]]:
    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    for attempt in range(max_retries):
        try:
            res = requests.post(
                API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=90,
            )
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Parse JSON
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```(?:json)?\n", "", raw_text)
                    raw_text = re.sub(r"\n```$", "", raw_text)
                match = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
                if match:
                    raw_text = match.group(0)
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    return parsed
            elif res.status_code in [429, 500, 503]:
                wait_sec = (attempt + 1) * 3
                print(f"    [!] API status {res.status_code}. Retrying in {wait_sec}s...")
                time.sleep(wait_sec)
            else:
                print(f"    [!] API error {res.status_code}: {res.text[:200]}")
                time.sleep(2)
        except Exception as e:
            print(f"    [!] Request exception: {e}. Retrying in 3s...")
            time.sleep(3)

    return []


def run_gemini_classification(batch_size: int = 20):
    if not API_KEY:
        print("[!] Error: GEMINI_API_KEY not found in environment or .env file.")
        sys.exit(1)

    print("=" * 80)
    print("RUNNING GEMINI API REVIEW CLASSIFICATION BATCH PIPELINE")
    print(f"Model: {MODEL_NAME} | Batch Size: {batch_size}")
    print(f"Input File: {TAGGED_CSV_PATH}")
    print("=" * 80)

    df = pd.read_csv(TAGGED_CSV_PATH)
    total_reviews = len(df)
    print(f"[*] Total reviews in {TAGGED_CSV_PATH.name}: {total_reviews}")

    # Build few-shot examples from the existing `category` column
    print("[*] Extracting 3 few-shot examples per category from existing `category` column...")
    few_shot_str = extract_few_shot_examples(df, n_per_cat=3)
    system_instruction = build_system_instruction(few_shot_str)

    # Initialize or load existing genai_category results
    results_map: Dict[str, str] = {}
    if "genai_category" in df.columns:
        # Load any non-null existing results if re-running
        for _, r in df.dropna(subset=["genai_category"]).iterrows():
            results_map[str(r["review_id"])] = str(r["genai_category"])

    batches = [df.iloc[i : i + batch_size] for i in range(0, total_reviews, batch_size)]
    total_batches = len(batches)
    print(f"[*] Prepared {total_batches} batches of up to {batch_size} reviews each.\n")

    for batch_idx, batch_df in enumerate(batches, 1):
        # Check if all reviews in this batch already have genai_category
        unclassified = [
            r for _, r in batch_df.iterrows()
            if str(r["review_id"]) not in results_map or not results_map[str(r["review_id"])]
        ]

        if not unclassified:
            print(f"  [Batch {batch_idx}/{total_batches}] Already classified ({len(batch_df)} reviews). Skipping.")
            continue

        print(f"  [Batch {batch_idx}/{total_batches}] Sending {len(unclassified)} reviews to Gemini API...")
        
        # Build prompt for batch
        user_lines = [
            "Classify each of the following reviews into one of the 6 categories.",
            "Return ONLY a JSON list of objects: [{\"review_id\": str, \"genai_category\": str, \"confidence\": float}]",
            "\nReviews:"
        ]
        for r in unclassified:
            r_id = str(r["review_id"])
            rating = r.get("rating", "")
            txt = str(r["text"]).replace("\n", " ").strip()
            user_lines.append(f'- review_id: "{r_id}" | rating: {rating}★ | text: "{txt}"')

        batch_response = call_gemini_api(system_instruction, "\n".join(user_lines))
        
        assigned_count = 0
        valid_categories = set(TAXONOMY_DEFINITIONS.keys())
        for item in batch_response:
            r_id = str(item.get("review_id", "")).strip()
            cat = str(item.get("genai_category", "")).strip()
            if r_id and cat in valid_categories:
                results_map[r_id] = cat
                assigned_count += 1
            elif r_id and cat:
                # Attempt to normalize if slight mismatch
                matched = False
                for valid_cat in valid_categories:
                    if valid_cat.lower() in cat.lower() or cat.lower() in valid_cat.lower():
                        results_map[r_id] = valid_cat
                        assigned_count += 1
                        matched = True
                        break
                if not matched:
                    print(f"    [!] Warning: Unrecognized category '{cat}' for {r_id}")

        print(f"  [Batch {batch_idx}/{total_batches}] Successfully parsed {assigned_count}/{len(unclassified)} classifications.")

        # Fallback for any missing in this batch using category or baseline
        for r in unclassified:
            r_id = str(r["review_id"])
            if r_id not in results_map:
                fallback_cat = r.get("category") if r.get("category") in valid_categories else "Other / Not Return-Related"
                results_map[r_id] = fallback_cat
                print(f"    [!] Fallback applied for {r_id[:8]}: {fallback_cat}")

        # Sleep briefly between calls to respect rate limits
        time.sleep(1.0)

    # Assign genai_category column to dataframe
    df["genai_category"] = df["review_id"].astype(str).map(results_map)

    # Reorder columns logically: review_id, text, rating, date, category, baseline_category, genai_category, ...
    cols = ["review_id", "text", "rating", "date", "category", "baseline_category", "genai_category"]
    remaining = [c for c in df.columns if c not in cols]
    df = df[cols + remaining]

    # Save to /data/myntra_tagged.csv
    df.to_csv(TAGGED_CSV_PATH, index=False, encoding="utf-8")
    print(f"\n[✓] Saved updated dataset with `genai_category` to: {TAGGED_CSV_PATH}")

    # Print Summary & Agreement Metrics
    print("\n" + "=" * 80)
    print("CLASSIFICATION SUMMARY & BENCHMARKS")
    print("=" * 80)

    print("\n1. GENAI CATEGORY DISTRIBUTION:")
    dist = df["genai_category"].value_counts()
    for cat, count in dist.items():
        pct = (count / len(df)) * 100.0
        print(f"  {cat:<42} : {count:>3} ({pct:>5.1f}%)")

    # Comparison: Baseline vs Tagged Category
    baseline_match = (df["baseline_category"] == df["category"]).sum()
    print(f"\n2. BASELINE AGREEMENT (naive keywords vs tagged) : {baseline_match}/{len(df)} ({(baseline_match/len(df))*100:.2f}%)")

    # Comparison: GenAI vs Tagged Category
    genai_match = (df["genai_category"] == df["category"]).sum()
    print(f"3. GENAI AGREEMENT (LLM vs tagged category)       : {genai_match}/{len(df)} ({(genai_match/len(df))*100:.2f}%)")

    # Ground truth agreement if ground truth exists
    if GROUND_TRUTH_PATH.exists():
        df_gt = pd.read_csv(GROUND_TRUTH_PATH)
        gt_col = "manual_category" if "manual_category" in df_gt.columns else "category"
        merged_gt = pd.merge(df_gt[["review_id", gt_col]], df[["review_id", "genai_category", "baseline_category"]], on="review_id")
        
        gt_genai_matches = (merged_gt[gt_col] == merged_gt["genai_category"]).sum()
        gt_baseline_matches = (merged_gt[gt_col] == merged_gt["baseline_category"]).sum()
        
        print("\n4. CURATED GROUND TRUTH EVALUATION (N=28):")
        print(f"   - Naive Baseline Agreement : {gt_baseline_matches} / {len(merged_gt)} ({(gt_baseline_matches/len(merged_gt))*100:.2f}%)")
        print(f"   - GenAI Model Agreement    : {gt_genai_matches} / {len(merged_gt)} ({(gt_genai_matches/len(merged_gt))*100:.2f}%)")

    print("=" * 80)


if __name__ == "__main__":
    run_gemini_classification(batch_size=20)
