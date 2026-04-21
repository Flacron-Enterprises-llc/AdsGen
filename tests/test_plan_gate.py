"""
Unit tests for the plan-gate fallback chain added in commits b10431c and 9bd7010.

Verifies the real-world bug: a user who paid in Stripe but whose Firestore row
is missing (dropped webhook, write failure, etc.) should still land on /dashboard
after login, not in the /choose-plan loop.

All external services (Stripe + Firestore) are mocked. No network calls.
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Stub price IDs so plan resolution by price.id works in the tests.
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy_for_tests")
os.environ.setdefault("STRIPE_PRICE_STARTER", "price_starter_test")
os.environ.setdefault("STRIPE_PRICE_PRO", "price_pro_test")


def _fake_stripe_module(customers=None, subs_by_customer=None):
    """Build an object that looks like the `stripe` module for our lookups."""
    stripe = types.SimpleNamespace()
    stripe.api_key = None

    class _InvalidRequestError(Exception):
        pass

    stripe.error = types.SimpleNamespace(InvalidRequestError=_InvalidRequestError)

    class _List:
        def __init__(self, data):
            self.data = data

    class _Customer:
        @staticmethod
        def list(email=None, limit=10):
            data = [c for c in (customers or []) if c.email == email]
            return _List(data)

    class _Subscription:
        @staticmethod
        def list(customer=None, status=None, limit=10):
            return _List((subs_by_customer or {}).get(customer, []))

    stripe.Customer = _Customer
    stripe.Subscription = _Subscription
    return stripe


def _make_customer(cid, email):
    return types.SimpleNamespace(id=cid, email=email)


def _make_sub(sub_id, status, plan_meta=None, price_id=None):
    sub = types.SimpleNamespace()
    sub.id = sub_id
    sub.status = status
    sub.metadata = {"plan": plan_meta} if plan_meta else {}
    items = []
    if price_id:
        items.append(types.SimpleNamespace(price=types.SimpleNamespace(id=price_id)))
    sub.items = types.SimpleNamespace(data=items)
    return sub


def _import_app():
    """Import web_app.app once; subsequent calls return the cached module."""
    if "web_app.app" in sys.modules:
        return sys.modules["web_app.app"]
    import web_app.app as app_mod  # noqa: WPS433
    return app_mod


def run_test_no_firestore_but_active_stripe_sub_with_metadata():
    """Stripe has an active sub for the email; plan comes from subscription.metadata."""
    app_mod = _import_app()

    cust = _make_customer("cus_abc", "mishalahmed@gmail.com")
    sub = _make_sub("sub_abc", "active", plan_meta="pro")
    stripe_stub = _fake_stripe_module(
        customers=[cust],
        subs_by_customer={"cus_abc": [sub]},
    )

    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "has_active_plan", return_value=False), \
         patch.object(app_mod, "_raw_active_plan", return_value=None), \
         patch.object(app_mod, "set_plan", return_value=True) as mock_set_plan:
        with app_mod.app.test_request_context("/"):
            result = app_mod.user_has_active_plan("mishalahmed@gmail.com")
    assert result is True, "user with active Stripe sub should be treated as paid"
    mock_set_plan.assert_called_once()
    args, kwargs = mock_set_plan.call_args
    assert args[0] == "mishalahmed@gmail.com"
    assert args[1] == "pro"
    assert kwargs.get("stripe_customer_id") == "cus_abc"
    assert kwargs.get("stripe_subscription_id") == "sub_abc"
    print("PASS  Stripe-metadata fallback resolves plan and writes to Firestore")


def run_test_plan_resolved_from_price_id_when_metadata_missing():
    """Older subs often have no metadata.plan; we fall back to matching price.id."""
    app_mod = _import_app()

    cust = _make_customer("cus_xyz", "mishalahmed@gmail.com")
    sub = _make_sub("sub_xyz", "active", plan_meta=None, price_id="price_starter_test")
    stripe_stub = _fake_stripe_module(
        customers=[cust],
        subs_by_customer={"cus_xyz": [sub]},
    )

    env_override = {
        "STRIPE_SECRET_KEY": "sk_test_dummy_for_tests",
        "STRIPE_PRICE_STARTER": "price_starter_test",
        "STRIPE_PRICE_PRO": "price_pro_test",
    }
    with patch.dict(os.environ, env_override, clear=False), \
         patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "has_active_plan", return_value=False), \
         patch.object(app_mod, "_raw_active_plan", return_value=None), \
         patch.object(app_mod, "set_plan", return_value=True) as mock_set_plan:
        with app_mod.app.test_request_context("/"):
            result = app_mod.user_has_active_plan("mishalahmed@gmail.com")
    assert result is True
    args, _ = mock_set_plan.call_args
    assert args[1] == "starter", f"expected plan=starter from price.id match, got {args[1]!r}"
    print("PASS  Plan resolved by price.id when metadata.plan is missing")


def run_test_stripe_fallback_writes_plan_gate_even_if_firestore_write_fails():
    """If set_plan returns False we should still let the user in via plan_gate."""
    app_mod = _import_app()

    cust = _make_customer("cus_fail", "mishalahmed@gmail.com")
    sub = _make_sub("sub_fail", "active", plan_meta="pro")
    stripe_stub = _fake_stripe_module(
        customers=[cust],
        subs_by_customer={"cus_fail": [sub]},
    )

    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "has_active_plan", return_value=False), \
         patch.object(app_mod, "_raw_active_plan", return_value=None), \
         patch.object(app_mod, "set_plan", return_value=False):
        with app_mod.app.test_request_context("/"):
            result = app_mod.user_has_active_plan("mishalahmed@gmail.com")
            from flask import session as flask_session
            gate = flask_session.get("plan_gate")
    assert result is True
    assert gate and gate.get("email") == "mishalahmed@gmail.com" and gate.get("plan") == "pro", \
        f"plan_gate was not stamped: {gate!r}"
    print("PASS  Session plan_gate is stamped even when Firestore write fails")


def run_test_no_stripe_customer_returns_false():
    """Email not in Stripe at all = genuinely unpaid = no access."""
    app_mod = _import_app()
    stripe_stub = _fake_stripe_module(customers=[], subs_by_customer={})

    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "has_active_plan", return_value=False), \
         patch.object(app_mod, "_raw_active_plan", return_value=None):
        with app_mod.app.test_request_context("/"):
            result = app_mod.user_has_active_plan("never-paid@example.com")
    assert result is False
    print("PASS  User without Stripe customer or subscription is correctly unpaid")


def run_test_firestore_hit_short_circuits_stripe_lookup():
    """If Firestore already says active, we must NOT hit Stripe (latency + cost)."""
    app_mod = _import_app()
    stripe_calls = {"count": 0}

    def exploding_customer_list(*args, **kwargs):
        stripe_calls["count"] += 1
        raise AssertionError("Stripe should not be called when Firestore has the plan")

    stripe_stub = types.SimpleNamespace(
        api_key=None,
        error=types.SimpleNamespace(InvalidRequestError=Exception),
        Customer=types.SimpleNamespace(list=exploding_customer_list),
    )

    fake_sub = {"plan": "pro", "status": "active"}
    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "has_active_plan", return_value=True), \
         patch.object(app_mod, "get_subscription", return_value=fake_sub):
        with app_mod.app.test_request_context("/"):
            result = app_mod.user_has_active_plan("j@doe.com")
    assert result is True
    assert stripe_calls["count"] == 0
    print("PASS  Firestore hit short-circuits Stripe lookup")


def run_test_payment_success_stale_session_id_goes_to_dashboard_for_paid_user():
    """/payment-success with an unknown session_id should not loop; paid user -> /dashboard."""
    app_mod = _import_app()

    class _InvalidRequest(Exception):
        pass

    stripe_stub = types.SimpleNamespace()
    stripe_stub.api_key = None
    stripe_stub.error = types.SimpleNamespace(InvalidRequestError=_InvalidRequest)

    class _Checkout:
        class Session:
            @staticmethod
            def retrieve(*args, **kwargs):
                raise _InvalidRequest("No such checkout.session: JM_uMMv...")

    stripe_stub.checkout = _Checkout

    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "user_has_active_plan", return_value=True):
        client = app_mod.app.test_client()
        with client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["user_email"] = "mishalahmed@gmail.com"
        resp = client.get("/payment-success?session_id=JM_uMMv_fake_stale_id", follow_redirects=False)
    assert resp.status_code == 302, f"expected redirect, got {resp.status_code}"
    assert resp.headers.get("Location", "").endswith("/dashboard"), \
        f"stale session_id must land a paid user on /dashboard, got {resp.headers.get('Location')!r}"
    print("PASS  Stale session_id does not loop; paid user redirects to /dashboard")


def run_test_payment_success_stale_session_id_unpaid_user_goes_to_choose_plan():
    """Same route, logged in but genuinely unpaid -> /choose-plan (not login loop)."""
    app_mod = _import_app()

    class _InvalidRequest(Exception):
        pass

    stripe_stub = types.SimpleNamespace(
        api_key=None,
        error=types.SimpleNamespace(InvalidRequestError=_InvalidRequest),
    )

    class _Checkout:
        class Session:
            @staticmethod
            def retrieve(*args, **kwargs):
                raise _InvalidRequest("No such checkout.session: xxx")

    stripe_stub.checkout = _Checkout

    with patch.dict(sys.modules, {"stripe": stripe_stub}), \
         patch.object(app_mod, "user_has_active_plan", return_value=False):
        client = app_mod.app.test_client()
        with client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["user_email"] = "unpaid@example.com"
        resp = client.get("/payment-success?session_id=xxx", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers.get("Location", "").endswith("/choose-plan"), \
        f"unpaid user with stale session_id must land on /choose-plan, got {resp.headers.get('Location')!r}"
    print("PASS  Stale session_id for unpaid user redirects to /choose-plan (no loop)")


def main():
    tests = [
        run_test_no_firestore_but_active_stripe_sub_with_metadata,
        run_test_plan_resolved_from_price_id_when_metadata_missing,
        run_test_stripe_fallback_writes_plan_gate_even_if_firestore_write_fails,
        run_test_no_stripe_customer_returns_false,
        run_test_firestore_hit_short_circuits_stripe_lookup,
        run_test_payment_success_stale_session_id_goes_to_dashboard_for_paid_user,
        run_test_payment_success_stale_session_id_unpaid_user_goes_to_choose_plan,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as err:
            print(f"FAIL  {t.__name__}: {err}")
            failed += 1
        except Exception as err:  # noqa: BLE001
            import traceback
            print(f"ERROR {t.__name__}: {err}")
            traceback.print_exc()
            failed += 1
    print()
    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print(f"All {len(tests)} test(s) passed")


if __name__ == "__main__":
    main()
