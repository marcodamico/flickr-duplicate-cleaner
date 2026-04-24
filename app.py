# app.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

from flask import Flask, render_template, jsonify, request
import json
import threading
import os
import signal
from detector import FlickrDetector
import db
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
detector = FlickrDetector()

scan_thread = None
scan_results = []
duplicates_cache = {"mtime": None, "data": []}
duplicates_lock = threading.Lock()
nsfw_results_cache = {"mtime": None, "data": []}
nsfw_results_lock = threading.Lock()


def _get_duplicates_data():
    duplicates_file = "duplicates.json"
    if not os.path.exists(duplicates_file):
        return []

    mtime = os.path.getmtime(duplicates_file)
    with duplicates_lock:
        if duplicates_cache["mtime"] != mtime:
            try:
                with open(duplicates_file) as f:
                    duplicates_cache["data"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                duplicates_cache["data"] = []
            duplicates_cache["mtime"] = mtime
        return duplicates_cache["data"]


def _get_nsfw_results_data():
    nsfw_file = "nsfw_results.json"
    if not os.path.exists(nsfw_file):
        return []

    mtime = os.path.getmtime(nsfw_file)
    with nsfw_results_lock:
        if nsfw_results_cache["mtime"] != mtime:
            try:
                with open(nsfw_file) as f:
                    nsfw_results_cache["data"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                nsfw_results_cache["data"] = []
            nsfw_results_cache["mtime"] = mtime
        return nsfw_results_cache["data"]


def _remove_photos_from_duplicates(photo_ids):
    if not photo_ids:
        return

    data = _get_duplicates_data()
    changed = False
    id_set = set(photo_ids)
    next_groups = []
    for group in data:
        photos = group.get("photos", [])
        kept = [p for p in photos if p.get("id") not in id_set]
        if len(kept) != len(photos):
            changed = True
        if len(kept) >= 2:
            updated = group.copy()
            updated["photos"] = kept
            updated["size"] = len(kept)
            next_groups.append(updated)
        elif len(kept) != len(photos):
            changed = True

    if not changed:
        return

    with duplicates_lock:
        with open("duplicates.json", "w") as f:
            json.dump(next_groups, f, indent=2)
        duplicates_cache["data"] = next_groups
        duplicates_cache["mtime"] = os.path.getmtime("duplicates.json")


def _remove_photos_from_nsfw_results(photo_ids):
    if not photo_ids:
        return

    data = _get_nsfw_results_data()
    changed = False
    id_set = set(photo_ids)
    next_groups = []
    for group in data:
        photos = group.get("photos", [])
        kept = [p for p in photos if p.get("id") not in id_set]
        if len(kept) != len(photos):
            changed = True
        if len(kept) >= 1:
            updated = group.copy()
            updated["photos"] = kept
            updated["size"] = len(kept)
            next_groups.append(updated)
        elif len(kept) != len(photos):
            changed = True

    if not changed:
        return

    with nsfw_results_lock:
        with open("nsfw_results.json", "w") as f:
            json.dump(next_groups, f, indent=2)
        nsfw_results_cache["data"] = next_groups
        nsfw_results_cache["mtime"] = os.path.getmtime("nsfw_results.json")


def _apply_nsfw_override_in_duplicates(photo_id, override_value):
    data = _get_duplicates_data()
    changed = False
    for group in data:
        for photo in group.get("photos", []):
            if photo.get("id") == photo_id:
                photo["nsfw_override"] = override_value
                if override_value in ("safe", "possible_nsfw", "nsfw"):
                    photo["nsfw_label"] = override_value
                changed = True
    if not changed:
        return
    with duplicates_lock:
        with open("duplicates.json", "w") as f:
            json.dump(data, f, indent=2)
        duplicates_cache["data"] = data
        duplicates_cache["mtime"] = os.path.getmtime("duplicates.json")


def _apply_nsfw_override_in_nsfw_results(photo_id, override_value):
    data = _get_nsfw_results_data()
    changed = False
    for group in data:
        for photo in group.get("photos", []):
            if photo.get("id") == photo_id:
                photo["nsfw_override"] = override_value
                if override_value in ("safe", "possible_nsfw", "nsfw"):
                    photo["nsfw_label"] = override_value
                changed = True
    if not changed:
        return
    with nsfw_results_lock:
        with open("nsfw_results.json", "w") as f:
            json.dump(data, f, indent=2)
        nsfw_results_cache["data"] = data
        nsfw_results_cache["mtime"] = os.path.getmtime("nsfw_results.json")


def _resolve_photos_in_duplicates(photo_ids):
    if not photo_ids:
        return
    data = _get_duplicates_data()
    changed = False
    id_set = set(photo_ids)
    next_groups = []
    for group in data:
        photos = group.get("photos", [])
        kept = [p for p in photos if p.get("id") not in id_set]
        if len(kept) != len(photos):
            changed = True
        if len(kept) >= 2:
            updated = group.copy()
            updated["photos"] = kept
            updated["size"] = len(kept)
            next_groups.append(updated)
        elif len(kept) != len(photos):
            changed = True
    if not changed:
        return
    with duplicates_lock:
        with open("duplicates.json", "w") as f:
            json.dump(next_groups, f, indent=2)
        duplicates_cache["data"] = next_groups
        duplicates_cache["mtime"] = os.path.getmtime("duplicates.json")


def _resolve_photos_in_nsfw_results(photo_ids):
    if not photo_ids:
        return
    data = _get_nsfw_results_data()
    changed = False
    id_set = set(photo_ids)
    next_groups = []
    for group in data:
        photos = group.get("photos", [])
        kept = [p for p in photos if p.get("id") not in id_set]
        if len(kept) != len(photos):
            changed = True
        if len(kept) >= 1:
            updated = group.copy()
            updated["photos"] = kept
            updated["size"] = len(kept)
            next_groups.append(updated)
        elif len(kept) != len(photos):
            changed = True
    if not changed:
        return
    with nsfw_results_lock:
        with open("nsfw_results.json", "w") as f:
            json.dump(next_groups, f, indent=2)
        nsfw_results_cache["data"] = next_groups
        nsfw_results_cache["mtime"] = os.path.getmtime("nsfw_results.json")


def run_scan_in_background(threshold, global_search, use_cache, scan_mode="duplicates"):
    global scan_results
    try:
        if scan_mode == "nsfw":
            scan_results = detector.find_nsfw(
                use_cache=use_cache,
                include_possible=True,
            )
        else:
            scan_results = detector.find_duplicates(
                threshold=threshold,
                global_search=global_search,
                use_cache=use_cache,
                nsfw_mode="off",
            )
    except Exception as e:
        print(f"Scan error: {e}")
        detector.status["message"] = f"Error: {str(e)}"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/duplicates")
def get_duplicates():
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters"}), 400

    data = _get_duplicates_data()
    # Legacy pair-format results are treated as stale and hidden.
    if data and isinstance(data[0], dict) and "photos" not in data[0]:
        return jsonify({
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit
        })

    total = len(data)
    items = data[offset:offset + limit]
    return jsonify({
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit
    })


@app.route("/api/nsfw-results")
def get_nsfw_results():
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters"}), 400

    data = _get_nsfw_results_data()
    total = len(data)
    items = data[offset:offset + limit]
    return jsonify({
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit
    })

@app.route("/api/scan", methods=["POST"])
def scan_duplicates():
    global scan_thread
    data = request.json
    threshold = data.get("threshold", 5)
    global_search = data.get("global_search", False)
    use_cache = data.get("use_cache", False)
    scan_mode = data.get("scan_mode", "duplicates")

    if scan_mode not in ("duplicates", "nsfw"):
        return jsonify({"error": "Invalid scan_mode"}), 400

    if scan_thread and scan_thread.is_alive():
        return jsonify({"error": "Scan already in progress"}), 400

    scan_thread = threading.Thread(
        target=run_scan_in_background,
        args=(threshold, global_search, use_cache, scan_mode),
        daemon=True  # Dies automatically when main process exits
    )
    scan_thread.start()
    return jsonify({"status": "started"})

@app.route("/api/status")
def get_status():
    status = detector.status.copy()
    status["is_running"] = scan_thread is not None and scan_thread.is_alive()
    status["db_count"] = db.get_hash_count()
    return jsonify(status)

@app.route("/api/cancel", methods=["POST"])
def cancel_scan():
    detector.cancel()
    return jsonify({"status": "cancelling"})

@app.route("/api/delete", methods=["POST"])
def delete_photo():
    photo_id = request.json["photo_id"]
    try:
        detector.flickr.photos.delete(photo_id=photo_id)
        db.delete_hashes([photo_id])
        detector.mark_deleted_photos([photo_id])
        _remove_photos_from_duplicates([photo_id])
        _remove_photos_from_nsfw_results([photo_id])
        return {"status": "ok"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/delete-batch", methods=["POST"])
def delete_batch():
    data = request.json or {}
    photo_ids = data.get("photo_ids", [])
    if not isinstance(photo_ids, list) or not photo_ids:
        return jsonify({"error": "photo_ids must be a non-empty list"}), 400

    results = []
    successful_ids = []
    for photo_id in photo_ids:
        try:
            detector.flickr.photos.delete(photo_id=photo_id)
            successful_ids.append(photo_id)
            results.append({"photo_id": photo_id, "status": "ok"})
        except Exception as e:
            results.append({"photo_id": photo_id, "status": "error", "error": str(e)})

    if successful_ids:
        db.delete_hashes(successful_ids)
        detector.mark_deleted_photos(successful_ids)
        _remove_photos_from_duplicates(successful_ids)
        _remove_photos_from_nsfw_results(successful_ids)

    return jsonify({"results": results})

@app.route("/api/photo-original-info/<photo_id>")
def get_photo_original_info(photo_id):
    try:
        return jsonify(detector.get_original_info(photo_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nsfw/override", methods=["POST"])
def set_nsfw_override():
    data = request.json or {}
    photo_id = data.get("photo_id")
    override_value = data.get("override")
    if not photo_id:
        return jsonify({"error": "photo_id is required"}), 400
    if override_value not in (None, "", "safe", "possible_nsfw", "nsfw"):
        return jsonify({"error": "Invalid override value"}), 400

    normalized = override_value if override_value else None
    db.save_nsfw_override(photo_id, normalized)
    _apply_nsfw_override_in_duplicates(photo_id, normalized)
    _apply_nsfw_override_in_nsfw_results(photo_id, normalized)
    return jsonify({"status": "ok", "photo_id": photo_id, "override": normalized})

@app.route("/api/resolve", methods=["POST"])
def resolve_duplicates():
    data = request.json or {}
    photo_ids = data.get("photo_ids", [])
    mode = data.get("mode", "duplicates")
    if not isinstance(photo_ids, list) or not photo_ids:
        return jsonify({"error": "photo_ids must be a non-empty list"}), 400
    if mode == "nsfw":
        _resolve_photos_in_nsfw_results(photo_ids)
    else:
        _resolve_photos_in_duplicates(photo_ids)
    return jsonify({"status": "ok", "resolved_count": len(photo_ids)})

def _handle_shutdown(signum, frame):
    print("\nShutting down: cancelling scan...")
    detector.cancel()
    os._exit(0)

signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)

if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
