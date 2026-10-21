import os

import stripe
from dotenv import load_dotenv

load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if not STRIPE_SECRET_KEY.startswith("sk_test_"):
    raise RuntimeError(
        "STRIPE_SECRET_KEY in backend/.env must be a TEST key starting with sk_test_"
    )

CURRENCY = os.getenv("STRIPE_CURRENCY", "inr").lower()

stripe.api_key = STRIPE_SECRET_KEY