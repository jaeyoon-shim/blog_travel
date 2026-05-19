import os
from datetime import datetime
from PIL import Image
from collections import defaultdict

from exif_utils import get_exif_data
from location_resolver import resolve_location
from config import MYBOX_DIR


def organize_photos(travel_folder: str):
    """
    return:
    [
        {
            "date": "2024-11-02",
            "location": "Osaka",
            "photos": [
                {
                    "path": "...jpg",
                    "time": "11:18",
                    "lat": 34.67,
                    "lon": 135.50,
                    "place": "난바역"
                },
                ...
            ]
        },
        ...
    ]
    """

    travel_path = MYBOX_DIR / travel_folder
    if not travel_path.exists():
        raise FileNotFoundError(f"여행 폴더 없음: {travel_path}")

    buckets = defaultdict(list)

    for file in os.listdir(travel_path):
        if not file.lower().endswith(".jpg"):
            continue

        img_path = travel_path / file
        img = Image.open(img_path)

        date_time, gps = get_exif_data(img)
        if not date_time or not gps:
            continue

        lat, lon = gps
        place = resolve_location(lat, lon)

        date_str = date_time.strftime("%Y-%m-%d")
        time_str = date_time.strftime("%H:%M")

        buckets[(date_str, place)].append({
            "path": str(img_path),
            "time": time_str,
            "lat": lat,
            "lon": lon,
            "place": place
        })

    organized = []

    for (date, place), photos in sorted(buckets.items()):
        photos = sorted(photos, key=lambda x: x["time"])

        organized.append({
            "date": date,
            "location": place,
            "photos": photos
        })

    return organized
