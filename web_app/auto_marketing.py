"""
Auto Marketing Mode: store user settings and run scheduled campaigns.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

_COLLECTION = "auto_marketing"
FREQUENCIES = ("weekly", "bi-weekly", "monthly")


def _get_firestore():
    try:
        import firebase_admin
        from firebase_admin import firestore
        return firebase_admin.firestore.client()
    except Exception:
        return None


def _doc_id(email: str) -> str:
    return (email or "").strip().lower()


def get_settings(email: str) -> Dict[str, Any]:
    """Get auto marketing settings for user. Defaults to disabled."""
    db = _get_firestore()
    if not db or not email:
        return {"enabled": False, "frequency": "weekly", "campaign_params": {}, "recipients": []}
    doc = db.collection(_COLLECTION).document(_doc_id(email)).get()
    if not doc.exists:
        return {"enabled": False, "frequency": "weekly", "campaign_params": {}, "recipients": []}
    d = doc.to_dict() or {}
    return {
        "enabled": d.get("enabled", False),
        "frequency": d.get("frequency", "weekly"),
        "last_run": d.get("last_run"),
        "next_run": d.get("next_run"),
        "campaign_params": d.get("campaign_params", {}),
        "recipients": d.get("recipients", []),
        "updated_at": d.get("updated_at"),
    }


def save_settings(
    email: str,
    enabled: bool,
    frequency: str = "weekly",
    campaign_params: Optional[Dict[str, Any]] = None,
    recipients: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Save auto marketing settings. Sets next_run if enabling."""
    db = _get_firestore()
    if not db or not email:
        return False
    if frequency not in FREQUENCIES:
        frequency = "weekly"
    doc_id = _doc_id(email)
    now = datetime.utcnow()
    ref = db.collection(_COLLECTION).document(doc_id)
    data = {
        "email": doc_id,
        "enabled": bool(enabled),
        "frequency": frequency,
        "campaign_params": campaign_params or {},
        "recipients": recipients or [],
        "updated_at": now,
    }
    if enabled:
        data["next_run"] = now  # Run on next scheduler tick
        if not ref.get().exists:
            data["last_run"] = None
    else:
        data["next_run"] = None
    ref.set(data, merge=True)
    return True


def _next_run(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "weekly":
        return now + timedelta(days=7)
    if period == "bi-weekly":
        return now + timedelta(days=14)
    if period == "monthly":
        return now + timedelta(days=30)
    return now + timedelta(days=7)


def _to_datetime(val):
    """Convert Firestore timestamp/datetime to datetime."""
    if val is None:
        return None
    if hasattr(val, "timestamp"):
        return datetime.utcfromtimestamp(val.timestamp())
    if hasattr(val, "replace"):
        return val
    return None


def list_due() -> List[Dict[str, Any]]:
    """List all auto_marketing docs that are due (next_run <= now, enabled)."""
    db = _get_firestore()
    if not db:
        return []
    now = datetime.utcnow()
    out = []
    for doc in db.collection(_COLLECTION).stream():
        d = doc.to_dict() or {}
        if not d.get("enabled"):
            continue
        next_run = _to_datetime(d.get("next_run"))
        if next_run is None:
            continue
        if next_run <= now:
            d["id"] = doc.id
            d["email"] = doc.id
            out.append(d)
    return out


def mark_run(email: str) -> None:
    """Set last_run = now and next_run = now + frequency."""
    db = _get_firestore()
    if not db or not email:
        return
    doc_id = _doc_id(email)
    ref = db.collection(_COLLECTION).document(doc_id)
    doc = ref.get()
    if not doc.exists:
        return
    d = doc.to_dict() or {}
    now = datetime.utcnow()
    freq = d.get("frequency", "weekly")
    ref.set({
        "last_run": now,
        "next_run": _next_run(freq),
        "updated_at": now,
    }, merge=True)
