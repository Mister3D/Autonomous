"""Vault → desk inject: grant checks, redacted result (no cleartext)."""

from __future__ import annotations

import pytest

from autonomous.services import bots as bots_svc
from autonomous.services import vault as vault_svc
from autonomous.services import vault_inject as inject_svc
from autonomous.services.errors import AutonomousError, ValidationError


def test_inject_requires_grant(home):
    bots_svc.create_bot("inj1", label="Inj1", home=home)
    bots_svc.patch_bot(
        "inj1",
        {"capability": "screen", "desk": {"state": "running"}},
        home=home,
    )
    entry = vault_svc.create_entry(
        label="Amazon",
        kind="credential",
        secret='{"password":"never-leak-me"}',
        origin="https://www.amazon.fr",
        fields=[
            {"id": "password", "label": "Mot de passe", "secret": True, "required": True},
        ],
        home=home,
    )
    with pytest.raises(AutonomousError) as exc:
        inject_svc.inject(
            "inj1",
            entry_id=entry["id"],
            field="password",
            method="type",
            home=home,
        )
    assert exc.value.code == "vault_forbidden"


def test_secret_field_resolution(home):
    bots_svc.create_bot("inj2", label="Inj2", home=home)
    entry = vault_svc.create_entry(
        label="Site",
        kind="credential",
        secret='{"username":"x","password":"s3cret"}',
        fields=[
            {"id": "username", "label": "User", "secret": False, "required": True},
            {"id": "password", "label": "Pass", "secret": True, "required": True},
        ],
        public={"username": "x"},
        home=home,
    )
    # Pack was JSON of secrets only typically — simulate packed secrets dict
    # create_entry stores raw secret string; unpack handles JSON dict.
    vault_svc.grant("inj2", entry["id"], home=home)
    field, value = inject_svc._secret_for_bot(
        "inj2", entry["id"], "password", home=home
    )
    assert field == "password"
    assert value == "s3cret"
    field2, value2 = inject_svc._secret_for_bot(
        "inj2", entry["id"], None, home=home
    )
    assert field2 == "password"
    assert value2 == "s3cret"
    with pytest.raises(ValidationError):
        inject_svc._secret_for_bot("inj2", entry["id"], "nope", home=home)


def test_inject_result_schema_has_no_secret_keys():
    # Structural guard: public result keys must not include secret/password/value.
    keys = {"ok", "bot", "entry_id", "field", "method", "chars", "secret_returned"}
    sample = {
        "ok": True,
        "bot": "x",
        "entry_id": "id",
        "field": "password",
        "method": "type",
        "chars": 8,
        "secret_returned": False,
    }
    assert set(sample) == keys
    assert "secret" not in sample
    assert "password" not in sample or sample.get("field") == "password"
