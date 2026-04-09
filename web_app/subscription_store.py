"""
Subscription/plan store using Firebase Firestore. Keys by user email.
"""
from typing import Optional, List, Dict, Any

_COLLECTION = "subscriptions"

# Module-level cached Firestore client.
# app.py calls set_firestore_client() right after Firebase initialises so that
# every Gunicorn worker that imports this module picks up the same client
# without having to call firebase_admin.get_app() again.
_firestore_client = None


def set_firestore_client(db) -> None:
    """Inject the Firestore client from app.py. Called once per worker startup."""
    global _firestore_client
    _firestore_client = db
    print(f"[subscription_store] Firestore client injected: {type(db).__name__}")


def _is_active_status(data: dict) -> bool:
    st = (data or {}).get("status")
    return st is not None and str(st).strip().lower() == "active"


def _get_firestore():
    global _firestore_client
    # Use cached client if available
    if _firestore_client is not None:
        return _firestore_client
    # Fallback: try firebase_admin.get_app()
    try:
        import firebase_admin
        from firebase_admin import firestore
        app = firebase_admin.get_app()
        client = firestore.client(app)
        _firestore_client = client  # cache for next call
        return client
    except Exception as e:
        print(f"[subscription_store] _get_firestore failed: {e}")
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
        if not db:
            print(f"[subscription_store] get_subscription: no Firestore client for {email!r}")
            return None
        if not email:
            return None
        doc_id = _doc_id(email)
        doc = db.collection(_COLLECTION).document(doc_id).get()
        if not doc.exists:
            print(f"[subscription_store] get_subscription: no doc for {doc_id!r}")
            return None
        data = doc.to_dict() or {}
        status = data.get("status")
        plan = data.get("plan")
        if not _is_active_status(data):
            print(
                f"[subscription_store] get_subscription: doc {doc_id!r} exists but not active "
                f"(status={status!r}, plan={plan!r})"
            )
            return None
        return {"email": doc_id, "plan": plan, **data}
    except Exception as e:
        import traceback
        print(f"[subscription_store] get_subscription failed for {email!r}: {e}")
        traceback.print_exc()
        return None


def has_active_plan(email: str) -> bool:
    return get_subscription(email) is not None


def set_plan(
    email: str,
    plan: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> bool:
    """Set or update user's plan. plan = 'free' | 'starter' | 'pro'. Returns True if written to Firestore."""
    try:
        db = _get_firestore()
        if not db or not email or plan not in ("free", "starter", "pro"):
            return False
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
        snap = doc_ref.get()
        if not snap.exists:
            print(f"[subscription_store] set_plan: doc missing after write for {doc_id!r}")
            return False
        written = snap.to_dict() or {}
        if not _is_active_status(written) or (written.get("plan") or "").strip().lower() != plan:
            print(
                f"[subscription_store] set_plan: unexpected data after write for {doc_id!r}: "
                f"status={written.get('status')!r} plan={written.get('plan')!r}"
            )
            return False
        return True
    except Exception as e:
        print(f"[subscription_store] set_plan failed for {email!r}: {e}")
        return False


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
    return set_plan(email, plan)


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
