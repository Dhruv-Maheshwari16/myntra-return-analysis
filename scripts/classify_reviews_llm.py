"""
LLM-based Review Classifier for Myntra Avoidable Returns Analysis.

Supports:
- Gemini API (google-genai SDK or direct REST fallback)
- Claude API (anthropic SDK)

Features:
- Batched inference (default: 20 reviews per call)
- Few-shot prompting using /data/ground_truth.csv (3 examples per category)
- JSON structured output: [review_id, category, confidence]
- Exponential backoff retry logic
- Outputs to /data/myntra_classified.csv
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_INPUT = DATA_DIR / "myntra_filtered.csv"
DEFAULT_GROUND_TRUTH = DATA_DIR / "ground_truth.csv"
DEFAULT_OUTPUT = DATA_DIR / "myntra_classified.csv"

# Category Definitions & Descriptions
TAXONOMY: Dict[str, str] = {
    "Size & Fit Discrepancy": (
        "Sizing chart inaccuracies, inconsistent brand measurements, or garments arriving too tight, loose, or ill-fitting."
    ),
    "Defective, Damaged & Counterfeit Items": (
        "Merchandise arriving physically torn, soiled, moldy, defective, used, or suspected of being duplicate/counterfeit."
    ),
    "Incorrect / Wrong Item Delivered": (
        "Fulfillment and warehouse picking errors resulting in a completely wrong item, wrong color, wrong variant, or wrong size delivered."
    ),
    "Return & Exchange Logistics & QC Friction": (
        "Operational breakdowns during reverse logistics, including doorstep pickup agent no-shows, tag/barcode mismatch rejections, and arbitrary cancellation of return/exchange requests."
    ),
    "Refund Processing & Settlement Disputes": (
        "Extended delays in refund disbursement, missing funds, unauthorized wallet/credit conversions (MynCash/Myntra Credit), or disputed return/platform fees."
    ),
    "Other / Not Return-Related": (
        "Positive app praise, general quality or outfit compliments caught by keyword filters, and complaints unrelated to merchandise returns."
    ),
}


def load_few_shot_examples(gt_path: Path, examples_per_cat: int = 3) -> str:
    """Load up to `examples_per_cat` examples per category from ground truth CSV."""
    if not gt_path.exists():
        print(f"[!] Warning: Ground truth file not found at {gt_path}. Proceeding without few-shot examples.")
        return ""

    df_gt = pd.read_csv(gt_path)
    few_shot_sections = []

    for cat in TAXONOMY.keys():
        sub = df_gt[df_gt["category"] == cat].head(examples_per_cat)
        if sub.empty:
            continue
        few_shot_sections.append(f"### Category: {cat}")
        for _, row in sub.iterrows():
            text_cleaned = str(row["text"]).replace("\n", " ").strip()
            rating = row.get("rating", "")
            few_shot_sections.append(f'- Review ({rating}★): "{text_cleaned}"')
            few_shot_sections.append(f'  Assigned Category: "{cat}"')

    return "\n".join(few_shot_sections)


def build_system_prompt(few_shot_text: str) -> str:
    """Construct prompt with taxonomy v2 definitions, disambiguation rules, and few-shot examples."""
    cat_desc = "\n".join([f"{i+1}. **{cat}**: {desc}" for i, (cat, desc) in enumerate(TAXONOMY.items())])

    prompt = f"""You are an expert e-commerce and product analyst specializing in fashion apparel returns.
Your task is to classify customer Play Store reviews of Myntra into one of the following 6 mutually exclusive categories:

CATEGORIES AND DEFINITIONS:
{cat_desc}

DISAMBIGUATION & PRECEDENCE RULES (from Taxonomy v2):
1. **The Correct Label Rule (Size & Fit)**: Only classify as 'Size & Fit Discrepancy' if the garment delivered matched the ordered SKU/size tag but failed to fit the customer's body. If the warehouse shipped the wrong physical size tag (e.g. ordered 36, shipped XXL), classify as 'Incorrect / Wrong Item Delivered'.
2. **The Condition Precedence Rule (Defective/Damaged)**: If a review mentions BOTH receiving a damaged, torn, defective, or counterfeit item AND subsequent return refusal or refund delay, classify as 'Defective, Damaged & Counterfeit Items' (product root cause takes precedence).
3. **The Warehouse Root Cause Rule (Wrong Item Delivered)**: If a pickup agent refused a return citing tag mismatch or photo mismatch, BUT the review states Myntra originally sent the wrong item, color, or tag, classify as 'Incorrect / Wrong Item Delivered' (warehouse error takes precedence over doorstep refusal).
4. **The Handshake Failure Rule (Logistics & QC Friction)**: If the primary obstacle is the physical handover (pickup agent no-show, false cancellation, unserviceable pincode for return), classify as 'Return & Exchange Logistics & QC Friction'.
5. **The Post-Pickup Only Rule (Refund Disputes)**: 'Refund Processing & Settlement Disputes' applies ONLY when the physical merchandise has already been collected/returned, or a prepaid order was cancelled before delivery and funds remain uncredited.
6. **The Sentiment & Relevance Filter (Other / Not Return-Related)**: Any review expressing net positive praise regarding quality, fit, or pricing—even if it mentions return keywords—MUST be classified as 'Other / Not Return-Related'. Forward transit delivery delays (before package delivery) also belong here.

FEW-SHOT EXAMPLES:
{few_shot_text}
"""
    return prompt


def build_batch_user_prompt(batch: List[Dict[str, Any]]) -> str:
    """Format a batch of reviews for classification."""
    lines = ["Classify the following batch of reviews. Return ONLY a JSON list of objects matching the schema:"]
    lines.append('[{"review_id": str, "category": str, "confidence": float}, ...]')
    lines.append("\nReviews to classify:")
    for item in batch:
        rev_id = item["review_id"]
        rating = item.get("rating", "")
        text = str(item["text"]).replace("\n", " ").strip()
        lines.append(f'- review_id: "{rev_id}" | rating: {rating}★ | text: "{text}"')

    return "\n".join(lines)


def parse_json_response(raw_response: str) -> List[Dict[str, Any]]:
    """Clean and parse JSON from model output."""
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    cleaned = cleaned.strip()

    # Find JSON array using regex if surrounded by chatty text
    match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except Exception as e:
        print(f"[!] JSON parsing error: {e}. Raw response snippet: {raw_response[:200]}...")

    return []


# ----------------------------------------------------------------------
# Provider Clients
# ----------------------------------------------------------------------

class GeminiProvider:
    def __init__(self, api_key: str, model_name: str = "gemini-3.6-flash"):
        self.api_key = api_key
        self.model_name = model_name
        self.client = None

        # Try google-genai SDK
        try:
            # pyrefly: ignore [missing-import]
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
            self.use_sdk = True
            print(f"[+] Initialized Gemini client with model: {self.model_name}")
        except Exception:
            self.use_sdk = False
            print("[+] Using direct REST API for Gemini")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.use_sdk and self.client:
            # pyrefly: ignore [missing-import]
            from google.genai import types
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            return response.text or ""
        else:
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": user_prompt}]}],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
            }
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=60)
            res.raise_for_status()
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


class ClaudeProvider:
    def __init__(self, api_key: str, model_name: str = "claude-3-5-haiku-20241022"):
        # pyrefly: ignore [missing-import]
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_name = model_name
        print(f"[+] Initialized Anthropic client with model: {self.model_name}")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text


class MockProvider:
    """Mock provider for dry-run validation without active API keys."""
    def __init__(self):
        print("[+] Initialized Mock Provider (Dry-run mode)")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # Extract review IDs from user prompt and return mock classifications
        rev_ids = re.findall(r'review_id:\s*"([^"]+)"', user_prompt)
        mock_cats = list(TAXONOMY.keys())
        mock_output = []
        for i, r_id in enumerate(rev_ids):
            mock_output.append({
                "review_id": r_id,
                "category": mock_cats[i % len(mock_cats)],
                "confidence": 0.95,
            })
        return json.dumps(mock_output)


def get_llm_provider(provider_name: str, api_key: Optional[str] = None, model: Optional[str] = None):
    provider_name = provider_name.lower()

    if provider_name == "mock":
        return MockProvider()

    if provider_name == "gemini":
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY not found in environment or --api-key.")
        model_name = model or "gemini-3.6-flash"
        return GeminiProvider(api_key=key, model_name=model_name)

    elif provider_name in ["claude", "anthropic"]:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or --api-key.")
        model_name = model or "claude-3-5-haiku-20241022"
        return ClaudeProvider(api_key=key, model_name=model_name)

    else:
        raise ValueError(f"Unknown provider '{provider_name}'. Supported: gemini, claude, mock")


# ----------------------------------------------------------------------
# Batch Processing Engine
# ----------------------------------------------------------------------

def run_classification_pipeline(
    input_path: Path,
    output_path: Path,
    ground_truth_path: Path,
    provider_name: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    batch_size: int = 20,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Executes the classification pipeline in batches of 20."""
    print(f"[*] Loading filtered reviews from: {input_path}")
    df_reviews = pd.read_csv(input_path)
    total_reviews = len(df_reviews)
    print(f"[+] Total reviews to classify: {total_reviews}")

    print(f"[*] Loading few-shot examples from: {ground_truth_path}")
    few_shot_prompt = load_few_shot_examples(ground_truth_path, examples_per_cat=3)
    system_prompt = build_system_prompt(few_shot_prompt)

    llm = get_llm_provider(provider_name, api_key=api_key, model=model)

    records = df_reviews.to_dict(orient="records")
    classification_results: Dict[str, Dict[str, Any]] = {}

    total_batches = (total_reviews + batch_size - 1) // batch_size
    print(f"[*] Processing {total_batches} batches ({batch_size} reviews per batch)...")

    for b_idx in range(total_batches):
        start_i = b_idx * batch_size
        end_i = min(start_i + batch_size, total_reviews)
        batch = records[start_i:end_i]

        user_prompt = build_batch_user_prompt(batch)
        print(f"[*] Batch {b_idx + 1}/{total_batches} (Reviews {start_i + 1} to {end_i})...", end="", flush=True)

        parsed_items = []
        for attempt in range(max_retries):
            try:
                raw_resp = llm.generate(system_prompt, user_prompt)
                parsed_items = parse_json_response(raw_resp)
                if parsed_items:
                    break
                else:
                    print(f" [Empty/malformed JSON, retry {attempt+1}]", end="", flush=True)
                    time.sleep(2 ** attempt)
            except Exception as e:
                print(f" [Error: {e}, retry {attempt+1}]", end="", flush=True)
                time.sleep(2 ** attempt)

        # Index returned classifications
        classified_in_batch = 0
        for item in parsed_items:
            r_id = item.get("review_id")
            if r_id:
                classification_results[r_id] = {
                    "category": item.get("category", "Other / Not Return-Related"),
                    "confidence": float(item.get("confidence", 0.8)),
                }
                classified_in_batch += 1

        print(f" Done ({classified_in_batch}/{len(batch)} classified).")

        # Rate-limiting courtesy pause
        if provider_name != "mock" and b_idx < total_batches - 1:
            time.sleep(1.0)

    # Merge results back into DataFrame
    categories = []
    confidences = []
    for r_id in df_reviews["review_id"]:
        res = classification_results.get(r_id, {"category": "Other / Not Return-Related", "confidence": 0.5})
        # Standardize category name against taxonomy
        matched_cat = res["category"]
        if matched_cat not in TAXONOMY:
            for valid_cat in TAXONOMY:
                if valid_cat.lower() in matched_cat.lower() or matched_cat.lower() in valid_cat.lower():
                    matched_cat = valid_cat
                    break
            else:
                matched_cat = "Other / Not Return-Related"

        categories.append(matched_cat)
        confidences.append(res["confidence"])

    df_reviews["category"] = categories
    df_reviews["confidence"] = confidences

    # Reorder columns to [review_id, text, rating, date, category, confidence]
    out_cols = ["review_id", "text", "rating", "date", "category", "confidence"]
    df_out = df_reviews[out_cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(output_path, index=False, encoding="utf-8")
    print(f"\n[+] Successfully saved classifications to: {output_path}")

    # Summary
    print("\n================ LLM CLASSIFICATION DISTRIBUTION ================")
    counts = df_out["category"].value_counts()
    for cat, count in counts.items():
        pct = (count / len(df_out)) * 100
        print(f"{cat:<45} : {count:>3} ({pct:>5.1f}%)")
    print(f"Average Confidence: {df_out['confidence'].mean():.2f}")
    print("=================================================================\n")

    return df_out


def main():
    parser = argparse.ArgumentParser(description="Classify Myntra reviews using Claude or Gemini API.")
    parser.add_argument("--provider", default="gemini", choices=["gemini", "claude", "mock"], help="LLM Provider to use")
    parser.add_argument("--model", default=None, help="Model name (e.g. gemini-2.5-flash or claude-3-5-haiku-20241022)")
    parser.add_argument("--api-key", default=None, help="Provider API key (defaults to env var)")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to input reviews CSV")
    parser.add_argument("--ground-truth", default=str(DEFAULT_GROUND_TRUTH), help="Path to ground truth CSV for few-shot")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to save classified CSV")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of reviews per API call batch (default: 20)")

    args = parser.parse_args()

    # Automatically fallback to mock if requested or if no key is found
    provider = args.provider
    if provider == "gemini" and not (args.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print("[!] No Gemini API key detected in environment. Running in mock validation mode.")
        print("[!] (To run live inference, provide GEMINI_API_KEY or use --api-key <YOUR_KEY>)")
        provider = "mock"
    elif provider == "claude" and not (args.api_key or os.environ.get("ANTHROPIC_API_KEY")):
        print("[!] No Claude API key detected in environment. Running in mock validation mode.")
        print("[!] (To run live inference, provide ANTHROPIC_API_KEY or use --api-key <YOUR_KEY>)")
        provider = "mock"

    run_classification_pipeline(
        input_path=Path(args.input),
        output_path=Path(args.output),
        ground_truth_path=Path(args.ground_truth),
        provider_name=provider,
        api_key=args.api_key,
        model=args.model,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
