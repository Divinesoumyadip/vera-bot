import threading
import time
from typing import Dict, Optional, Tuple


class ContextStore:
    def __init__(self, conversation_ttl_s: int = 86400 * 7, suppression_ttl_s: int = 86400 * 3):
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Dict]] = {
            "category": {}, "merchant": {}, "customer": {}, "trigger": {}
        }
        self._conversations: Dict[str, Dict] = {}
        self._suppressed: Dict[str, float] = {}
        self._merchant_auto_counts: Dict[str, int] = {}
        self._tick_idempotency: Dict[str, list] = {}
        self.conversation_ttl_s = conversation_ttl_s
        self.suppression_ttl_s = suppression_ttl_s
        self._last_gc = time.time()

    def _maybe_gc(self):
        now = time.time()
        if now - self._last_gc < 300:
            return
        self._last_gc = now
        cutoff_supp = now - self.suppression_ttl_s
        self._suppressed = {k: v for k, v in self._suppressed.items() if v > cutoff_supp}
        cutoff_conv = now - self.conversation_ttl_s
        self._conversations = {
            k: v for k, v in self._conversations.items()
            if v.get("last_active", now) > cutoff_conv
        }

    def upsert(self, scope: str, context_id: str, version: int, payload: dict) -> str:
        with self._lock:
            self._maybe_gc()
            existing = self._data[scope].get(context_id)
            if existing:
                ev = existing["version"]
                if version == ev:
                    return "noop"
                if version < ev:
                    return "stale"
            self._data[scope][context_id] = {"version": version, "payload": payload, "stored_at": time.time()}
            return "ok"

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        with self._lock:
            entry = self._data[scope].get(context_id)
            return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        with self._lock:
            entry = self._data[scope].get(context_id)
            return entry["version"] if entry else None

    def all_of(self, scope: str) -> Dict[str, dict]:
        with self._lock:
            return {cid: e["payload"] for cid, e in self._data[scope].items()}

    def counts(self) -> dict:
        with self._lock:
            return {s: len(v) for s, v in self._data.items()}

    def get_merchant_with_category(self, merchant_id: str) -> Tuple[Optional[dict], Optional[dict]]:
        merchant = self.get("merchant", merchant_id)
        if not merchant:
            return None, None
        category = self.get("category", merchant.get("category_slug", ""))
        return merchant, category

    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        return self._conversations.get(conversation_id)

    def append_turn(self, conversation_id: str, role: str, message: str):
        with self._lock:
            conv = self._conversations.setdefault(conversation_id, {
                "history": [], "suppressed": False, "created_at": time.time()
            })
            conv["history"].append({"role": role, "message": message, "ts": time.time()})
            conv["last_active"] = time.time()
            if len(conv["history"]) > 50:
                conv["history"] = conv["history"][-50:]

    def suppress_conversation(self, conversation_id: str):
        with self._lock:
            conv = self._conversations.setdefault(conversation_id, {"history": [], "created_at": time.time()})
            conv["suppressed"] = True
            conv["last_active"] = time.time()

    def is_conversation_suppressed(self, conversation_id: str) -> bool:
        return self._conversations.get(conversation_id, {}).get("suppressed", False)

    def is_suppressed(self, key: str) -> bool:
        with self._lock:
            ts = self._suppressed.get(key)
            if ts is None:
                return False
            if time.time() - ts > self.suppression_ttl_s:
                del self._suppressed[key]
                return False
            return True

    def add_suppression(self, key: str):
        with self._lock:
            self._suppressed[key] = time.time()

    def get_merchant_auto_count(self, merchant_id: str) -> int:
        return self._merchant_auto_counts.get(merchant_id, 0)

    def bump_merchant_auto_count(self, merchant_id: str) -> int:
        with self._lock:
            self._merchant_auto_counts[merchant_id] = self._merchant_auto_counts.get(merchant_id, 0) + 1
            return self._merchant_auto_counts[merchant_id]

    def reset_merchant_auto_count(self, merchant_id: str):
        with self._lock:
            self._merchant_auto_counts.pop(merchant_id, None)

    def check_tick_idempotency(self, idempotency_key: str) -> Optional[list]:
        return self._tick_idempotency.get(idempotency_key)

    def store_tick_result(self, idempotency_key: str, result: list):
        with self._lock:
            self._tick_idempotency[idempotency_key] = result
            if len(self._tick_idempotency) > 1000:
                keys = list(self._tick_idempotency.keys())[:500]
                for k in keys:
                    self._tick_idempotency.pop(k, None)
