from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def get_exif_data(image_path):
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if not info:
            return None
        
        exif_data = {}
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_data = {}
                for t in value:
                    sub_decoded = GPSTAGS.get(t, t)
                    gps_data[sub_decoded] = value[t]
                exif_data[decoded] = gps_data
            else:
                exif_data[decoded] = value
        return exif_data
    except Exception:
        return None

def get_lat_lon(exif_data):
    if not exif_data or "GPSInfo" not in exif_data:
        return None, None

    gps_info = exif_data["GPSInfo"]
    
    def convert_to_degrees(value):
        d = float(value[0])
        m = float(value[1])
        s = float(value[2])
        return d + (m / 60.0) + (s / 3600.0)

    try:
        lat = convert_to_degrees(gps_info["GPSLatitude"])
        if gps_info["GPSLatitudeRef"] != "N": lat = -lat
        lon = convert_to_degrees(gps_info["GPSLongitude"])
        if gps_info["GPSLongitudeRef"] != "E": lon = -lon
        return lat, lon
    except KeyError:
        return None, None