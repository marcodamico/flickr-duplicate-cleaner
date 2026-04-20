# detector.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

import flickrapi
import requests
from io import BytesIO
from PIL import Image
import imagehash
from tqdm import tqdm
from collections import defaultdict
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import db
import itertools
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Load environment variables from .env
load_dotenv()

API_KEY = os.getenv("FLICKR_API_KEY")
API_SECRET = os.getenv("FLICKR_API_SECRET")

class FlickrDetector:
    def __init__(self):
        if not API_KEY or not API_SECRET:
            raise ValueError("FLICKR_API_KEY and FLICKR_API_SECRET must be set in .env")
        
        self.flickr = flickrapi.FlickrAPI(API_KEY, API_SECRET, format='parsed-json')
        self.flickr.authenticate_via_browser(perms='delete')
        self.user_id = self.flickr.test.login()['user']['id']
        self.status = {"total": 0, "current": 0, "message": "Idle"}
        self.cancelled = False
        self._lock = threading.Lock()
        # Global rate limiter: minimum 0.25s between requests across all workers
        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0

        # Configure session with retries only for server errors (not 429, which blocks threads too long)
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _rate_limited_get(self, url, **kwargs):
        """Enforce a minimum gap between requests to avoid triggering CDN rate limits."""
        with self._rate_lock:
            now = time.time()
            wait = max(0.0, self._last_request_time + 0.25 - now)
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.time()
        return self.session.get(url, **kwargs)

    def cancel(self):
        self.cancelled = True
        self.status["message"] = "Scan cancelled."

    def get_all_photos(self):
        # ... (unchanged)
        photos = []
        page = 1
        while True:
            self.status["message"] = f"Fetching photo list (page {page})..."
            resp = self.flickr.people.getPhotos(
                user_id=self.user_id,
                extras='date_taken,url_k,width_k,height_k,url_b,width_b,height_b,url_o,width_o,height_o,url_m,width_m,height_m',
                per_page=500,
                page=page
            )
            photos.extend(resp['photos']['photo'])
            if page >= resp['photos']['pages']:
                break
            page += 1
        return photos

    def process_single_photo(self, p):
        if self.cancelled:
            return None
        # ... (rest of the file remains functionally the same, but I'll provide the start again)
        photo_id = p['id']
        cached = db.get_hash(photo_id)
        if cached and cached[0]:  # cached[0] is the hash string; width/height may be 0 (falsy) but still valid
            with self._lock:
                self.status["current"] += 1
            return {
                'id': photo_id,
                'hash': imagehash.hex_to_hash(cached[0]),
                'title': cached[2],
                'url': cached[1],
                'width': cached[3] or 0,
                'height': cached[4] or 0,
                'date_taken': p.get('datetaken', '0000-00-00')
            }

        best_url = None
        width = 0
        height = 0
        for suffix in ['o', 'k', 'b', 'm']:
            url = p.get(f'url_{suffix}')
            if url:
                best_url = url
                width = int(p.get(f'width_{suffix}', 0))
                height = int(p.get(f'height_{suffix}', 0))
                break

        if not best_url:
            with self._lock:
                self.status["current"] += 1
            return None

        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

            # Use rate-limited get; retry 429 with short exponential backoff
            resp = None
            for attempt in range(5):
                resp = self._rate_limited_get(best_url, timeout=15, headers=headers)
                if resp.status_code == 429:
                    wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                    print(f"Rate limited on {photo_id}, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                else:
                    break
            
            if resp.status_code != 200:
                print(f"Error processing {photo_id}: Status {resp.status_code} for URL {best_url}")
                with self._lock:
                    self.status["current"] += 1
                return None

            content_type = resp.headers.get('Content-Type', '')
            if 'image' not in content_type:
                print(f"Error processing {photo_id}: Invalid content type '{content_type}'")
                with self._lock:
                    self.status["current"] += 1
                return None

            img = Image.open(BytesIO(resp.content))
            h = imagehash.phash(img)
            db.save_hash(photo_id, str(h), best_url, p['title'], p.get('datetaken', ''), width, height)
            with self._lock:
                self.status["current"] += 1
            return {
                'id': photo_id,
                'hash': h, 'title': p['title'], 'url': best_url, 'width': width, 'height': height,
                'date_taken': p.get('datetaken', '0000-00-00')
            }
        except Exception as e:
            msg = f"Error processing {photo_id}: {str(e)}"
            if resp is not None:
                msg += f" (Status: {resp.status_code}, Type: {resp.headers.get('Content-Type')})"
            print(msg)
            with self._lock:
                self.status["current"] += 1
            return None

    def find_duplicates(self, threshold=5, global_search=False, use_cache=False):
        photos = []
        cache_file = "photo_cache.json"

        if use_cache and os.path.exists(cache_file):
            try:
                self.status["message"] = "Using cached photo list..."
                with open(cache_file, "r") as f:
                    photos = json.load(f)
            except Exception as e:
                print(f"Cache load error: {e}")
                photos = self.get_all_photos()
        else:
            photos = self.get_all_photos()
            try:
                with open(cache_file, "w") as f:
                    json.dump(photos, f)
            except Exception as e:
                print(f"Cache save error: {e}")

        self.status["total"] = len(photos)
        self.status["current"] = 0
        self.status["message"] = "Hashing images..."
        self.cancelled = False

        processed_photos = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(self.process_single_photo, photos))
            processed_photos = [r for r in results if r is not None]

        duplicates = []
        if global_search:
            self.status["message"] = "Deep Scan: Comparing all photos..."
            total_pairs = len(processed_photos) * (len(processed_photos) - 1) // 2
            self.status["total"] = total_pairs
            self.status["current"] = 0
            count = 0
            for i, p1 in enumerate(processed_photos):
                for j in range(i + 1, len(processed_photos)):
                    if self.cancelled: break
                    p2 = processed_photos[j]
                    diff = p1['hash'] - p2['hash']
                    if diff < threshold:
                        duplicates.append(self.format_pair(p1, p2, diff))
                    count += 1
                    if count % 5000 == 0: self.status["current"] = count
                if self.cancelled: break
                self.status["current"] = count
        else:
            self.status["message"] = "Fast Scan: Comparing by date..."
            groups = defaultdict(list)
            for p in processed_photos:
                date_key = p['date_taken'][:10]
                groups[date_key].append(p)
            for date_key, group in groups.items():
                if len(group) < 2: continue
                for i in range(len(group)):
                    if self.cancelled: break
                    for j in range(i + 1, len(group)):
                        diff = group[i]['hash'] - group[j]['hash']
                        if diff < threshold:
                            duplicates.append(self.format_pair(group[i], group[j], diff))
                if self.cancelled: break

        if self.cancelled:
            self.status["message"] = "Scan cancelled."
            return []

        self.status["message"] = "Scan complete."
        self.save_results(duplicates)
        return duplicates

    def format_pair(self, p1, p2, diff):
        return {
            "p1": {"id": p1['id'], "title": p1['title'], "url": p1['url'], "width": p1['width'], "height": p1['height']},
            "p2": {"id": p2['id'], "title": p2['title'], "url": p2['url'], "width": p2['width'], "height": p2['height']},
            "diff": int(diff)
        }

    def save_results(self, duplicates):
        with open("duplicates.json", "w") as f:
            json.dump(duplicates, f, indent=2)

if __name__ == "__main__":
    detector = FlickrDetector()
    detector.find_duplicates()
