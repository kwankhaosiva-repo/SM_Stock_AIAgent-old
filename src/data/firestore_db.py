"""Firestore NoSQL Database Adapter for Near-Zero Cost GCP Deployment.

Uses the perpetual GCP Firestore Free Tier (1GB storage, 50k reads/day, 20k writes/day).
On Google Cloud Run, it connects automatically via Application Default Credentials (ADC).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FirestoreDB:
    """Manages collections: users, schedules, market_snapshots, report_deliveries."""

    def __init__(self, project_id: Optional[str] = None):
        try:
            from google.cloud import firestore
            self.client = firestore.Client(project=project_id or os.getenv('GCP_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT'))
            self.available = True
        except Exception as exc:
            self.client = None
            self.available = False
            self._init_error = str(exc)

    def _ensure_connected(self):
        if not self.available or not self.client:
            raise RuntimeError(f"Firestore client is not available: {getattr(self, '_init_error', 'Uninitialized')}")

    # --- Users & Preferences ---

    def get_or_create_user(self, line_user_id: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_connected()
        user_ref = self.client.collection('users').document(line_user_id)
        doc = user_ref.get()
        if doc.exists:
            return doc.to_dict()

        now = _utcnow()
        new_user = {
            'line_user_id': line_user_id,
            'display_name': display_name or '',
            'investment_goal': 'Medium',
            'core_strategy': 'AI-Auto',
            'risk_appetite': 'Medium',
            'report_format': 'Short',
            'created_at': now,
            'updated_at': now,
        }
        user_ref.set(new_user)
        return new_user

    def update_user_preferences(self, line_user_id: str, updates: Dict[str, Any]) -> None:
        self._ensure_connected()
        user_ref = self.client.collection('users').document(line_user_id)
        updates['updated_at'] = _utcnow()
        user_ref.set(updates, merge=True)

    # --- Watchlist (Subcollection: users/{line_user_id}/watchlist/{symbol}) ---

    def get_watchlist(self, line_user_id: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        watch_ref = self.client.collection('users').document(line_user_id).collection('watchlist')
        docs = watch_ref.stream()
        return [d.to_dict() for d in docs]

    def add_to_watchlist(self, line_user_id: str, symbol: str, settings: Optional[Dict[str, Any]] = None) -> bool:
        self._ensure_connected()
        clean_symbol = symbol.upper().strip()
        item_ref = self.client.collection('users').document(line_user_id).collection('watchlist').document(clean_symbol)
        doc = item_ref.get()
        if doc.exists:
            return False

        data = {
            'symbol': clean_symbol,
            'strategy': (settings or {}).get('strategy'),
            'goal': (settings or {}).get('goal'),
            'risk': (settings or {}).get('risk'),
            'report_format': (settings or {}).get('report_format'),
            'added_at': _utcnow(),
        }
        item_ref.set(data)
        return True

    def remove_from_watchlist(self, line_user_id: str, symbol: str) -> bool:
        self._ensure_connected()
        clean_symbol = symbol.upper().strip()
        item_ref = self.client.collection('users').document(line_user_id).collection('watchlist').document(clean_symbol)
        doc = item_ref.get()
        if not doc.exists:
            return False
        item_ref.delete()
        return True

    # --- Schedules ---

    def set_schedule(self, line_user_id: str, alert_time: str, is_active: bool = True) -> None:
        self._ensure_connected()
        sched_ref = self.client.collection('schedules').document(line_user_id)
        sched_ref.set({
            'line_user_id': line_user_id,
            'alert_time': alert_time,
            'is_active': is_active,
            'updated_at': _utcnow(),
        }, merge=True)

    def get_due_schedules(self, alert_time: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        query = (
            self.client.collection('schedules')
            .where('is_active', '==', True)
            .where('alert_time', '==', alert_time)
        )
        return [doc.to_dict() for doc in query.stream()]

    # --- Shared Market Snapshots (15 min cache) ---

    def get_cached_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._ensure_connected()
        clean_symbol = symbol.upper().strip()
        snap_ref = self.client.collection('market_snapshots').document(clean_symbol)
        doc = snap_ref.get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        expires_at = data.get('expires_at')
        if expires_at and expires_at > _utcnow():
            return data
        return None

    def save_snapshot(self, snapshot_dict: Dict[str, Any], ttl_minutes: int = 15) -> None:
        self._ensure_connected()
        clean_symbol = snapshot_dict['symbol'].upper().strip()
        now = _utcnow()
        snapshot_dict['collected_at'] = now
        snapshot_dict['expires_at'] = now + timedelta(minutes=ttl_minutes)
        self.client.collection('market_snapshots').document(clean_symbol).set(snapshot_dict)

    # --- Idempotent Deliveries ---

    def is_delivery_sent(self, idempotency_key: str) -> bool:
        self._ensure_connected()
        doc = self.client.collection('report_deliveries').document(idempotency_key).get()
        return doc.exists and doc.to_dict().get('status') == 'sent'

    def mark_delivery_sent(self, idempotency_key: str, line_user_id: str) -> None:
        self._ensure_connected()
        self.client.collection('report_deliveries').document(idempotency_key).set({
            'idempotency_key': idempotency_key,
            'line_user_id': line_user_id,
            'status': 'sent',
            'sent_at': _utcnow(),
        })
