"""UI locale is a mono-user setting (en|fr) restored across browsers."""

from __future__ import annotations

from autonomous.services import settings as settings_svc


def test_locale_default_and_roundtrip(home):
    assert settings_svc.get("locale", home=home) == "en"
    out = settings_svc.set_many({"locale": "fr"}, home=home)
    assert out["locale"] == "fr"
    assert settings_svc.get("locale", home=home) == "fr"
    settings_svc.set_many({"locale": "en"}, home=home)
    assert settings_svc.get("locale", home=home) == "en"


def test_locale_rejects_unknown(home):
    from autonomous.services.errors import ValidationError

    try:
        settings_svc.set_many({"locale": "de"}, home=home)
        assert False, "expected ValidationError"
    except ValidationError as exc:
        assert exc.code == "invalid_locale"


def test_locale_via_api(auth_client, home):
    r = auth_client.put("/api/v1/settings", json={"locale": "fr"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["locale"] == "fr"
    assert auth_client.get("/api/v1/settings").get_json()["locale"] == "fr"
    bad = auth_client.put("/api/v1/settings", json={"locale": "es"})
    assert bad.status_code in (400, 422)
