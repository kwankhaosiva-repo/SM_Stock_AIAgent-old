"""Unified data store — Firestore on GCP, in-memory fallback for dev/tests.

Replaces the SQLAlchemy layer (database.py). All app code reads/writes through
this module so Cloud Run instances share state via Firestore while local
development and unit tests run on a fast in-memory backend.

Collections (Firestore):
    users/{user_key}                          — profile + chat_state
    users/{user_key}/watchlist/{SYMBOL}       — watchlist items
    schedules/{user_key}                      — daily alert schedule
    market_snapshots/{SYMBOL}                 — cached snapshot (TTL)
    source_documents/{id}                     — news sources per snapshot
    financial_cache/{SYMBOL}                  — balance-sheet cache (24h)
    analysis_runs/{id}                        — workflow audit records
    agent_outputs/{id}                        — per-agent audit output
    report_deliveries/{idempotency_key}       — idempotent delivery guard
    global_stock_info/{SYMBOL}                — company profile cache

user_key คือรหัสผู้ใช้ที่ไม่ซ้ำ เช่น LINE user id หรือ 'web:<uuid>' สำหรับช่องทาง web
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_DEFAULT_PROFILE = {
    'investment_goal': 'Medium',
    'core_strategy': 'AI-Auto',
    'risk_appetite': 'Medium',
    'report_format': 'Short',
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_symbol(symbol: str) -> str:
    return (symbol or '').upper().strip()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class MemoryBackend:
    """Thread-safe in-memory backend. Data lives only for the process lifetime."""

    def __init__(self):
        self.lock = threading.RLock()
        self.users: Dict[str, Dict] = {}
        self.watchlist: Dict[tuple, Dict] = {}
        self.schedules: Dict[str, Dict] = {}
        self.snapshots: Dict[str, Dict] = {}
        self.source_docs: Dict[str, List[Dict]] = {}
        self.financials: Dict[str, Dict] = {}
        self.analysis_runs: Dict[str, Dict] = {}
        self.agent_outputs: Dict[str, List[Dict]] = {}
        self.deliveries: Dict[str, Dict] = {}
        self.global_info: Dict[str, Dict] = {}
        self._counter = 0

    def _next_id(self) -> str:
        with self.lock:
            self._counter += 1
            return f'mem-{self._counter}'

    # users
    def get_or_create_user(self, user_key: str, display_name: str = '') -> Dict:
        with self.lock:
            user = self.users.get(user_key)
            if not user:
                now = _utcnow()
                user = {**_DEFAULT_PROFILE, 'user_key': user_key, 'display_name': display_name or '',
                        'chat_state': None, 'created_at': now, 'updated_at': now}
                self.users[user_key] = user
            elif display_name and not user.get('display_name'):
                user['display_name'] = display_name
            return dict(user)

    def get_user(self, user_key: str) -> Optional[Dict]:
        with self.lock:
            user = self.users.get(user_key)
            return dict(user) if user else None

    def update_user(self, user_key: str, updates: Dict) -> None:
        with self.lock:
            user = self.users.setdefault(user_key, {**_DEFAULT_PROFILE, 'user_key': user_key})
            user.update(updates)
            user['updated_at'] = _utcnow()

    def set_chat_state(self, user_key: str, state: Optional[str]) -> None:
        self.update_user(user_key, {'chat_state': state})

    def get_chat_state(self, user_key: str) -> Optional[str]:
        with self.lock:
            user = self.users.get(user_key)
            return user.get('chat_state') if user else None

    # watchlist
    def list_watchlist(self, user_key: str) -> List[Dict]:
        with self.lock:
            items = [dict(v) for (k, _), v in self.watchlist.items() if k == user_key]
            return sorted(items, key=lambda x: x.get('added_at') or _utcnow())

    def get_watch_item(self, user_key: str, symbol: str) -> Optional[Dict]:
        with self.lock:
            item = self.watchlist.get((user_key, _clean_symbol(symbol)))
            return dict(item) if item else None

    def add_watch_item(self, user_key: str, symbol: str, **settings) -> bool:
        clean = _clean_symbol(symbol)
        with self.lock:
            key = (user_key, clean)
            if key in self.watchlist:
                return False
            self.watchlist[key] = {'user_key': user_key, 'symbol': clean, **settings, 'added_at': _utcnow()}
            return True

    def update_watch_item(self, user_key: str, symbol: str, **fields) -> bool:
        clean = _clean_symbol(symbol)
        with self.lock:
            item = self.watchlist.get((user_key, clean))
            if not item:
                return False
            item.update({k: v for k, v in fields.items() if v is not None})
            item['updated_at'] = _utcnow()
            return True

    def count_watchlist(self, user_key: str) -> int:
        with self.lock:
            return sum(1 for (k, _) in self.watchlist if k == user_key)

    # schedules
    def get_schedule(self, user_key: str) -> Optional[Dict]:
        with self.lock:
            sched = self.schedules.get(user_key)
            return dict(sched) if sched else None

    def upsert_schedule(self, user_key: str, **fields) -> None:
        with self.lock:
            sched = self.schedules.setdefault(user_key, {'user_key': user_key})
            sched.update({k: v for k, v in fields.items() if v is not None})
            sched['updated_at'] = _utcnow()

    def list_active_schedules(self, alert_time: str) -> List[Dict]:
        with self.lock:
            return [
                dict(s) for s in self.schedules.values()
                if s.get('is_active') and s.get('alert_time') == alert_time
            ]

    # market snapshots (15-min shared cache)
    def get_valid_snapshot(self, symbol: str) -> Optional[Dict]:
        with self.lock:
            rec = self.snapshots.get(_clean_symbol(symbol))
            if rec and rec['expires_at'] > _utcnow():
                return dict(rec)
            return None

    def save_snapshot(self, symbol: str, data: Dict, provider: str, ttl_minutes: int) -> str:
        clean = _clean_symbol(symbol)
        now = _utcnow()
        snap_id = self._next_id()
        with self.lock:
            self.snapshots[clean] = {
                'id': snap_id, 'symbol': clean, 'data': data, 'provider': provider,
                'collected_at': now, 'expires_at': now + timedelta(minutes=ttl_minutes),
            }
        return snap_id

    def save_source_documents(self, snapshot_id: str, sources: List[Dict]) -> None:
        with self.lock:
            self.source_docs.setdefault(snapshot_id, []).extend(sources)

    # financial cache (24h)
    def get_financial_cache(self, symbol: str, max_age_hours: int) -> Optional[Dict]:
        with self.lock:
            rec = self.financials.get(_clean_symbol(symbol))
            if rec and rec['collected_at'] > _utcnow() - timedelta(hours=max_age_hours):
                return {'data': rec['data'], 'source': rec['source']}
            return None

    def save_financial_cache(self, symbol: str, data: Dict, source: str) -> None:
        with self.lock:
            self.financials[_clean_symbol(symbol)] = {
                'data': data, 'source': source, 'collected_at': _utcnow(),
            }

    # analysis runs / agent outputs
    def create_analysis_run(self, user_key: Optional[str], symbol: str) -> str:
        run_id = self._next_id()
        with self.lock:
            self.analysis_runs[run_id] = {
                'user_key': user_key, 'symbol': _clean_symbol(symbol), 'status': 'running',
                'snapshot_id': None, 'result': None, 'error_message': None,
                'created_at': _utcnow(), 'completed_at': None,
            }
        return run_id

    def update_analysis_run(self, run_id: str, **fields) -> None:
        with self.lock:
            run = self.analysis_runs.setdefault(run_id, {})
            run.update({k: v for k, v in fields.items() if v is not None or k == 'error_message'})

    def add_agent_output(self, run_id: str, agent_name: str, output_json: str) -> None:
        with self.lock:
            self.agent_outputs.setdefault(run_id, []).append({
                'agent_name': agent_name, 'output_json': output_json, 'created_at': _utcnow(),
            })

    # report deliveries (idempotency)
    def get_delivery(self, idempotency_key: str) -> Optional[Dict]:
        with self.lock:
            d = self.deliveries.get(idempotency_key)
            return dict(d) if d else None

    def upsert_delivery(self, idempotency_key: str, user_key: str, status: str,
                        error_message: Optional[str] = None) -> None:
        with self.lock:
            d = self.deliveries.setdefault(idempotency_key, {'idempotency_key': idempotency_key})
            d.update({'user_key': user_key, 'status': status, 'error_message': error_message,
                      'updated_at': _utcnow()})
            if status == 'sent':
                d['sent_at'] = _utcnow()

    # global stock info cache
    def get_global_stock_info(self, symbol: str) -> Optional[Dict]:
        with self.lock:
            rec = self.global_info.get(_clean_symbol(symbol))
            return dict(rec) if rec else None

    def save_global_stock_info(self, symbol: str, **fields) -> None:
        with self.lock:
            rec = self.global_info.setdefault(_clean_symbol(symbol), {'symbol': _clean_symbol(symbol)})
            rec.update(fields)
            rec['updated_at'] = _utcnow()

    def prune_global_stock_info(self, max_age_hours: int) -> int:
        cutoff = _utcnow() - timedelta(hours=max_age_hours)
        with self.lock:
            stale = [s for s, r in self.global_info.items()
                     if (r.get('updated_at') or cutoff) < cutoff]
            for s in stale:
                del self.global_info[s]
            return len(stale)


class FirestoreBackend:
    """Firestore backend using Application Default Credentials (Cloud Run ready)."""

    def __init__(self, client):
        self.client = client

    # users
    def get_or_create_user(self, user_key: str, display_name: str = '') -> Dict:
        ref = self.client.collection('users').document(user_key)
        doc = ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            if display_name and not data.get('display_name'):
                data['display_name'] = display_name
                ref.set({'display_name': display_name, 'updated_at': _utcnow()}, merge=True)
            data.setdefault('user_key', user_key)
            return data
        now = _utcnow()
        user = {**_DEFAULT_PROFILE, 'user_key': user_key, 'display_name': display_name or '',
                'chat_state': None, 'created_at': now, 'updated_at': now}
        ref.set(user)
        return user

    def get_user(self, user_key: str) -> Optional[Dict]:
        doc = self.client.collection('users').document(user_key).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data.setdefault('user_key', user_key)
        return data

    def update_user(self, user_key: str, updates: Dict) -> None:
        updates = dict(updates)
        updates['updated_at'] = _utcnow()
        self.client.collection('users').document(user_key).set(updates, merge=True)

    def set_chat_state(self, user_key: str, state: Optional[str]) -> None:
        self.update_user(user_key, {'chat_state': state})

    def get_chat_state(self, user_key: str) -> Optional[str]:
        user = self.get_user(user_key)
        return user.get('chat_state') if user else None

    # watchlist — subcollection per user
    def _watch_ref(self, user_key: str):
        return self.client.collection('users').document(user_key).collection('watchlist')

    def list_watchlist(self, user_key: str) -> List[Dict]:
        return [d.to_dict() for d in self._watch_ref(user_key).stream()]

    def get_watch_item(self, user_key: str, symbol: str) -> Optional[Dict]:
        doc = self._watch_ref(user_key).document(_clean_symbol(symbol)).get()
        return doc.to_dict() if doc.exists else None

    def add_watch_item(self, user_key: str, symbol: str, **settings) -> bool:
        ref = self._watch_ref(user_key).document(_clean_symbol(symbol))
        if ref.get().exists:
            return False
        ref.set({'user_key': user_key, 'symbol': _clean_symbol(symbol), **settings, 'added_at': _utcnow()})
        return True

    def update_watch_item(self, user_key: str, symbol: str, **fields) -> bool:
        ref = self._watch_ref(user_key).document(_clean_symbol(symbol))
        if not ref.get().exists:
            return False
        fields = {k: v for k, v in fields.items() if v is not None}
        fields['updated_at'] = _utcnow()
        ref.set(fields, merge=True)
        return True

    def count_watchlist(self, user_key: str) -> int:
        return len(list(self._watch_ref(user_key).stream()))

    # schedules
    def get_schedule(self, user_key: str) -> Optional[Dict]:
        doc = self.client.collection('schedules').document(user_key).get()
        return doc.to_dict() if doc.exists else None

    def upsert_schedule(self, user_key: str, **fields) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        fields['updated_at'] = _utcnow()
        self.client.collection('schedules').document(user_key).set(fields, merge=True)

    def list_active_schedules(self, alert_time: str) -> List[Dict]:
        query = (
            self.client.collection('schedules')
            .where('is_active', '==', True)
            .where('alert_time', '==', alert_time)
        )
        return [doc.to_dict() for doc in query.stream()]

    # market snapshots (15-min shared cache) — one doc per symbol
    def get_valid_snapshot(self, symbol: str) -> Optional[Dict]:
        doc = self.client.collection('market_snapshots').document(_clean_symbol(symbol)).get()
        if not doc.exists:
            return None
        rec = doc.to_dict() or {}
        if rec.get('expires_at') and rec['expires_at'] > _utcnow():
            return {'id': doc.id, **rec}
        return None

    def save_snapshot(self, symbol: str, data: Dict, provider: str, ttl_minutes: int) -> str:
        clean = _clean_symbol(symbol)
        now = _utcnow()
        ref = self.client.collection('market_snapshots').document(clean)
        ref.set({
            'symbol': clean, 'data': data, 'provider': provider,
            'collected_at': now, 'expires_at': now + timedelta(minutes=ttl_minutes),
        })
        return clean

    def save_source_documents(self, snapshot_id: str, sources: List[Dict]) -> None:
        import uuid
        col = self.client.collection('source_documents')
        for src in sources:
            col.document(uuid.uuid4().hex).set({**src, 'snapshot_id': snapshot_id, 'created_at': _utcnow()})

    # financial cache (24h)
    def get_financial_cache(self, symbol: str, max_age_hours: int) -> Optional[Dict]:
        doc = self.client.collection('financial_cache').document(_clean_symbol(symbol)).get()
        if not doc.exists:
            return None
        rec = doc.to_dict() or {}
        if rec.get('collected_at') and rec['collected_at'] > _utcnow() - timedelta(hours=max_age_hours):
            return {'data': rec.get('data'), 'source': rec.get('source')}
        return None

    def save_financial_cache(self, symbol: str, data: Dict, source: str) -> None:
        self.client.collection('financial_cache').document(_clean_symbol(symbol)).set({
            'data': data, 'source': source, 'collected_at': _utcnow(),
        })

    # analysis runs / agent outputs
    def create_analysis_run(self, user_key: Optional[str], symbol: str) -> str:
        import uuid
        run_id = uuid.uuid4().hex
        self.client.collection('analysis_runs').document(run_id).set({
            'user_key': user_key, 'symbol': _clean_symbol(symbol), 'status': 'running',
            'snapshot_id': None, 'result': None, 'error_message': None,
            'created_at': _utcnow(), 'completed_at': None,
        })
        return run_id

    def update_analysis_run(self, run_id: str, **fields) -> None:
        self.client.collection('analysis_runs').document(run_id).set(fields, merge=True)

    def add_agent_output(self, run_id: str, agent_name: str, output_json: str) -> None:
        import uuid
        self.client.collection('agent_outputs').document(uuid.uuid4().hex).set({
            'analysis_run_id': run_id, 'agent_name': agent_name,
            'output_json': output_json, 'created_at': _utcnow(),
        })

    # report deliveries (idempotency)
    def get_delivery(self, idempotency_key: str) -> Optional[Dict]:
        doc = self.client.collection('report_deliveries').document(idempotency_key).get()
        return doc.to_dict() if doc.exists else None

    def upsert_delivery(self, idempotency_key: str, user_key: str, status: str,
                        error_message: Optional[str] = None) -> None:
        payload = {'user_key': user_key, 'status': status, 'error_message': error_message,
                   'updated_at': _utcnow()}
        if status == 'sent':
            payload['sent_at'] = _utcnow()
        self.client.collection('report_deliveries').document(idempotency_key).set(payload, merge=True)

    # global stock info cache
    def get_global_stock_info(self, symbol: str) -> Optional[Dict]:
        doc = self.client.collection('global_stock_info').document(_clean_symbol(symbol)).get()
        return doc.to_dict() if doc.exists else None

    def save_global_stock_info(self, symbol: str, **fields) -> None:
        fields['updated_at'] = _utcnow()
        self.client.collection('global_stock_info').document(_clean_symbol(symbol)).set(fields, merge=True)

    def prune_global_stock_info(self, max_age_hours: int) -> int:
        cutoff = _utcnow() - timedelta(hours=max_age_hours)
        removed = 0
        for doc in self.client.collection('global_stock_info').stream():
            updated = doc.to_dict().get('updated_at')
            if updated and updated < cutoff:
                doc.reference.delete()
                removed += 1
        return removed


# ---------------------------------------------------------------------------
# Backend selection — Firestore on GCP, memory fallback for dev/tests
# ---------------------------------------------------------------------------

def _create_backend():
    mode = (os.getenv('DATA_BACKEND') or 'auto').lower()
    if mode in ('memory', 'local', 'test'):
        return MemoryBackend()
    try:
        from google.cloud import firestore as fs

        project = os.getenv('GCP_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT')
        database = os.getenv('FIRESTORE_DATABASE', 'agent-stocks')
        kwargs: Dict[str, Any] = {'database': database}
        if project:
            kwargs['project'] = project
        try:
            client = fs.Client(**kwargs)
            # Fail-fast probe so a wrong database name is caught at startup
            list(client.collection('_health_probe').limit(1).stream())
        except Exception:
            if database not in ('(default)', 'default'):
                # Retry against the default database before giving up
                kwargs['database'] = '(default)'
                client = fs.Client(**kwargs)
                list(client.collection('_health_probe').limit(1).stream())
                database = '(default)'
            else:
                raise
        print(f'[STORE] Firestore backend ready (database={database})')
        return FirestoreBackend(client)
    except Exception as exc:
        if mode == 'firestore':
            raise
        print(f'[STORE] Firestore unavailable ({exc}); using in-memory backend (dev/test only, data is not persisted)')
        return MemoryBackend()


backend = _create_backend()


# ---------------------------------------------------------------------------
# Module-level API (call sites import these — no sessions, no ORM)
# ---------------------------------------------------------------------------

def get_or_create_user(user_key: str, display_name: str = '') -> Dict:
    return backend.get_or_create_user(user_key, display_name)


def get_user(user_key: str) -> Optional[Dict]:
    return backend.get_user(user_key)


def update_user(user_key: str, updates: Dict) -> None:
    backend.update_user(user_key, updates)


def set_chat_state(user_key: str, state: Optional[str]) -> None:
    backend.set_chat_state(user_key, state)


def get_chat_state(user_key: str) -> Optional[str]:
    return backend.get_chat_state(user_key)


def list_watchlist(user_key: str) -> List[Dict]:
    return backend.list_watchlist(user_key)


def get_watch_item(user_key: str, symbol: str) -> Optional[Dict]:
    return backend.get_watch_item(user_key, symbol)


def add_watch_item(user_key: str, symbol: str, **settings) -> bool:
    return backend.add_watch_item(user_key, symbol, **settings)


def delete_watch_item(user_key: str, symbol: str) -> bool:
    return backend.delete_watch_item(user_key, symbol)


def update_watch_item(user_key: str, symbol: str, **fields) -> bool:
    return backend.update_watch_item(user_key, symbol, **fields)


def count_watchlist(user_key: str) -> int:
    return backend.count_watchlist(user_key)


def get_schedule(user_key: str) -> Optional[Dict]:
    return backend.get_schedule(user_key)


def upsert_schedule(user_key: str, **fields) -> None:
    backend.upsert_schedule(user_key, **fields)


def list_active_schedules(alert_time: str) -> List[Dict]:
    return backend.list_active_schedules(alert_time)


def get_valid_snapshot(symbol: str) -> Optional[Dict]:
    return backend.get_valid_snapshot(symbol)


def save_snapshot(symbol: str, data: Dict, provider: str, ttl_minutes: int) -> str:
    return backend.save_snapshot(symbol, data, provider, ttl_minutes)


def save_source_documents(snapshot_id: str, sources: List[Dict]) -> None:
    backend.save_source_documents(snapshot_id, sources)


def get_financial_cache(symbol: str, max_age_hours: int) -> Optional[Dict]:
    return backend.get_financial_cache(symbol, max_age_hours)


def save_financial_cache(symbol: str, data: Dict, source: str) -> None:
    backend.save_financial_cache(symbol, data, source)


def create_analysis_run(user_key: Optional[str], symbol: str) -> str:
    return backend.create_analysis_run(user_key, symbol)


def update_analysis_run(run_id: str, **fields) -> None:
    backend.update_analysis_run(run_id, **fields)


def add_agent_output(run_id: str, agent_name: str, output_json: str) -> None:
    backend.add_agent_output(run_id, agent_name, output_json)


def get_delivery(idempotency_key: str) -> Optional[Dict]:
    return backend.get_delivery(idempotency_key)


def upsert_delivery(idempotency_key: str, user_key: str, status: str,
                    error_message: Optional[str] = None) -> None:
    backend.upsert_delivery(idempotency_key, user_key, status, error_message)


def get_global_stock_info(symbol: str) -> Optional[Dict]:
    return backend.get_global_stock_info(symbol)


def save_global_stock_info(symbol: str, **fields) -> None:
    backend.save_global_stock_info(symbol, **fields)


def prune_global_stock_info(max_age_hours: int) -> int:
    return backend.prune_global_stock_info(max_age_hours)


def backend_name() -> str:
    return 'firestore' if isinstance(backend, FirestoreBackend) else 'memory'
