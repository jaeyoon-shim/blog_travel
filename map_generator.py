import folium
from pathlib import Path

def generate_map(travel_name: str, organized_data: list, output_dir: Path):
    coords = []

    for day in organized_data:
        for p in day["photos"]:
            if p.get("lat") and p.get("lon"):
                coords.append((p["lat"], p["lon"]))

    if len(coords) < 2:
        return None

    m = folium.Map(location=coords[0], zoom_start=12)

    for i in range(len(coords) - 1):
        folium.PolyLine(
            locations=[coords[i], coords[i + 1]],
            color="red",
            weight=4,
            opacity=0.9
        ).add_to(m)

        folium.Marker(
            coords[i],
            icon=folium.Icon(icon="arrow-right", color="red")
        ).add_to(m)

    folium.Marker(
        coords[-1],
        icon=folium.Icon(color="red")
    ).add_to(m)

    map_path = output_dir / f"{travel_name}_route.html"
    m.save(map_path)

    return map_path
