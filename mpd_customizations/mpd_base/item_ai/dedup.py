import json
import pickle

import frappe
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

REDIS_MATRIX_KEY = "mpd:item_tfidf_matrix"


# ─── Cache build ──────────────────────────────────────────────────────────────

def build_search_index():
    """
    Fetches all active items from DB, fits a TF-IDF vectorizer on their
    names, and stores the vectorizer + matrix + item records in Redis.
    Called on item approval and when manually triggered.
    """
    from datetime import datetime

    items = frappe.get_all(
        "Item",
        filters={"disabled": 0},
        fields=[
            "name", "item_name", "item_group",
            "custom_tally_name", "custom_tally_alias",
            "custom_legacy_code", "gst_hsn_code",
        ],
    )

    # Update settings regardless — even if 0 items, timestamp should update
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frappe.db.set_value("Item Search Settings", "Item Search Settings",
                        "index_last_built_on", now)
    frappe.db.set_value("Item Search Settings", "Item Search Settings",
                        "total_items_indexed", len(items))
    frappe.db.commit()

    if not items:
        _clear_cache()
        return

    corpus = []
    for item in items:
        parts = [item.item_name or ""]
        if item.tally_name:           parts.append(item.tally_name)
        if item.tally_alias:          parts.append(item.tally_alias)
        if item.legacy_material_code: parts.append(item.legacy_material_code)
        corpus.append(" ".join(parts))

    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(corpus)

    payload = {
        "vectorizer": vectorizer,
        "matrix":     matrix,
        "items":      [dict(i) for i in items],
    }

    frappe.cache().set_value(REDIS_MATRIX_KEY, pickle.dumps(payload))

def _clear_cache():
    frappe.cache().delete_value(REDIS_MATRIX_KEY)


def _load_cache():
    """
    Loads the cached payload from Redis.
    Returns None if cache is empty — caller must handle and rebuild.
    """
    raw = frappe.cache().get_value(REDIS_MATRIX_KEY)
    if not raw:
        return None
    return pickle.loads(raw)


# ─── Dedup check ──────────────────────────────────────────────────────────────
@frappe.whitelist()
def check_item_duplicates_and_set_status(request_name, description,
                                          tally_name=None, tally_alias=None,
                                          legacy_material_code=None):
    """
    Runs the duplicate check.
    If no candidates found — auto-confirms dedup on server, sets Dedup Confirmed.
    If candidates found — sets Pending Dedup Check and returns them for user review.
    Client only needs one reload either way.
    """
    candidates = check_item_duplicates(
        description=description,
        tally_name=tally_name,
        tally_alias=tally_alias,
        legacy_material_code=legacy_material_code,
    )

    if not candidates:
        # No similar items — auto confirm, no user action needed
        frappe.db.set_value(
            "Item Request", request_name,
            {
                "status": "Dedup Confirmed",
                "dedup_check_done": 1,
            }
        )
    else:
        # Candidates found — wait for user acknowledgement
        frappe.db.set_value(
            "Item Request", request_name,
            "status", "Pending Dedup Check"
        )

    frappe.db.commit()
    return candidates

def check_item_duplicates(description, tally_name=None, tally_alias=None,
                          legacy_material_code=None):
    """
    Returns top 5 most similar existing items using TF-IDF cosine similarity.
    Builds the cache on first call if it doesn't exist yet.
    """
    payload = _load_cache()
    if payload is None:
        # First ever call or cache was cleared — build it now
        build_search_index()
        payload = _load_cache()

    if payload is None:
        # No items in the system yet — nothing to compare against
        return []

    vectorizer = payload["vectorizer"]
    matrix     = payload["matrix"]
    items      = payload["items"]

    settings  = frappe.get_single("Item Search Settings")
    threshold = settings.similarity_threshold or 0.3

    # Build query string — same logic as corpus build
    parts = [description]
    if tally_name:           parts.append(tally_name)
    if tally_alias:          parts.append(tally_alias)
    if legacy_material_code: parts.append(legacy_material_code)
    query = " ".join(parts)

    query_vec   = vectorizer.transform([query])
    similarities = cosine_similarity(query_vec, matrix).flatten()

    # Get indices sorted by similarity descending
    top_indices = np.argsort(similarities)[::-1]

    results = []
    for idx in top_indices:
        score = float(similarities[idx])
        if score < threshold:
            break
        results.append({
            **items[idx],
            "similarity_score": round(score, 3),
        })
        if len(results) == 5:
            break

    return results


# ─── Confirm / reset ──────────────────────────────────────────────────────────

@frappe.whitelist()
def confirm_dedup(request_name):
    frappe.db.set_value(
        "Item Request", request_name,
        {"dedup_check_done": 1, "status": "Dedup Confirmed"}
    )
    frappe.db.commit()
    return {"status": "confirmed"}


@frappe.whitelist()
def reset_dedup(request_name):
    frappe.db.set_value("Item Request", request_name, "dedup_check_done", 0)
    frappe.db.commit()
    return {"status": "reset"}


# ─── Manual rebuild (called from Single DocType button) ───────────────────────

@frappe.whitelist()
def rebuild_search_index():
    """
    Whitelisted so the Item Search Settings form can trigger a rebuild
    via a custom button.
    """
    build_search_index()
    frappe.msgprint("Search index rebuilt successfully.", alert=True)