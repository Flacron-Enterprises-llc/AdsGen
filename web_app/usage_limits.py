"""
Plan limits and usage tracking. Stores usage in Firestore, resets by calendar month.
Overage is tracked and can be billed via Stripe.
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

# Plan limits: -1 = unlimited
PLAN_LIMITS = {
    "free": {
        "ai_ads_per_month": 5,
        "campaigns_per_month": 1,
        "emails_per_month": 20,
        "sms_per_month": 10,
        "ad_variations": 1,
        "competitor_analysis": False,
        "scheduling": False,
        "automation": False,
    },
    "starter": {
        "ai_ads_per_month": 200,
        "campaigns_per_month": 20,
        "emails_per_month": 2000,
        "sms_per_month": 1000,
        "ad_variations": 5,
        "competitor_analysis": True,
        "scheduling": True,
        "automation": True,
    },
    "pro": {
        "ai_ads_per_month": -1,
        "campaigns_per_month": -1,
        "emails_per_month": 10000,
        "sms_per_month": 5000,
        "ad_variations": 10,
        "competitor_analysis": True,
        "scheduling": True,
        "automation": True,
    },
}

# Overage pricing (USD)
OVERAGE_PRICE_SMS = 0.02
OVERAGE_PRICE_EMAIL = 0.001
OVERAGE_PRICE_AI_ADS_PER_100 = 5.0

_USAGE_COLLECTION = "usage"


def _get_firestore():
    try:
        import firebase_admin
        from firebase_admin import firestore
        return firebase_admin.firestore.client()
    except Exception:
        return None


def _doc_id(email: str) -> str:
    return (email or "").strip().lower()


def _current_period() -> str:
    """Current calendar month key e.g. 2025-03."""
    return datetime.utcnow().strftime("%Y-%m")


def _get_usage_doc(db, doc_id: str, period: str) -> Dict[str, Any]:
    ref = db.collection(_USAGE_COLLECTION).document(doc_id)
    doc = ref.get()
    if not doc.exists:
        return {"period": period, "ai_ads_used": 0, "campaigns_used": 0, "emails_used": 0, "sms_used": 0,
                "overage_sms": 0, "overage_email": 0, "overage_ai_ads": 0}
    data = doc.to_dict() or {}
    if data.get("period") != period:
        return {"period": period, "ai_ads_used": 0, "campaigns_used": 0, "emails_used": 0, "sms_used": 0,
                "overage_sms": 0, "overage_email": 0, "overage_ai_ads": 0}
    return data


def get_plan_limits(plan: str) -> Dict[str, Any]:
    """Return limits for plan. Default to free if unknown."""
    return PLAN_LIMITS.get((plan or "free").lower(), PLAN_LIMITS["free"]).copy()


def get_usage(email: str, plan: Optional[str] = None) -> Dict[str, Any]:
    """Get current period usage and limits for user."""
    try:
        from .subscription_store import get_subscription
        sub = get_subscription(email) if email else None
        plan = (plan or (sub.get("plan") if sub else None) or "free").lower()
    except Exception:
        plan = "free"

    limits = get_plan_limits(plan)
    db = _get_firestore()
    period = _current_period()
    doc_id = _doc_id(email) if email else ""
    if not db or not doc_id:
        return {
            "period": period,
            "plan": plan,
            "limits": limits,
            "ai_ads_used": 0,
            "campaigns_used": 0,
            "emails_used": 0,
            "sms_used": 0,
            "overage_sms": 0,
            "overage_email": 0,
            "overage_ai_ads": 0,
            "within_limits": True,
        }

    data = _get_usage_doc(db, doc_id, period)
    data["plan"] = plan
    data["limits"] = limits
    # Compute within_limits
    def within(key_used: str, key_limit: str):
        used = data.get(key_used, 0)
        lim = limits.get(key_limit)
        if lim is None or lim == -1:
            return True
        return used < lim

    data["within_limits"] = (
        within("ai_ads_used", "ai_ads_per_month")
        and within("campaigns_used", "campaigns_per_month")
        and within("emails_used", "emails_per_month")
        and within("sms_used", "sms_per_month")
    )
    return data


def check_can_generate(email: str, num_ads: int = 1, new_campaign: bool = True) -> Tuple[bool, str]:
    """
    Check if user can generate ads (and optionally create a new campaign).
    Returns (allowed, error_message).
    """
    usage = get_usage(email)
    limits = usage["limits"]
    period = usage["period"]

    # Check campaign limit if this will create a new campaign
    if new_campaign:
        camp_limit = limits.get("campaigns_per_month")
        if camp_limit is not None and camp_limit != -1:
            if usage.get("campaigns_used", 0) >= camp_limit:
                return False, f"Campaign limit reached ({camp_limit} per month). Upgrade or wait until next month."

    # Check AI ads limit
    ad_limit = limits.get("ai_ads_per_month")
    if ad_limit is not None and ad_limit != -1:
        after = usage.get("ai_ads_used", 0) + num_ads
        if usage.get("ai_ads_used", 0) >= ad_limit:
            return False, f"AI ad limit reached ({ad_limit} per month). Upgrade or wait until next month."
        if after > ad_limit and not _allow_overage(usage):
            return False, f"Would exceed AI ad limit ({ad_limit}). You have {ad_limit - usage.get('ai_ads_used', 0)} left."

    return True, ""


def check_can_send(email: str, num_sms: int, num_email: int) -> Tuple[bool, str]:
    """Check if user can send this many SMS and emails. Returns (allowed, error_message)."""
    usage = get_usage(email)
    limits = usage["limits"]

    sms_limit = limits.get("sms_per_month")
    if sms_limit is not None and sms_limit != -1:
        after_sms = usage.get("sms_used", 0) + num_sms
        if after_sms > sms_limit and not _allow_overage(usage):
            return False, f"SMS limit is {sms_limit}/month. You would exceed it. Upgrade for overage billing."

    email_limit = limits.get("emails_per_month")
    if email_limit is not None and email_limit != -1:
        after_email = usage.get("emails_used", 0) + num_email
        if after_email > email_limit and not _allow_overage(usage):
            return False, f"Email limit is {email_limit}/month. You would exceed it. Upgrade for overage billing."

    return True, ""


def _allow_overage(usage: Dict) -> bool:
    """Starter and Pro allow overage (billed). Free does not."""
    return (usage.get("plan") or "free").lower() in ("starter", "pro")


def increment_usage(
    email: str,
    ai_ads: int = 0,
    campaigns: int = 0,
    emails: int = 0,
    sms: int = 0,
) -> Dict[str, Any]:
    """
    Increment usage and optionally overage. Call after successful generate/send.
    Returns updated usage snapshot.
    """
    db = _get_firestore()
    if not db or not email:
        return get_usage(email)

    doc_id = _doc_id(email)
    period = _current_period()
    ref = db.collection(_USAGE_COLLECTION).document(doc_id)
    data = _get_usage_doc(db, doc_id, period)

    limits = get_plan_limits(data.get("plan") or get_usage(email).get("plan", "free"))

    # Compute how much goes to included vs overage
    def add_usage(key_used: str, key_limit: str, key_overage: Optional[str], delta: int):
        used = data.get(key_used, 0)
        lim = limits.get(key_limit)
        if lim == -1:
            data[key_used] = used + delta
            if key_overage:
                data[key_overage] = data.get(key_overage, 0)
            return
        cap = max(0, lim - used)
        included = min(delta, cap)
        over = max(0, delta - included)
        data[key_used] = used + delta
        if key_overage:
            data[key_overage] = data.get(key_overage, 0) + over

    add_usage("ai_ads_used", "ai_ads_per_month", "overage_ai_ads", ai_ads)
    add_usage("campaigns_used", "campaigns_per_month", None, campaigns)
    add_usage("emails_used", "emails_per_month", "overage_email", emails)
    add_usage("sms_used", "sms_per_month", "overage_sms", sms)

    data["period"] = period
    data["updated_at"] = datetime.utcnow()
    ref.set(data, merge=True)
    return get_usage(email)


def get_overage_cost(email: str) -> Dict[str, Any]:
    """Get current period overage amounts and total cost in USD."""
    usage = get_usage(email)
    over_sms = usage.get("overage_sms", 0)
    over_email = usage.get("overage_email", 0)
    over_ads = usage.get("overage_ai_ads", 0)
    cost_sms = over_sms * OVERAGE_PRICE_SMS
    cost_email = over_email * OVERAGE_PRICE_EMAIL
    cost_ads = (over_ads / 100.0) * OVERAGE_PRICE_AI_ADS_PER_100
    return {
        "overage_sms": over_sms,
        "overage_email": over_email,
        "overage_ai_ads": over_ads,
        "cost_sms_usd": round(cost_sms, 4),
        "cost_email_usd": round(cost_email, 4),
        "cost_ai_ads_usd": round(cost_ads, 4),
        "total_usd": round(cost_sms + cost_email + cost_ads, 4),
    }
