import httpx

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"


class RouteError(Exception):
    """Raised when the routing service fails or finds no route."""


def get_route(origin_lat, origin_lng, dest_lat, dest_lng):
    for lat in (origin_lat, dest_lat):
        if not -90 <= lat <= 90:
            raise ValueError("latitude must be between -90 and 90")
    for lng in (origin_lng, dest_lng):
        if not -180 <= lng <= 180:
            raise ValueError("longitude must be between -180 and 180")

    # OSRM expects longitude first, then latitude
    coords = f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"

    try:
        response = httpx.get(
            f"{OSRM_URL}/{coords}",
            params={"overview": "false"},
            headers={"User-Agent": "cab-booking-learning-project"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RouteError(f"Routing service failed: {e}") from e

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError("No route found between these points")

    route = data["routes"][0]
    return {
        "distance_meters": round(route["distance"]),
        "duration_secs": round(route["duration"]),
    }