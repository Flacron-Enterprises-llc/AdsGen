# AdsGen — Product Information Document

**Product name:** AdsGen (AdsCompetitor)  
**Version:** 1.0  
**Document type:** Product details, purpose, and working process

---

## 1. Product Overview & Purpose

**AdsGen** is an AI-powered advertising platform that helps businesses create and distribute competitive ad content quickly. It is designed for:

- **Small businesses and marketers** who want to run targeted campaigns without heavy copywriting or design work.
- **Local and regional campaigns** that need location-aware messaging (ZIP code, area, industry).
- **Multi-channel distribution** of the same campaign via **SMS** and **email** from a single workflow.

### Why AdsGen Exists

- **Speed:** Generate multiple ad variations in one flow instead of writing each one manually.
- **Competitor focus:** Input your brand and a competitor (name or URL); the system uses that context to produce differentiated, relevant copy.
- **End-to-end flow:** From “competitor info” to “ads sent to users” in four steps—no switching between tools for creation vs. delivery.
- **Flexibility:** Optional industry presets, audience type, offer type, campaign goal, and hashtags let you steer the AI without deep prompt engineering.

---

## 2. Product Details

### 2.1 Core Capabilities

| Capability | Description |
|------------|-------------|
| **Competitor-based ad generation** | Enter your brand and a competitor name (or paste a competitor URL to auto-extract info). Optional: competitor ad copy, industry, audience, offer type, goal. |
| **AI-generated content** | Produces headline, main ad text, call-to-action (CTA), and hashtags. Multiple variations per run (configurable, typically 1–10). |
| **Competitor intelligence (optional)** | Can scrape competitor data from the web (description, services, features, contact) to enrich the context sent to the AI. |
| **SMS delivery** | Sends generated ads via **Twilio** to phone numbers you add. |
| **Email delivery** | Sends generated ads via **SendGrid** to email addresses you add. |
| **Validation** | Validates and normalizes phone numbers and email addresses before sending. |
| **Background jobs** | Generation and sending can run in a job queue so the UI stays responsive. |
| **Persistence (optional)** | Campaigns, ad variants, recipients, and send events can be stored in a database for tracking. |

### 2.2 User-Facing Features

- **Step 1 — Competitor info:** Your brand, competitor name/URL, optional ad copy, industry preset, audience type, offer type, campaign goal, location, ZIP code, hashtags, number of ad variations.
- **Step 2 — Generated ads:** Review and edit AI-generated ad variations (headline, ad text, CTA, hashtags).
- **Step 3 — Add recipients:** Add SMS recipients (phone) and/or email recipients; support for single add, bulk paste, and CSV import.
- **Step 4 — Review & send:** Campaign summary, “Send now,” “Schedule for later,” and “Preview campaign.”

### 2.3 Technical Components

| Component | Role |
|-----------|------|
| **Web app** | Flask app; serves UI and REST API for generate, send, validate, status, job status. |
| **Input layer** | Cleans and validates competitor names, hashtags, and ZIP codes. |
| **Processing layer** | Builds marketing context: tone/sentiment, keyword patterns, regional (ZIP) analysis. |
| **AI generation layer** | Uses an LLM (e.g. **Gemini**) to generate headline, ad text, CTA, and hashtags from the marketing context. |
| **Competitor intelligence** | Optional scraper to gather competitor info from the web and merge it into the context. |
| **Notification layer** | Sends SMS (Twilio) and email (SendGrid); provider-agnostic so other backends can be added. |
| **Jobs** | Background tasks for “generate ads” and “send notifications”; optional queue (e.g. RQ/Redis). |
| **Database (optional)** | Stores campaigns, ad variants, recipients, sends, and events. |

### 2.4 Integrations & Configuration

- **AI:** Google Gemini (API key; model and temperature configurable via env).
- **SMS:** Twilio (account SID, auth token, phone number).
- **Email:** SendGrid (API key, from email, from name).
- **Environment:** `.env` for keys and feature flags (e.g. enable/disable notifications, queue).

---

## 3. Working Process / Flow

### 3.1 High-Level User Journey

```
Step 1: Enter competitor info  →  Step 2: Generate ads  →  Step 3: Add recipients  →  Step 4: Review & send
```

### 3.2 Step-by-Step Process

**Step 1 — Competitor information (input)**  
- User enters: brand name, competitor name or URL, optional ad copy, industry, audience, offer type, goal, location, ZIP code, hashtags, number of variations.  
- Optional: “Parse from URL” calls the backend to derive a competitor name/domain from a pasted URL.  
- Data is sent to the backend when the user clicks “Generate Ads.”

**Step 2 — Generate ads (processing pipeline)**  
1. **Competitor intelligence (optional):** If the competitor intelligence module is present, it may scrape the competitor (name/URL) and return description, services, features, website, contact.  
2. **Input layer:** Competitor name, hashtags, and ZIP code are processed (cleaned, validated, normalized).  
3. **Processing layer:** A **marketing context** is built from processed inputs (tone, keywords, regional info) and combined with business fields (brand, competitor, ad copy, location, zipcode, industry, audience, offer, goal) and any scraped competitor data.  
4. **AI generation layer:** The LLM (e.g. Gemini) is called with this context to produce one ad (headline, ad text, CTA, hashtags). For multiple variations, the AI is called repeatedly (with optional caching by brand/competitor/zipcode/variation count).  
5. **Output:** A list of ad objects is returned to the UI (and optionally stored as campaign + ad variants in the database).  
- User sees the ads in Step 2, can go back to Step 1 to change inputs and regenerate, or proceed to Step 3.

**Step 3 — Add recipients**  
- User adds SMS recipients (phone numbers) and/or email recipients (addresses).  
- Validation APIs may be used to check phone and email format.  
- Recipients can be added one-by-one, in bulk (paste), or via CSV upload.  
- Step 4 is enabled once at least one recipient exists.

**Step 4 — Review & send**  
- User sees a summary: counts of SMS/email recipients, channels, and ad variations.  
- **Send now:** Backend runs the “send notifications” job: for each ad variation, sends SMS to all SMS recipients and email to all email recipients (Twilio and SendGrid).  
- **Schedule for later:** User can set date, time, and timezone; scheduling logic can store the intent (exact implementation may use DB or queue).  
- **Preview:** User can preview how the campaign will look.  
- Results (success/failure per channel) are shown; optional DB records track sends and events.

### 3.3 Data Flow (Backend)

```
User input (Step 1)
    ↓
Competitor intelligence (optional) → enriched competitor data
    ↓
Input layer (competitor, hashtags, zipcode) → processed results
    ↓
Processing layer (processed results + business data) → marketing context
    ↓
AI generation layer (marketing context) → generated ads
    ↓
Session / DB: store ads and campaign_id
    ↓
User adds recipients (Step 3) → Session / DB: store recipient list
    ↓
Send (Step 4): for each ad → Notification layer → Twilio (SMS) + SendGrid (email)
    ↓
Results and optional DB events (send/delivery)
```

### 3.4 Optional Behaviors

- **Caching:** Ad generation can be cached by (brand, competitor, zipcode, number of variations) to avoid repeated AI calls for the same inputs.  
- **Queue:** If a job queue is configured, “generate” and “send” run as background jobs; the API may return a `job_id` and the client can poll for status.  
- **Database:** When enabled, campaigns, ad variants, recipients, sends, and events are persisted for reporting and auditing.

---

## 4. Summary

| Aspect | Description |
|--------|-------------|
| **Product** | AdsGen (AdsCompetitor): AI-powered ad creation and delivery. |
| **Purpose** | Help businesses create competitor-aware ad copy and send it via SMS and email quickly, with optional scheduling and tracking. |
| **Process** | Four steps: (1) Enter competitor/brand/location/options, (2) Generate ad variations with AI, (3) Add SMS/email recipients, (4) Review and send (or schedule). |
| **Layers** | Input → Processing → AI generation → Notification; optional competitor intelligence and DB. |
| **Channels** | SMS (Twilio), Email (SendGrid). |

This document reflects the product’s current design and working process as implemented in the codebase.
