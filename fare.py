# All money values are whole numbers in the smallest currency unit
BASE_FARE = 5000
PER_KM = 1200
PER_MINUTE = 150
MINIMUM_FARE = 8000


def calculate_fare(distance_meters: int, duration_secs: int) -> int:
    if distance_meters < 0 or duration_secs < 0:
        raise ValueError("distance and duration must not be negative")

    km = distance_meters / 1000
    minutes = duration_secs / 60

    fare = BASE_FARE + km * PER_KM + minutes * PER_MINUTE
    return max(round(fare), MINIMUM_FARE)