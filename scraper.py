#!/usr/bin/env python3
import hashlib, json, time
from pathlib import Path
import requests

GALLERIES_PATH = Path("data/galleries.json")
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 15
SLEEP = 0.5

def fetch_hash(url):
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return hashlib.md5(r.content).hexdigest()
    except Exception as e:
        print(f"  WARN: {url}: {e}")
        return None

def main():
    geojson = json.loads(GALLERIES_PATH.read_text())
    features = geojson["features"]
    print(f"Loaded {len(features)} galleries")
    # Hashes live inside galleries.json so the workflow only needs to commit one file
    prev_hashes = geojson.get("_hashes", {})
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
    geojson["_hashes"] = new_hashes
    GALLERIES_PATH.write_text(json.dumps(geojson, indent=2))
    print(f"Done. {updated_count} updated.")

if __name__ == "__main__":
    main()
