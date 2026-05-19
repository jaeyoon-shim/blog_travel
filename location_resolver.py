from geopy.geocoders import Nominatim

# 한국어와 현지어를 모두 가져오기 위해 2개의 객체 생성 가능하나, 
# Nominatim의 한계가 있어 최대한 상세 주소를 파싱합니다.
geolocator = Nominatim(user_agent="travel_blog_auto_v2")

def get_location_name(lat, lon):
    if lat is None or lon is None:
        return "장소 미정", "지역 미정"
    try:
        # 주소 정보를 한국어로 요청
        location_ko = geolocator.reverse((lat, lon), language='ko', timeout=10)
        # 주소 정보를 현지어(일본어 등)로 요청
        location_orig = geolocator.reverse((lat, lon), language='ja', timeout=10)
        
        addr_ko = location_ko.raw.get('address', {})
        addr_orig = location_orig.raw.get('address', {})

        # 특정 랜드마크 이름 추출 시도
        place_ko = addr_ko.get('tourism') or addr_ko.get('amenity') or addr_ko.get('historic') or addr_ko.get('road')
        place_orig = addr_orig.get('tourism') or addr_orig.get('amenity') or addr_orig.get('historic') or addr_orig.get('road')

        if place_ko and place_orig and place_ko != place_orig:
            full_place = f"{place_ko} ({place_orig})"
        else:
            full_place = place_ko or "장소 정보 없음"

        region = addr_ko.get('city') or addr_ko.get('province') or addr_ko.get('state')
        return full_place, region
    except Exception:
        return "위치 정보 오류", "위치 정보 오류"