import json
import os

def main():
    # Placeholder data for testing
    data = [
        {
            "name": "303 Gallery",
            "address": "555 W 21st St, New York, NY 10011",
            "coordinates": [-74.0051, 40.7466],
            "url": "https://www.303gallery.com/"
        }
    ]
    
    os.makedirs('data', exist_ok=True)
    with open('data/galleries.json', 'w') as f:
        json.dump(data, f, indent=4)
    print("Successfully created galleries.json")

if __name__ == "__main__":
    main()
