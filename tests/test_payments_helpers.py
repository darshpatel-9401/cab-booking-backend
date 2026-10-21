from routers.payments import IntentRequest, clean_promo_code


def test_no_body_means_no_promo():
    assert clean_promo_code(None) is None


def test_missing_code_means_no_promo():
    assert clean_promo_code(IntentRequest()) is None


def test_blank_code_means_no_promo():
    assert clean_promo_code(IntentRequest(promo_code="   ")) is None


def test_real_code_is_passed_through():
    assert clean_promo_code(IntentRequest(promo_code="welcome10")) == "welcome10"