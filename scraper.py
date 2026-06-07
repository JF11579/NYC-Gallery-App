#!/usr/bin/env python3
import hashlib, json, time
from pathlib import Path
import requests

GALLERIES_PATH = Path("data/galleries.json")
HASHES_PATH = Path("data/hashes.json")
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 15
SLEEP = 0.5

def fetch_hash(url):
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return __import__('hashlib').md5(r.content).hexdigest()
    except Exception as e:
        print(f"  WARN: {url}: {e}")
        return None

def main():
    geojson = json.loads(Path("data/galleries.json").read_text())
    features = geojson["features"]
    print(f"Loaded {len(features)} galleries")
    prev_hashes = json.loads(HASHES_PATH.read_text()) if HASHES_PATH.exists() else {}
    new_hashes = {}
    updated_count = 0
    for i, feature in enumerate(features, 1):
        props = feature["properties"]
        name = props.get("name", "?")
        url = props.get("url", "")
        h = fetch_hash(url)
        time.sleep(SLEEP)
        if h is None:
            props["updated"] = False
            new_hashes[url] = prev_hashes.get(url, "")
            print(f"  [{i:3d}/{len(features)}] ERROR  {name}")
            continue
        prev = prev_hashes.get(url)
        changed = (prev is not None) and (h != prev)
        props["updated"] = changed
        new_hashes[url] = h
        if changed:
            updated_count += 1
        print(f"  [{i:3d}/{len(features)}] {'UPDATED' if changed else 'same':7s} {name}")
    Path("data/galleries.json").write_text(json.dumps(geojson, indent=2))
    HASHES_PATH.write_text(json.dumps(new_hashes, indent=2))
    print(f"Done. {updated_count} updated.")

if __name__ == "__main__":
    main()
