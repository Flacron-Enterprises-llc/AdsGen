"""
Subscription/plan store using Firebase Firestore. Keys by user email.
"""
from typing import Optional, List, Dict, Any

_COLLECTION = "subscriptions"


def _get_firestore():
    try:
        import firebase_admin
        from firebase_admin import firestore
        return firestore.client()
    except Exception:
        return None


def init_subscription_store():
    """No-op; Firestore doesn't need table creation."""
    pass


def _doc_id(email: str) -> str:
    return (email or "").strip().lower()


def get_subscription(email: str) -> Optional[dict]:
    """Return subscription for email or None."""
    try:
        db = _get_firestore()
        if not db or not email:
            return None
        doc_id = _doc_id(email)
        doc = db.collection(_COLLECTION).document(doc_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        if (data or {}).get("status") != "active":
            return None
        return {"email": doc_id, "plan": data.get("plan"), **data}
    except Exception:
        return None


def has_active_plan(email: str) -> bool:
    return get_subscription(email) is not None


def set_plan(
    email: str,
    plan: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
):
    """Set or update user's plan. plan = 'free' | 'starter' | 'pro'."""
    try:
        db = _get_firestore()
        if not db or not email or plan not in ("free", "starter", "pro"):
            return
        doc_id = _doc_id(email)
        from datetime import datetime
        now = datetime.utcnow()
        data = {
            "email": doc_id,
            "plan": plan,
            "status": "active",
            "updated_at": now,
        }
        if stripe_customer_id:
            data["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id:
            data["stripe_subscription_id"] = stripe_subscription_id
        doc_ref = db.collection(_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            data["created_at"] = now
        doc_ref.set(data, merge=True)
    except Exception:
        pass


def list_all_subscriptions() -> List[Dict[str, Any]]:
    """List all subscription docs for admin. Returns list of dicts with id, email, plan, status, etc."""
    try:
        db = _get_firestore()
        if not db:
            return []
        out = []
        for doc in db.collection(_COLLECTION).stream():
            d = doc.to_dict()
            d["id"] = doc.id
            out.append(d)
        return out
    except Exception:
        return []


def update_subscription_status(email: str, status: str) -> bool:
    """Update status (e.g. active, cancelled). Returns True if updated."""
    db = _get_firestore()
    if not db or status not in ("active", "cancelled", "past_due"):
        return False
    doc_id = _doc_id(email)
    db.collection(_COLLECTION).document(doc_id).set({"status": status}, merge=True)
    return True


def update_subscription_plan(email: str, plan: str) -> bool:
    """Admin: set user's plan. plan = free | starter | pro."""
    if plan not in ("free", "starter", "pro"):
        return False
    set_plan(email, plan)
    return True


def get_pricing() -> Dict[str, Any]:
    """Get pricing config from Firestore (for admin and optional use in checkout)."""
    db = _get_firestore()
    if not db:
        return {}
    doc = db.collection("settings").document("pricing").get()
    return doc.to_dict() if doc.exists else {}


def set_pricing(data: Dict[str, Any]) -> None:
    """Admin: save pricing config to Firestore."""
    db = _get_firestore()
    if not db:
        return
    db.collection("settings").document("pricing").set(data, merge=True)
