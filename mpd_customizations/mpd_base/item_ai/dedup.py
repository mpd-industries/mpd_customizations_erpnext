import pickle
import re

import frappe
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

REDIS_MATRIX_KEY = "mpd:item_tfidf_matrix"
HSN_SCORE_BOOST = 0.15


# ─── HSN helpers ──────────────────────────────────────────────────────────────

def normalize_hsn(hsn: str | None) -> str:
    """Digits only from an HSN/SAC code."""
    if not hsn:
        return ""
    return re.sub(r"\D", "", str(hsn).strip())


def hsn_compatible(query_hsn: str | None, item_hsn: str | None) -> bool:
    """True when HSN codes share a prefix (e.g. 7307 vs 73072100) or either is empty."""
    q = normalize_hsn(query_hsn)
    i = normalize_hsn(item_hsn)
    if not q or not i:
        return True
    return q.startswith(i) or i.startswith(q)


def _build_item_corpus_text(item: dict) -> str:
    parts = [item.get("item_name") or ""]
    if item.get("custom_tally_name"):
        parts.append(item["custom_tally_name"])
    if item.get("custom_tally_alias"):
        parts.append(item["custom_tally_alias"])
    if item.get("custom_legacy_code"):
        parts.append(item["custom_legacy_code"])
    hsn = normalize_hsn(item.get("gst_hsn_code"))
    if hsn:
        parts.append(hsn)
    return " ".join(p for p in parts if p)


def _build_query_text(
    description: str,
    tally_name=None,
    tally_alias=None,
    legacy_material_code=None,
    hsn_code=None,
) -> str:
    parts = [description or ""]
    if tally_name:
        parts.append(tally_name)
    if tally_alias:
        parts.append(tally_alias)
    if legacy_material_code:
        parts.append(legacy_material_code)
    hsn = normalize_hsn(hsn_code)
    if hsn:
        parts.append(hsn)
    return " ".join(p for p in parts if p)


def _apply_hsn_score_adjustment(results: list[dict], query_hsn: str | None) -> list[dict]:
    """Boost compatible HSN candidates; re-sort by adjusted score."""
    if not results or not normalize_hsn(query_hsn):
        return results

    adjusted = []
    for row in results:
        score = float(row.get("similarity_score") or 0)
        if hsn_compatible(query_hsn, row.get("gst_hsn_code")):
            score = min(1.0, score + HSN_SCORE_BOOST)
        row = {**row, "similarity_score": round(score, 3)}
        adjusted.append(row)

    adjusted.sort(key=lambda r: r["similarity_score"], reverse=True)
    return adjusted


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

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frappe.db.set_value("Item Search Settings", "Item Search Settings",
                        "index_last_built_on", now)
    frappe.db.set_value("Item Search Settings", "Item Search Settings",
                        "total_items_indexed", len(items))
    frappe.db.commit()

    if not items:
        _clear_cache()
        return

    corpus = [_build_item_corpus_text(dict(i)) for i in items]

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
    """Loads the cached payload from Redis. Returns None if cache is empty."""
    raw = frappe.cache().get_value(REDIS_MATRIX_KEY)
    if not raw:
        return None
    return pickle.loads(raw)


# ─── Dedup check ──────────────────────────────────────────────────────────────

@frappe.whitelist()
def check_item_duplicates_and_set_status(
    request_name,
    description,
    tally_name=None,
    tally_alias=None,
    legacy_material_code=None,
    hsn_code=None,
):
    """
    Runs the duplicate check.
    If no candidates found — auto-confirms dedup on server, sets Dedup Confirmed.
    If candidates found — sets Pending Dedup Check and returns them for user review.
    """
    candidates = check_item_duplicates(
        description=description,
        tally_name=tally_name,
        tally_alias=tally_alias,
        legacy_material_code=legacy_material_code,
        hsn_code=hsn_code,
    )

    if not candidates:
        frappe.db.set_value(
            "Item Request", request_name,
            {
                "status": "Dedup Confirmed",
                "dedup_check_done": 1,
            }
        )
    else:
        frappe.db.set_value(
            "Item Request", request_name,
            "status", "Pending Dedup Check"
        )

    frappe.db.commit()
    return candidates


def check_item_duplicates(
    description,
    tally_name=None,
    tally_alias=None,
    legacy_material_code=None,
    hsn_code=None,
):
    """
    Returns top 5 most similar existing items using TF-IDF cosine similarity.
    Builds the cache on first call if it doesn't exist yet.
    Scores are retrieval hints only — callers (e.g. LLM) make the final match decision.
    """
    payload = _load_cache()
    if payload is None:
        build_search_index()
        payload = _load_cache()

    if payload is None:
        return []

    vectorizer = payload["vectorizer"]
    matrix     = payload["matrix"]
    items      = payload["items"]

    settings  = frappe.get_single("Item Search Settings")
    threshold = settings.similarity_threshold or 0.3

    query = _build_query_text(
        description,
        tally_name=tally_name,
        tally_alias=tally_alias,
        legacy_material_code=legacy_material_code,
        hsn_code=hsn_code,
    )

    query_vec   = vectorizer.transform([query])
    similarities = cosine_similarity(query_vec, matrix).flatten()

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

    return _apply_hsn_score_adjustment(results, hsn_code)


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
    """Whitelisted so the Item Search Settings form can trigger a rebuild."""
    build_search_index()
    frappe.msgprint("Search index rebuilt successfully.", alert=True)
