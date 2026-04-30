import os
import json
import logging

log = logging.getLogger("vera.bootstrap")

ID_FIELDS = {
    "category": "slug",
    "merchant": "merchant_id",
    "customer": "customer_id",
    "trigger": "id",
}


def bootstrap_dataset(store):
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset"),
        "/app/dataset",
        "dataset",
        os.path.join(os.getcwd(), "dataset"),
    ]

    base = None
    for c in candidates:
        if os.path.isdir(c):
            base = c
            break

    if not base:
        log.warning(f"No bundled dataset found. Tried: {candidates}")
        return

    log.info(f"Loading dataset from: {base}")
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}

    for scope, subdir in [
        ("category", "categories"),
        ("merchant", "merchants"),
        ("customer", "customers"),
        ("trigger", "triggers"),
    ]:
        dpath = os.path.join(base, subdir)
        if not os.path.isdir(dpath):
            continue
        for fname in sorted(os.listdir(dpath)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(dpath, fname), "r", encoding="utf-8") as f:
                    obj = json.load(f)
                cid = obj.get(ID_FIELDS[scope])
                if cid:
                    store.upsert(scope, cid, 1, obj)
                    counts[scope] += 1
            except Exception as e:
                log.warning(f"Skipping {fname}: {e}")

    log.info(f"Bootstrapped: {counts}")