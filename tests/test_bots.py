"""Bot CRUD smoke tests."""


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json["ok"] is True


def test_bots_require_auth(client):
    r = client.get("/api/v1/bots")
    assert r.status_code == 401


def test_create_list_delete(auth_client):
    r = auth_client.post(
        "/api/v1/bots",
        json={"name": "demo", "internet": True},
    )
    assert r.status_code == 201
    assert r.json["name"] == "demo"
    assert r.json["capability"] == "none"

    r = auth_client.get("/api/v1/bots")
    assert len(r.json) == 1

    r = auth_client.delete("/api/v1/bots/demo")
    assert r.status_code == 200
    assert auth_client.get("/api/v1/bots").json == []


def test_create_freeform_name_slugifies(auth_client):
    r = auth_client.post("/api/v1/bots", json={"name": "Bad Name"})
    assert r.status_code == 201
    assert r.json["name"] == "bad-name"
    assert r.json["label"] == "Bad Name"
    auth_client.delete("/api/v1/bots/bad-name")


def test_create_rejects_case_insensitive_duplicate(auth_client):
    assert auth_client.post("/api/v1/bots", json={"name": "Test"}).status_code == 201
    for name in ("test", "TEST", "TeSt"):
        r = auth_client.post("/api/v1/bots", json={"name": name})
        assert r.status_code == 409, (name, r.status_code, r.data)
    # Same label, different spelling of spaces/hyphens can still collide on slug
    # with a suffix — but pure case variants must not.
    auth_client.delete("/api/v1/bots/test")


def test_create_slug_collision_suffix_distinct_labels(auth_client):
    assert auth_client.post("/api/v1/bots", json={"name": "Foo Bar"}).status_code == 201
    # Different display (casefold ≠) but same derived slug → suffix
    r = auth_client.post("/api/v1/bots", json={"name": "foo--bar"})
    assert r.status_code == 201
    assert r.json["name"] == "foo-bar-2"
    assert r.json["label"] == "foo--bar"
    auth_client.delete("/api/v1/bots/foo-bar")
    auth_client.delete("/api/v1/bots/foo-bar-2")


def test_create_explicit_slug(auth_client):
    r = auth_client.post(
        "/api/v1/bots",
        json={"name": "Mon Assistant", "slug": "asst"},
    )
    assert r.status_code == 201
    assert r.json["name"] == "asst"
    assert r.json["label"] == "Mon Assistant"
    auth_client.delete("/api/v1/bots/asst")


def test_invalid_name(auth_client):
    r = auth_client.post("/api/v1/bots", json={"name": "!!!"})
    assert r.status_code in (400, 422)


def test_bearer_auth(client, bearer_headers):
    r = client.post(
        "/api/v1/bots",
        json={"name": "tok"},
        headers=bearer_headers,
    )
    assert r.status_code == 201
