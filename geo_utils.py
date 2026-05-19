# geo_utils.py
from geopy.distance import geodesic

def distance_meter(lat1, lon1, lat2, lon2):
    """두 좌표 사이 거리(m)를 반환. 하나라도 None이면 무한대 반환"""
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    return geodesic((lat1, lon1), (lat2, lon2)).meters
