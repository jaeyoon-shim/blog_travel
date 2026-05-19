import os

def find_trip_folders(root):
    trips = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            trips.append(path)
    return trips
