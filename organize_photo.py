import os
import json
from tqdm import tqdm
from exif_utils import get_exif_data, get_lat_lon
from location_resolver import get_location_name

def process_files(folder_path):
    items = []
    files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4'))]
    
    print(f"총 {len(files)}개의 파일을 분석합니다...")

    for filename in tqdm(sorted(files), desc="사진 분석 중", unit="file"):
        path = os.path.join(folder_path, filename)
        exif = get_exif_data(path)
        date = exif.get("DateTimeOriginal", "날짜 정보 없음") if exif else "날짜 정보 없음"
        lat, lon = get_lat_lon(exif)
        place, region = get_location_name(lat, lon)

        items.append({
            "file": path,
            "filename": filename,
            "date": date,
            "lat": lat,
            "lon": lon,
            "region": region,
            "place": place
        })
    
    # 결과를 중간 파일로 저장
    with open("metadata.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=4)
        
    return items