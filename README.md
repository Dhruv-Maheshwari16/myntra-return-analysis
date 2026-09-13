# Reducing Avoidable Apparel Returns on Myntra: A Product & Analytics Case Study

## Project Summary
This project analyzes the root causes of apparel returns in Indian e-commerce using 3,000 scraped Google Play Store reviews for Myntra (and 1,000 for Ajio). By implementing a 6-category taxonomy, testing a keyword baseline against a few-shot GenAI classifier (Gemini 3.6 Flash), running SQL diagnostics, and auditing competitor flows across Myntra, Ajio, and Amazon India, the study identifies high-leverage product interventions to curb return friction.

## The Key Pivot: Size/Fit Hypothesis → Refund & Fulfillment Reality
The study began assuming pre-purchase size/fit issues were the primary return driver. Empirical classification of 389 keyword-filtered reviews disproved this:
- **Size & Fit Discrepancy** was the smallest genuine complaint driver at **1.8% of total filtered reviews** (7.0% of actionable complaints, 2.57★ avg).
- **Refund Processing & Settlement Disputes** was the primary complaint driver at **34.0% of actionable complaints** (8.74% of total reviews, 1.12★ avg).
- **Incorrect / Wrong Item Delivered** (warehouse dispatch errors) followed at **24.0% of actionable complaints** (6.17% of total reviews, 1.13★ avg).

## How This Was Built
- **Phase 0: Problem Framing** — Defined return unit economics and project charter ([`docs/project_charter.md`](docs/project_charter.md)).
- **Phase 1: VoC Scraping** — Scraped 4,000 reviews; filtered 389 Myntra reviews using 8 keywords.
- **Phase 2: MECE Taxonomy** — Formulated 6 categories with precedence rules ([`docs/taxonomy.md`](docs/taxonomy.md)).
- **Phase 3: AI Classification** — Built baseline (19% accuracy) and GenAI model (96% benchmark; 82% blind validation).
- **Phase 4: SQL Warehouse** — Analyzed category share and ratings in SQLite ([`analysis/category_share.csv`](analysis/category_share.csv)).
- **Phase 5: Interactive Dashboard** — Built an executive visual analytics interface ([`analysis/dashboard.html`](analysis/dashboard.html)).
- **Phase 6: Competitive Teardown** — Audited UX across Myntra, Ajio, and Amazon ([`design/competitive/teardown_notes.md`](design/competitive/teardown_notes.md)).
- **Phase 7: Product PRD** — Drafted specs for refund tracking and QC decoupling ([`docs/PRD.md`](docs/PRD.md)).
- **Phase 8: Case Study** — Authored complete portfolio synthesis ([`docs/case_study.md`](docs/case_study.md)).

## Primary Artifacts
- 📄 **Full Case Study**: [`docs/case_study.md`](docs/case_study.md)
- 📊 **Interactive Analytics Dashboard**: [`analysis/dashboard.html`](analysis/dashboard.html)

## Limitations Summary
Public Play Store reviews serve as an imperfect proxy for internal transaction databases and carry vocal negative bias. Initial classification required blind re-validation (82% agreement on N=28) due to a circularity flaw, and wireframes depict only happy-path refund flows without internal Myntra telemetry.
