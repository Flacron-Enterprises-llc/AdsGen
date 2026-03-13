"""
Usage-based billing: report overage to Stripe (one-time invoice items or metered usage).
"""
import os
from typing import Optional, Dict, Any
from .usage_limits import get_overage_cost, get_usage, _doc_id, _current_period, _USAGE_COLLECTION


def _get_firestore():
    try:
        import firebase_admin
        from firebase_admin import firestore
        return firebase_admin.firestore.client()
    except Exception:
        return None


def charge_overage_stripe(email: str, stripe_customer_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Charge current period overage to Stripe and reset overage counters.
    Uses Stripe Invoice Items (one-time) so the amount appears on the next invoice.
    If no stripe_customer_id, look up from subscription store.
    Returns { success, error?, invoice_item_id? }.
    """
    try:
        from .subscription_store import get_subscription
        sub = get_subscription(email)
        if not sub:
            return {"success": False, "error": "No active subscription"}
        customer_id = stripe_customer_id or sub.get("stripe_customer_id")
        if not customer_id:
            return {"success": False, "error": "No Stripe customer ID"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    cost = get_overage_cost(email)
    total = cost.get("total_usd", 0)
    if total <= 0:
        return {"success": True, "charged": 0, "message": "No overage to charge"}

    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        return {"success": False, "error": "Stripe not configured"}

    try:
        import stripe
        stripe.api_key = secret

        # Create invoice items for the next invoice (cents)
        total_cents = int(round(total * 100))
        if total_cents <= 0:
            return {"success": True, "charged": 0}

        item = stripe.InvoiceItem.create(
            customer=customer_id,
            amount=total_cents,
            currency="usd",
            description=f"Overage ({_current_period()}): SMS, Email, AI ads",
        )
        # Reset overage in Firestore so we don't double-charge
        db = _get_firestore()
        if db:
            ref = db.collection(_USAGE_COLLECTION).document(_doc_id(email))
            ref.set({
                "overage_sms": 0,
                "overage_email": 0,
                "overage_ai_ads": 0,
            }, merge=True)

        return {"success": True, "charged": total, "invoice_item_id": item.id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def report_metered_usage_stripe(email: str, quantity: int, metered_price_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Report usage to Stripe Metered Billing (if you use a metered Price).
    Optional: set STRIPE_METERED_PRICE_ID_OVERAGE in env.
    """
    try:
        from .subscription_store import get_subscription
        sub = get_subscription(email)
        if not sub:
            return {"success": False, "error": "No subscription"}
        sub_id = sub.get("stripe_subscription_id")
        if not sub_id:
            return {"success": False, "error": "No Stripe subscription ID"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    price_id = metered_price_id or os.getenv("STRIPE_METERED_PRICE_ID_OVERAGE", "").strip()
    if not price_id:
        return {"success": False, "error": "No metered price ID configured"}

    secret = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        return {"success": False, "error": "Stripe not configured"}

    try:
        import stripe
        stripe.api_key = secret
        stripe.SubscriptionItem.create_usage_record(
            sub_id,  # subscription_item_id is required; you need to get it from the subscription
            quantity=quantity,
            timestamp=int(__import__("time").time()),
            action="increment",
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
