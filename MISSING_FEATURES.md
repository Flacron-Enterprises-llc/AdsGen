# Missing Core Features & Implementation Gaps

Based on the "CORE FEATURES" requirement list, here is the status of the current implementation:

## 1. Auto Marketing Mode (IMPLEMENTED)
- **Requirement:** Automate campaigns (weekly/bi-weekly/monthly), generate weekly ads automatically.
- **Status:** **Implemented.**
- **Details:** APScheduler runs every hour. Firestore `auto_marketing` collection stores per-user settings (enabled, frequency, campaign_params, recipients). GET/POST `/api/auto-marketing`. Starter and Pro only. Requires `apscheduler` and Firestore.

## 2. Campaign Analytics Dashboard (PARTIAL)
- **Requirement:** Show Open rate, Click rate, Campaign conversions.
- **Status:** **Partially Implemented.**
- **Gap:**
    - The system tracks "Sent" and "Delivered" status but **does not track Opens or Clicks**.
    - **Missing:** Webhook endpoints for SendGrid (Event Webhook) and Twilio (Status Callback) to capture open/click events.
    - **Missing:** Database/Firestore structure to store these events per campaign.

## 3. Competitor Marketing Engine (BASIC)
- **Requirement:** Analyze competitor offers, pricing, and Instagram.
- **Status:** **Basic Implementation.**
- **Gap:**
    - The system has a basic scraper structure but lacks deep integration for extracting **pricing** or **Instagram content**.
    - AI prompts use competitor names but don't yet have rich data (like specific competitor prices) to generate "beat their price" offers automatically unless the user manually inputs the competitor's ad copy.

## 6. Plan Limits Enforcement (IMPLEMENTED)
- **Requirement:** Enforce limits (e.g., Free Plan: 5 AI ads/mo, 1 campaign/mo).
- **Status:** **Implemented.**
- **Details:** `web_app/usage_limits.py` defines PLAN_LIMITS (free/starter/pro). Usage stored in Firestore `usage/{email}` per calendar month. Before generate: `check_can_generate()`; before send: `check_can_send()`. Returns 402 when limit exceeded. Ad variations capped to plan `ad_variations`.

## 7. Usage-Based Billing (IMPLEMENTED)
- **Requirement:** Charge for extra SMS ($0.02), Email ($0.001), and AI ads ($5/100).
- **Status:** **Implemented.**
- **Details:** Overage is tracked in the same `usage` doc. Starter/Pro can exceed limits (overage counted). `get_overage_cost(email)` returns amounts. `charge_overage_stripe(email)` creates Stripe Invoice Items for the overage and resets overage counters. POST `/api/charge-overage` for user to trigger; can be called periodically (e.g. end of month).

## 8. Campaign Scheduling (MISSING)
- **Requirement:** "Schedule or send immediately".
- **Status:** **Immediate Only.**
- **Gap:** The UI and backend support "Send Now" but lack a "Schedule for Later" queue mechanism that picks up future jobs.

---

### Summary
**Implemented:** Core AI Generator, Manual Campaign Management (Firestore), Plan Limits (6), Usage-Based Billing (7), Auto Marketing Mode (4). **Still missing:** Open/Click analytics (webhooks), Campaign scheduling (send later), deeper competitor pricing/Instagram integration.
