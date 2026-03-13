"""
Campaign store using Firebase Firestore.
Replaces PostgreSQL for storing campaigns, ads, and send logs.
"""
from typing import Optional, List, Dict, Any
import time
from datetime import datetime

_CAMPAIGNS_COLLECTION = "campaigns"
_SENDS_COLLECTION = "sends"

def _get_firestore():
    try:
        import firebase_admin
        from firebase_admin import firestore
        return firestore.client()
    except Exception:
        return None

def create_campaign(data: Dict[str, Any]) -> Optional[str]:
    """Create a new campaign doc. Returns campaign_id."""
    db = _get_firestore()
    if not db:
        return None
    
    # Add timestamps
    now = datetime.utcnow()
    data['created_at'] = now
    data['updated_at'] = now
    if 'status' not in data:
        data['status'] = 'draft'
        
    ref = db.collection(_CAMPAIGNS_COLLECTION).document()
    ref.set(data)
    return ref.id

def get_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    db = _get_firestore()
    if not db:
        return None
    doc = db.collection(_CAMPAIGNS_COLLECTION).document(campaign_id).get()
    if doc.exists:
        d = doc.to_dict()
        d['id'] = doc.id
        return d
    return None

def update_campaign(campaign_id: str, updates: Dict[str, Any]) -> bool:
    db = _get_firestore()
    if not db:
        return False
    updates['updated_at'] = datetime.utcnow()
    db.collection(_CAMPAIGNS_COLLECTION).document(campaign_id).set(updates, merge=True)
    return True

def list_user_campaigns(email: str, limit: int = 50) -> List[Dict[str, Any]]:
    """List campaigns for a specific user email."""
    db = _get_firestore()
    if not db:
        return []
    
    query = db.collection(_CAMPAIGNS_COLLECTION).where('user_email', '==', email).order_by('created_at', direction='DESCENDING').limit(limit)
    docs = query.stream()
    
    campaigns = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        campaigns.append(d)
    return campaigns

def list_all_campaigns(limit: int = 100) -> List[Dict[str, Any]]:
    """Admin: list all campaigns."""
    db = _get_firestore()
    if not db:
        return []
    
    # Simple list, ordering by created_at if possible, else just stream
    # Note: Composite index might be needed for ordering if we filter, but here we just list all
    try:
        query = db.collection(_CAMPAIGNS_COLLECTION).order_by('created_at', direction='DESCENDING').limit(limit)
        docs = query.stream()
    except Exception:
        # Fallback without ordering if index missing
        docs = db.collection(_CAMPAIGNS_COLLECTION).limit(limit).stream()
        
    campaigns = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        # Calculate derived stats if not present (optional)
        # For performance, we should increment counters on the doc, but for now we'll just read what's there
        campaigns.append(d)
    return campaigns

def log_send(campaign_id: str, channel: str, status: str, recipient: str, ad_variant: Dict[str, Any] = None) -> str:
    """Log a send event (SMS or Email)."""
    db = _get_firestore()
    if not db:
        return ""
    
    data = {
        'campaign_id': campaign_id,
        'channel': channel,
        'status': status,
        'recipient': recipient,
        'created_at': datetime.utcnow(),
        'ad_variant': ad_variant or {}
    }
    
    ref = db.collection(_SENDS_COLLECTION).document()
    ref.set(data)
    
    # Also update campaign counters atomically if possible, or just loose update
    # We'll do a loose update for simplicity here
    try:
        camp_ref = db.collection(_CAMPAIGNS_COLLECTION).document(campaign_id)
        # Increment send count
        # In a real app, use Firestore transactions or FieldValue.increment
        from firebase_admin import firestore
        camp_ref.update({
            'send_count': firestore.FieldValue.increment(1)
        })
    except Exception:
        pass
        
    return ref.id

def get_usage_stats() -> Dict[str, int]:
    """Admin: get total usage stats."""
    db = _get_firestore()
    if not db:
        return {'sms': 0, 'email': 0, 'sms_sent': 0, 'email_sent': 0}
        
    # Aggregation queries (requires Firestore native aggregation or client-side counting)
    # Client-side counting is expensive for reads.
    # For now, we will try to use the Count aggregation if available in the SDK, else fallback to a "settings/stats" doc
    # that we should maintain.
    # SINCE we are just migrating now, we might not have the stats doc.
    # We'll try to count recent sends or just return 0 if too many.
    
    # Better approach: Maintain a 'stats' document in a 'system' collection
    # incremented by log_send.
    
    try:
        doc = db.collection('system').document('usage_stats').get()
        if doc.exists:
            return doc.to_dict()
    except Exception:
        pass
        
    return {'sms': 0, 'email': 0, 'sms_sent': 0, 'email_sent': 0}

def increment_usage_stats(channel: str, status: str):
    """Helper to increment global usage stats."""
    db = _get_firestore()
    if not db:
        return
        
    try:
        from firebase_admin import firestore
        ref = db.collection('system').document('usage_stats')
        
        updates = {
            f'{channel}_total': firestore.FieldValue.increment(1)
        }
        if status in ('sent', 'delivered'):
            updates[f'{channel}_sent'] = firestore.FieldValue.increment(1)
            
        ref.set(updates, merge=True)
    except Exception:
        pass
