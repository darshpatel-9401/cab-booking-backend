"""Simulates riders and drivers against the real API, using throwaway test accounts.

Run from the backend folder, with the backend already running:
    python scripts/simulate.py --riders 4 --drivers 3
"""

import argparse
from email import header
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse


import httpx

PICKUP = (51.5080, -0.1281)
DROP = (51.5055, -0.0754)


def read_env_file(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Account:
    def __init__(self, kind, index, run_id, domain, config):
        self.kind = kind
        self.email = f"sim.{kind}.{index}.{run_id}@{domain}"
        self.config = config
        self.token = None
        self.http = httpx.Client(base_url=config["api"], timeout=30)

    def sign_up(self, password):
        headers = {"apikey": self.config["key"]}
        base = self.config["supabase"]
        with httpx.Client(timeout=30) as auth:
            created = auth.post(
                f"{base}/auth/v1/signup",
                headers=headers,
                json={"email": self.email, "password": password},
            )
            if created.status_code >= 400:
                sys.exit(f"Sign up failed for {self.email}: {created.text[:200]}")
            login = auth.post(
                f"{base}/auth/v1/token",
                params={"grant_type": "password"},
                headers=headers,
                json={"email": self.email, "password": password},
            )
            if login.status_code >= 400:
                sys.exit(
                    f"Sign in failed for {self.email}: {login.text[:200]}. "
                    "Is email confirmation switched off in Supabase?"
                )
            self.token = login.json()["access_token"]


    def call(self, method, path, **kwargs):
        return self.http.request(
            method,
            path,
            headers={"Authorization": f"Bearer {self.token}"},
            **kwargs,
        )


def expect(response, codes, what):
    if response.status_code not in codes:
        sys.exit(f"FAILED: {what} -> {response.status_code} {response.text[:200]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--riders", type=int, default=4)
    parser.add_argument("--drivers", type=int, default=3)
    parser.add_argument("--domain", default="example.com")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    if not (1 <= args.riders <= 10 and 1 <= args.drivers <= 10):
        sys.exit("Use between 1 and 10 riders and between 1 and 10 drivers.")

    env_path = Path(__file__).resolve().parents[2] / "frontend" / ".env.local"
    if not env_path.exists():
        sys.exit(f"Could not find {env_path}")
    env = read_env_file(env_path)
    config = {
        "supabase": env.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/"),
        "key": env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", ""),
        "api": env.get("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/"),
    }
    if not config["supabase"] or not config["key"]:
        sys.exit("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are needed.")

    host = urlparse(config["api"]).hostname
    if host not in ("localhost", "127.0.0.1") and not args.allow_remote:
        sys.exit(
            f"The API is at {config['api']}, which is not local. "
            "This script creates test data, so add --allow-remote if you really mean it."
        )

    run_id = secrets.token_hex(3)
    password = "Sim-" + secrets.token_urlsafe(9)
    print(f"Run {run_id}: {args.riders} riders, {args.drivers} drivers\n")

    drivers = [Account("driver", i, run_id, args.domain, config) for i in range(args.drivers)]
    riders = [Account("rider", i, run_id, args.domain, config) for i in range(args.riders)]

    print("1. Creating accounts...")
    for account in drivers + riders:
        account.sign_up(password)
        expect(account.call("POST", "/api/auth/session"), (200,), f"profile for {account.email}")

    print("2. Registering drivers...")
    for index, driver in enumerate(drivers):
        expect(
            driver.call("POST", "/api/drivers/register", json={"vehicle_info": f"Sim car {index}"}),
            (201,),
            f"register {driver.email}",
        )

    print("\n3. Drivers must be verified before they can go online. Run this in the Supabase SQL Editor:\n")
    print(
        "   update drivers set verified = true where user_id in "
        f"(select id from users where email like 'sim.driver.%.{run_id}@{args.domain}');\n"
    )
    input("   Press Enter when it has run... ")

    print("4. Drivers share a location and go online...")
    for index, driver in enumerate(drivers):
        expect(
            driver.call(
                "PUT",
                "/api/drivers/location",
                json={"lat": PICKUP[0] - 0.0004 * (index + 1), "lng": PICKUP[1]},
            ),
            (200,),
            f"location for {driver.email}",
        )
        expect(
            driver.call("PUT", "/api/drivers/status", json={"status": "active"}),
            (200,),
            f"go online for {driver.email}",
        )

    print("5. Riders request rides...")
    rides = []
    for rider in riders:
        response = rider.call(
            "POST",
            "/api/rides/request",
            json={
                "pickup_lat": PICKUP[0],
                "pickup_lng": PICKUP[1],
                "drop_lat": DROP[0],
                "drop_lng": DROP[1],
            },
        )
        expect(response, (201,), f"ride request for {rider.email}")
        rides.append((rider, response.json()["ride_id"]))
        time.sleep(0.5)

    print("6. Every rider asks for a driver at the same moment...")

    def match(pair):
        rider, ride_id = pair
        response = rider.call("POST", f"/api/rides/{ride_id}/match")
        return rider, ride_id, response.status_code

    with ThreadPoolExecutor(max_workers=len(rides)) as pool:
        results = list(pool.map(match, rides))

    matched = [r for r in results if r[2] == 200]
    no_driver = [r for r in results if r[2] == 503]
    others = [r for r in results if r[2] not in (200, 503)]
    expected = min(args.riders, args.drivers)
    print(f"   matched: {len(matched)}, no driver available: {len(no_driver)}, other: {len(others)}")

    if others:
        sys.exit(f"FAILED: unexpected answers {[r[2] for r in others]}")
    if len(matched) != expected:
        sys.exit(f"FAILED: expected {expected} matches, got {len(matched)}")

    print("7. Checking that no driver was given two rides...")
    assigned = {}
    for driver in drivers:
        response = driver.call("GET", "/api/drivers/current-ride")
        expect(response, (200,), f"current ride for {driver.email}")
        ride = response.json()["ride"]
        if ride:
            assigned[driver.email] = ride["ride_id"]

    matched_ids = {r[1] for r in matched}
    if len(assigned) != len(matched) or set(assigned.values()) != matched_ids:
        sys.exit(
            "FAILED: matches and driver assignments disagree "
            f"({len(matched)} matches, {len(assigned)} busy drivers). A driver may have been double-booked."
        )

    print("8. Drivers start and complete their rides...")
    for driver in drivers:
        ride_id = assigned.get(driver.email)
        if ride_id:
            expect(driver.call("POST", f"/api/rides/{ride_id}/start"), (200,), "start ride")
            expect(driver.call("POST", f"/api/rides/{ride_id}/complete"), (200,), "complete ride")

    print("9. Riders without a driver cancel their requests...")
    for rider, ride_id, _code in no_driver:
        expect(rider.call("POST", f"/api/rides/{ride_id}/cancel"), (200,), "cancel ride")

    print("\nPASSED. No driver was double-booked.\n")
    print("Clean up the test data in the Supabase SQL Editor, one statement at a time:\n")
    pattern = f"sim.%.{run_id}@{args.domain}"
    ids = f"(select id from users where email like '{pattern}')"
    for statement in [
        f"delete from reviews where rater_id in {ids} or rated_id in {ids};",
        f"delete from payments where ride_id in (select id from rides where rider_id in {ids});",
        f"delete from promo_redemptions where user_id in {ids};",
        f"delete from wallet_transactions where user_id in {ids};",
        f"delete from wallets where user_id in {ids};",
        f"delete from rides where rider_id in {ids} or driver_id in {ids};",
        f"delete from drivers where user_id in {ids};",
        f"delete from users where email like '{pattern}';",
    ]:
        print("  " + statement)
    print("\nThen delete the accounts in Supabase: Authentication, Users, search for 'sim.'.")


if __name__ == "__main__":
    main()