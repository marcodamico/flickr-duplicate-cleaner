# detector.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from itertools import combinations

import flickrapi
import imagehash
import requests
from PIL import Image
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import db
from nsfw_detector import NsfwDetector, NSFW_MODEL_VERSION

load_dotenv()

API_KEY = os.getenv("FLICKR_API_KEY")
API_SECRET = os.getenv("FLICKR_API_SECRET")
MISSING_PHOTOS_FILE = "missing_photos.json"
PHOTO_CACHE_FILE = "photo_cache.json"

class FlickrDetector:
    def __init__(self):
        if not API_KEY or not API_SECRET:
            raise ValueError("FLICKR_API_KEY and FLICKR_API_SECRET must be set in .env")

        self.flickr = flickrapi.FlickrAPI(API_KEY, API_SECRET, format="parsed-json")
        self.flickr.authenticate_via_browser(perms="delete")
        self.user_id = self.flickr.test.login()["user"]["id"]
        self.status = {"total": 0, "current": 0, "message": "Idle"}
        self.cancelled = False
        self._lock = threading.Lock()
        self._hash_cache = {}
        self._nsfw_cache = {}
        self._nsfw_cache_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0
        self._original_info_cache = {}
        self._nsfw_detector = NsfwDetector()
        self._missing_lock = threading.Lock()
        self._missing_photo_ids = self._load_missing_photo_ids()

        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _load_missing_photo_ids(self):
        if not os.path.exists(MISSING_PHOTOS_FILE):
            return set()
        try:
            with open(MISSING_PHOTOS_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return set()
            return {str(pid) for pid in data if pid}
        except Exception:
            return set()

    def _save_missing_photo_ids(self):
        try:
            with open(MISSING_PHOTOS_FILE, "w") as f:
                json.dump(sorted(self._missing_photo_ids), f, indent=2)
        except Exception:
            pass

    def _mark_photo_missing(self, photo_id):
        pid = str(photo_id)
        changed = False
        with self._missing_lock:
            if pid not in self._missing_photo_ids:
                self._missing_photo_ids.add(pid)
                changed = True
        if changed:
            self._save_missing_photo_ids()

        if not os.path.exists(PHOTO_CACHE_FILE):
            return
        try:
            with open(PHOTO_CACHE_FILE, "r") as f:
                cached_photos = json.load(f)
            if not isinstance(cached_photos, list):
                return
            filtered = [p for p in cached_photos if str((p or {}).get("id", "")) != pid]
            if len(filtered) != len(cached_photos):
                with open(PHOTO_CACHE_FILE, "w") as f:
                    json.dump(filtered, f)
        except Exception:
            pass

    def _rate_limited_get(self, url, min_interval=0.5, **kwargs):
        with self._rate_lock:
            now = time.time()
            wait = max(0.0, self._last_request_time + float(min_interval) - now)
            if wait > 0:
                self._stop_event.wait(timeout=wait)
            self._last_request_time = time.time()
        return self.session.get(url, **kwargs)

    def _set_status(self, message=None, total=None, current=None):
        with self._lock:
            if message is not None:
                self.status["message"] = message
            if total is not None:
                self.status["total"] = max(0, int(total))
            if current is not None:
                self.status["current"] = max(0, int(current))

    def _increment_progress(self, delta):
        if delta <= 0:
            return
        with self._lock:
            self.status["current"] += int(delta)
            if self.status["total"] > 0 and self.status["current"] > self.status["total"]:
                self.status["current"] = self.status["total"]

    def cancel(self):
        self.cancelled = True
        self._stop_event.set()
        self.status["message"] = "Scan cancelled."

    def get_all_photos(self):
        photos = []
        page = 1
        while True:
            self._set_status(message=f"Fetching photo list (page {page})...")
            resp = self.flickr.people.getPhotos(
                user_id=self.user_id,
                extras=(
                    "date_taken,url_k,width_k,height_k,url_b,width_b,height_b,"
                    "url_o,width_o,height_o,url_m,width_m,height_m"
                ),
                per_page=500,
                page=page,
            )
            photos.extend(resp["photos"]["photo"])
            if page >= resp["photos"]["pages"]:
                break
            page += 1
        return photos

    def _build_photo_record(
        self,
        photo_id,
        hash_obj,
        title,
        url,
        width,
        height,
        date_taken,
        original_url=None,
        original_width=None,
        original_height=None,
        nsfw_score=None,
        nsfw_label="unknown",
        nsfw_override=None,
    ):
        original_url = original_url or url
        original_width = int(original_width or 0)
        original_height = int(original_height or 0)
        base_label = nsfw_label or "unknown"
        resolved_label = nsfw_override if nsfw_override in {"safe", "possible_nsfw", "nsfw"} else base_label
        return {
            "id": photo_id,
            "hash": hash_obj,
            "hash_str": str(hash_obj),
            "title": title,
            "url": url,
            "width": width or 0,
            "height": height or 0,
            "original_url": original_url,
            "original_width": original_width,
            "original_height": original_height,
            "nsfw_score": nsfw_score,
            "nsfw_label": resolved_label,
            "nsfw_base_label": base_label,
            "nsfw_override": nsfw_override,
            "date_taken": date_taken or "0000-00-00",
        }

    def process_single_photo(self, p):
        if self.cancelled:
            return None

        photo_id = p["id"]
        cached = self._hash_cache.get(photo_id)
        nsfw_cached = self._nsfw_cache.get(photo_id, {})
        if cached and cached[0]:
            self._increment_progress(1)
            return self._build_photo_record(
                photo_id,
                imagehash.hex_to_hash(cached[0]),
                cached[2],
                cached[1],
                cached[3],
                cached[4],
                p.get("datetaken", "0000-00-00"),
                p.get("url_o"),
                p.get("width_o"),
                p.get("height_o"),
                nsfw_cached.get("score"),
                nsfw_cached.get("label") or "unknown",
                nsfw_cached.get("override"),
            )

        best_url = None
        width = 0
        height = 0
        for suffix in ["m", "b", "k", "o"]:
            url = p.get(f"url_{suffix}")
            if url:
                best_url = url
                width = int(p.get(f"width_{suffix}", 0))
                height = int(p.get(f"height_{suffix}", 0))
                break

        if not best_url:
            self._increment_progress(1)
            return None

        resp = None
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            }

            for attempt in range(5):
                resp = self._rate_limited_get(best_url, timeout=15, headers=headers)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    print(f"Rate limited on {photo_id}, waiting {wait}s (attempt {attempt + 1})")
                    self._stop_event.wait(timeout=wait)
                else:
                    break

            if resp.status_code != 200:
                if resp.status_code in (404, 410):
                    self._mark_photo_missing(photo_id)
                print(f"Error processing {photo_id}: status {resp.status_code} for URL {best_url}")
                self._increment_progress(1)
                return None

            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type:
                print(f"Error processing {photo_id}: invalid content type '{content_type}'")
                self._increment_progress(1)
                return None

            img = Image.open(BytesIO(resp.content))
            hash_obj = imagehash.phash(img)

            db.save_hash(
                photo_id,
                str(hash_obj),
                best_url,
                p["title"],
                p.get("datetaken", ""),
                width,
                height,
            )

            self._increment_progress(1)
            return self._build_photo_record(
                photo_id,
                hash_obj,
                p["title"],
                best_url,
                width,
                height,
                p.get("datetaken", "0000-00-00"),
                p.get("url_o"),
                p.get("width_o"),
                p.get("height_o"),
                None,
                "unknown",
                None,
            )
        except Exception as e:
            msg = f"Error processing {photo_id}: {str(e)}"
            if resp is not None:
                msg += f" (Status: {resp.status_code}, Type: {resp.headers.get('Content-Type')})"
            print(msg)
            self._increment_progress(1)
            return None

    def _nsfw_for_photo(self, photo):
        photo_id = photo["id"]
        cached = self._nsfw_cache.get(photo_id, {})
        override = cached.get("override")
        if (
            cached.get("model") == NSFW_MODEL_VERSION
            and cached.get("score") is not None
            and cached.get("label")
        ):
            return cached.get("score"), cached.get("label"), override

        try:
            resp = self._rate_limited_get(photo["url"], timeout=15, min_interval=0.1)
            if resp.status_code != 200:
                if resp.status_code in (404, 410):
                    self._mark_photo_missing(photo_id)
                return None, "unknown", override
            img = Image.open(BytesIO(resp.content))
            score, label = self._nsfw_detector.detect(img)
            updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            db.save_nsfw(photo_id, float(score), label, NSFW_MODEL_VERSION, updated_at)
            with self._nsfw_cache_lock:
                self._nsfw_cache[photo_id] = {
                    "score": float(score),
                    "label": label,
                    "model": NSFW_MODEL_VERSION,
                    "updated_at": updated_at,
                    "override": override,
                }
            return float(score), label, override
        except Exception:
            return None, "unknown", override

    def _apply_nsfw(self, photos, nsfw_mode):
        if nsfw_mode == "off":
            for p in photos:
                override = p.get("nsfw_override")
                base = p.get("nsfw_base_label") or p.get("nsfw_label") or "unknown"
                p["nsfw_base_label"] = base
                p["nsfw_label"] = override if override in {"safe", "possible_nsfw", "nsfw"} else base
            return

        self._set_status(
            message="NSFW mode: scoring photos...",
            total=max(1, len(photos)),
            current=0,
        )
        allowed_override = {"safe", "possible_nsfw", "nsfw"}
        to_score = []
        done = 0
        for idx, p in enumerate(photos):
            if self.cancelled:
                return
            cached = self._nsfw_cache.get(p["id"], {})
            override = cached.get("override")
            if (
                cached.get("model") == NSFW_MODEL_VERSION
                and cached.get("score") is not None
                and cached.get("label")
            ):
                score = cached.get("score")
                label = cached.get("label")
            else:
                to_score.append((idx, p))
                continue
            p["nsfw_score"] = score
            p["nsfw_base_label"] = label
            p["nsfw_override"] = override
            p["nsfw_label"] = override if override in allowed_override else label
            done += 1
            if done % 25 == 0:
                self._set_status(current=done)

        if not to_score:
            self._set_status(current=done)
            return

        workers = min(8, max(2, os.cpu_count() or 4))
        self._set_status(
            message=f"NSFW mode: scoring {len(to_score)} uncached photos...",
            current=done,
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._nsfw_for_photo, p): idx for idx, p in to_score}
            for future in as_completed(futures):
                if self.cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                idx = futures[future]
                p = photos[idx]
                try:
                    score, label, override = future.result()
                except Exception:
                    score, label, override = None, "unknown", p.get("nsfw_override")
                p["nsfw_score"] = score
                p["nsfw_base_label"] = label
                p["nsfw_override"] = override
                p["nsfw_label"] = override if override in allowed_override else label
                done += 1
                if done % 25 == 0:
                    self._set_status(current=done)
        self._set_status(current=done)

    def _bron_kerbosch(self, adjacency, r, p, x, cliques):
        if self.cancelled:
            return
        if not p and not x:
            if len(r) >= 2:
                cliques.append(set(r))
            return

        pivot = None
        if p or x:
            pivot = max(p | x, key=lambda v: len(adjacency[v] & p))

        candidates = list(p) if pivot is None else list(p - adjacency[pivot])
        for v in candidates:
            if self.cancelled:
                return
            self._bron_kerbosch(adjacency, r | {v}, p & adjacency[v], x & adjacency[v], cliques)
            p.discard(v)
            x.add(v)

    def _extract_strict_groups(self, photos, threshold, group_id_prefix):
        n = len(photos)
        if n < 2:
            return []

        adjacency = {i: set() for i in range(n)}
        edge_diff = {}
        remainder = 0

        for i in range(n):
            if self.cancelled:
                return []
            h1 = photos[i]["hash"]
            for j in range(i + 1, n):
                if self.cancelled:
                    return []
                diff = h1 - photos[j]["hash"]
                if diff < threshold:
                    adjacency[i].add(j)
                    adjacency[j].add(i)
                    edge_diff[(i, j)] = int(diff)
                remainder += 1
                if remainder >= 3000:
                    self._increment_progress(remainder)
                    remainder = 0

        if remainder:
            self._increment_progress(remainder)

        cliques = []
        self._bron_kerbosch(adjacency, set(), set(range(n)), set(), cliques)
        if self.cancelled:
            return []

        scored = []
        for clique in cliques:
            if len(clique) < 2:
                continue
            sorted_nodes = sorted(clique)
            diff_sum = 0
            pairs = 0
            for a, b in combinations(sorted_nodes, 2):
                key = (a, b) if a < b else (b, a)
                d = edge_diff.get(key)
                if d is None:
                    diff_sum = None
                    break
                diff_sum += d
                pairs += 1
            if diff_sum is None or pairs == 0:
                continue
            scored.append((sorted_nodes, diff_sum / pairs))

        scored.sort(key=lambda item: (-len(item[0]), item[1]))

        assigned = set()
        groups = []
        group_counter = 0
        for node_list, avg_diff in scored:
            if any(node in assigned for node in node_list):
                continue
            assigned.update(node_list)

            photos_out = []
            for node in node_list:
                p = photos[node]
                photos_out.append(
                    {
                        "id": p["id"],
                        "title": p["title"],
                        "url": p["url"],
                        "width": p["width"],
                        "height": p["height"],
                        "original_url": p.get("original_url") or p["url"],
                        "original_width": p.get("original_width") or 0,
                        "original_height": p.get("original_height") or 0,
                        "nsfw_score": p.get("nsfw_score"),
                        "nsfw_label": p.get("nsfw_label") or "unknown",
                        "nsfw_base_label": p.get("nsfw_base_label") or p.get("nsfw_label") or "unknown",
                        "nsfw_override": p.get("nsfw_override"),
                    }
                )

            photos_out.sort(key=lambda item: item["id"])
            groups.append(
                {
                    "group_id": f"{group_id_prefix}-{group_counter}",
                    "size": len(photos_out),
                    "avg_diff": round(float(avg_diff), 2),
                    "photos": photos_out,
                }
            )
            group_counter += 1

        return groups

    def _global_exact_groups(self, processed_photos, check_cancel=True):
        hash_groups = defaultdict(list)
        for p in processed_photos:
            hash_groups[p["hash_str"]].append(p)

        groups = []
        group_counter = 0
        for _, same_hash in hash_groups.items():
            if check_cancel and self.cancelled:
                return []
            if len(same_hash) < 2:
                continue

            photos_out = [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "url": p["url"],
                    "width": p["width"],
                    "height": p["height"],
                    "original_url": p.get("original_url") or p["url"],
                    "original_width": p.get("original_width") or 0,
                    "original_height": p.get("original_height") or 0,
                    "nsfw_score": p.get("nsfw_score"),
                    "nsfw_label": p.get("nsfw_label") or "unknown",
                    "nsfw_base_label": p.get("nsfw_base_label") or p.get("nsfw_label") or "unknown",
                    "nsfw_override": p.get("nsfw_override"),
                }
                for p in same_hash
            ]
            photos_out.sort(key=lambda item: item["id"])

            groups.append(
                {
                    "group_id": f"global-exact-{group_counter}",
                    "size": len(photos_out),
                    "avg_diff": 0.0,
                    "photos": photos_out,
                }
            )
            group_counter += 1

        groups.sort(key=lambda g: (-g["size"], g["group_id"]))
        return groups

    def _build_nsfw_groups(self, processed_photos, include_possible=True):
        allowed = {"nsfw", "possible_nsfw"} if include_possible else {"nsfw"}
        matched = [p for p in processed_photos if (p.get("nsfw_label") or "unknown") in allowed]
        matched.sort(
            key=lambda p: (
                0 if (p.get("nsfw_label") == "nsfw") else 1,
                -(p.get("nsfw_score") or 0),
                str(p.get("id") or ""),
            )
        )

        groups = []
        for idx, p in enumerate(matched):
            groups.append(
                {
                    "group_id": f"nsfw-{idx}",
                    "size": 1,
                    "avg_diff": 0.0,
                    "photos": [
                        {
                            "id": p["id"],
                            "title": p["title"],
                            "url": p["url"],
                            "width": p["width"],
                            "height": p["height"],
                            "original_url": p.get("original_url") or p["url"],
                            "original_width": p.get("original_width") or 0,
                            "original_height": p.get("original_height") or 0,
                            "nsfw_score": p.get("nsfw_score"),
                            "nsfw_label": p.get("nsfw_label") or "unknown",
                            "nsfw_base_label": p.get("nsfw_base_label") or p.get("nsfw_label") or "unknown",
                            "nsfw_override": p.get("nsfw_override"),
                        }
                    ],
                }
            )
        return groups

    def _finalize_cancelled_scan(self, mode, groups):
        if mode == "nsfw":
            self.save_nsfw_results(groups)
            self._set_status(message=f"Scan cancelled. Saved {len(groups)} partial NSFW matches.")
        else:
            self.save_results(groups)
            self._set_status(message=f"Scan cancelled. Saved {len(groups)} partial groups.")
        return groups

    def _load_photos(self, use_cache=False):
        photos = []
        cache_file = PHOTO_CACHE_FILE

        if use_cache and os.path.exists(cache_file):
            try:
                self._set_status(message="Using cached photo list...")
                with open(cache_file, "r") as f:
                    photos = json.load(f)
                if self._missing_photo_ids:
                    before = len(photos)
                    photos = [p for p in photos if str((p or {}).get("id", "")) not in self._missing_photo_ids]
                    skipped = before - len(photos)
                    if skipped > 0:
                        self._set_status(
                            message=f"Using cached photo list (skipped {skipped} deleted/missing photos)..."
                        )
            except Exception as e:
                print(f"Cache load error: {e}")
                photos = self.get_all_photos()
        else:
            photos = self.get_all_photos()
            if self._missing_photo_ids:
                current_ids = {str((p or {}).get("id", "")) for p in photos}
                stale = self._missing_photo_ids & current_ids
                if stale:
                    with self._missing_lock:
                        self._missing_photo_ids -= stale
                    self._save_missing_photo_ids()
            try:
                with open(cache_file, "w") as f:
                    json.dump(photos, f)
            except Exception as e:
                print(f"Cache save error: {e}")
        return photos

    def _prepare_processed_photos(self, photos):
        self._set_status(total=len(photos), current=0)
        self.cancelled = False
        self._stop_event.clear()

        self._set_status(message="Loading hash cache...")
        self._hash_cache = db.get_all_hashes()
        self._nsfw_cache = db.get_all_nsfw()

        self._set_status(message="Processing photos...")
        processed_photos = []
        uncached_photos = []
        for i, p in enumerate(photos):
            if self.cancelled:
                break
            photo_id = p["id"]
            if str(photo_id) in self._missing_photo_ids:
                self._increment_progress(1)
                continue
            cached = self._hash_cache.get(photo_id)
            nsfw_cached = self._nsfw_cache.get(photo_id, {})
            if cached and cached[0]:
                processed_photos.append(
                    self._build_photo_record(
                        photo_id,
                        imagehash.hex_to_hash(cached[0]),
                        cached[2],
                        cached[1],
                        cached[3],
                        cached[4],
                        p.get("datetaken", "0000-00-00"),
                        p.get("url_o"),
                        p.get("width_o"),
                        p.get("height_o"),
                        nsfw_cached.get("score"),
                        nsfw_cached.get("label") or "unknown",
                        nsfw_cached.get("override"),
                    )
                )
                self._increment_progress(1)
            else:
                uncached_photos.append(p)
            if i % 500 == 0:
                time.sleep(0)

        if uncached_photos and not self.cancelled:
            self._set_status(message=f"Downloading {len(uncached_photos)} new photos...")
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(self.process_single_photo, uncached_photos))
                processed_photos.extend(r for r in results if r is not None)

        return processed_photos

    def find_duplicates(self, threshold=5, global_search=False, use_cache=False, nsfw_mode="off"):
        photos = self._load_photos(use_cache=use_cache)
        processed_photos = self._prepare_processed_photos(photos)
        groups = []

        if self.cancelled:
            if global_search:
                groups = self._global_exact_groups(processed_photos, check_cancel=False)
            return self._finalize_cancelled_scan("duplicates", groups)

        self._apply_nsfw(processed_photos, nsfw_mode)
        if self.cancelled:
            if global_search:
                groups = self._global_exact_groups(processed_photos, check_cancel=False)
            return self._finalize_cancelled_scan("duplicates", groups)

        if global_search:
            self._set_status(
                message="Global exact scan: grouping identical photos regardless of date...",
                total=max(1, len(processed_photos)),
                current=0,
            )
            done = 0
            for _ in processed_photos:
                if self.cancelled:
                    break
                done += 1
                if done % 2500 == 0:
                    self._set_status(current=done)
            self._set_status(current=done)
            groups = self._global_exact_groups(processed_photos, check_cancel=not self.cancelled)
        else:
            buckets = defaultdict(list)
            for p in processed_photos:
                buckets[p["date_taken"][:10]].append(p)

            comparisons_total = 0
            for bucket_photos in buckets.values():
                n = len(bucket_photos)
                if n >= 2:
                    comparisons_total += n * (n - 1) // 2

            self._set_status(
                message="Fast scan: building strict similarity groups by date...",
                total=max(1, comparisons_total),
                current=0,
            )

            bucket_index = 0
            for date_key, bucket_photos in buckets.items():
                if self.cancelled:
                    break
                if len(bucket_photos) < 2:
                    continue
                self._set_status(message=f"Fast scan: date {date_key} ({bucket_index + 1}/{len(buckets)})")
                bucket_groups = self._extract_strict_groups(
                    bucket_photos,
                    threshold,
                    group_id_prefix=f"date-{date_key}",
                )
                groups.extend(bucket_groups)
                bucket_index += 1

            groups.sort(key=lambda g: (-g["size"], g["avg_diff"], g["group_id"]))

        if self.cancelled:
            return self._finalize_cancelled_scan("duplicates", groups)

        self._set_status(message="Scan complete.")
        self.save_results(groups)
        return groups

    def find_nsfw(self, use_cache=False, include_possible=True):
        photos = self._load_photos(use_cache=use_cache)
        processed_photos = self._prepare_processed_photos(photos)

        if self.cancelled:
            groups = self._build_nsfw_groups(processed_photos, include_possible=include_possible)
            return self._finalize_cancelled_scan("nsfw", groups)

        self._apply_nsfw(processed_photos, nsfw_mode="nsfw")
        if self.cancelled:
            groups = self._build_nsfw_groups(processed_photos, include_possible=include_possible)
            return self._finalize_cancelled_scan("nsfw", groups)

        groups = self._build_nsfw_groups(processed_photos, include_possible=include_possible)

        self._set_status(message="Scan complete.")
        self.save_nsfw_results(groups)
        return groups

    def save_results(self, groups):
        with open("duplicates.json", "w") as f:
            json.dump(groups, f, indent=2)

    def save_nsfw_results(self, groups):
        with open("nsfw_results.json", "w") as f:
            json.dump(groups, f, indent=2)

    def get_original_info(self, photo_id):
        if photo_id in self._original_info_cache:
            return self._original_info_cache[photo_id]

        info = {
            "photo_id": photo_id,
            "original_url": None,
            "original_width": 0,
            "original_height": 0,
            "original_size_bytes": None,
        }

        try:
            resp = self.flickr.photos.getSizes(photo_id=photo_id)
            sizes = (resp or {}).get("sizes", {}).get("size", [])
            if not sizes:
                self._original_info_cache[photo_id] = info
                return info

            selected = None
            for size in sizes:
                if size.get("label") == "Original":
                    selected = size
                    break
            if selected is None:
                selected = sizes[-1]

            source = selected.get("source")
            info["original_url"] = source
            info["original_width"] = int(selected.get("width", 0) or 0)
            info["original_height"] = int(selected.get("height", 0) or 0)

            if source:
                size_bytes = None
                try:
                    head = self.session.head(source, timeout=10, allow_redirects=True)
                    if head.ok:
                        content_length = head.headers.get("Content-Length")
                        if content_length and content_length.isdigit():
                            size_bytes = int(content_length)
                except Exception:
                    size_bytes = None

                if size_bytes is None:
                    try:
                        get_resp = self.session.get(source, timeout=10, stream=True)
                        if get_resp.ok:
                            content_length = get_resp.headers.get("Content-Length")
                            if content_length and content_length.isdigit():
                                size_bytes = int(content_length)
                        get_resp.close()
                    except Exception:
                        size_bytes = None

                info["original_size_bytes"] = size_bytes
        except Exception:
            pass

        self._original_info_cache[photo_id] = info
        return info


if __name__ == "__main__":
    detector = FlickrDetector()
    detector.find_duplicates()
