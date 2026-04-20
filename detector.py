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
from concurrent.futures import ThreadPoolExecutor
import db
import itertools
from dotenv import load_dotenv

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
        if cached and cached[3] and cached[4]:
            self.status["current"] += 1
            return {
                'id': photo_id,
                'hash': imagehash.hex_to_hash(cached[0]),
                'title': cached[2],
                'url': cached[1],
                'width': cached[3],
                'height': cached[4],
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
            self.status["current"] += 1
            return None

        try:
            resp = requests.get(best_url, timeout=10)
            img = Image.open(BytesIO(resp.content))
            h = imagehash.phash(img)
            db.save_hash(photo_id, str(h), best_url, p['title'], p.get('datetaken', ''), width, height)
            self.status["current"] += 1
            return {
                'id': photo_id,
                'hash': h, 'title': p['title'], 'url': best_url, 'width': width, 'height': height,
                'date_taken': p.get('datetaken', '0000-00-00')
            }
        except Exception as e:
            print(f"Error processing {photo_id}: {e}")
            self.status["current"] += 1
            return None

    def find_duplicates(self, threshold=5, global_search=False):
        photos = self.get_all_photos()
        self.status["total"] = len(photos)
        self.status["current"] = 0
        self.status["message"] = "Hashing images..."
        self.cancelled = False

        processed_photos = []
        with ThreadPoolExecutor(max_workers=10) as executor:
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
