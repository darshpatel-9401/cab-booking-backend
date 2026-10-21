from models import PromoCode, PromoRedemption


def constraint_names(model):
    return {c.name for c in model.__table__.constraints if c.name}


def test_promo_code_rules_are_declared():
    assert {
        "ck_promo_codes_code_format",
        "ck_promo_codes_type_and_value",
        "ck_promo_codes_max_discount_positive",
        "ck_promo_codes_max_total_uses_positive",
        "ck_promo_codes_per_user_positive",
    } <= constraint_names(PromoCode)


def test_redemption_rules_are_declared():
    assert {
        "ck_promo_redemptions_amount_positive",
        "ck_promo_redemptions_status",
        "uq_promo_redemptions_ride",
    } <= constraint_names(PromoRedemption)