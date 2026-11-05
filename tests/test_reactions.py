"""Emoji reactions on user messages."""


def test_reaction_on_user_message(auth_client):
    auth_client.post("/api/v1/bots", json={"name": "react1"})
    created = auth_client.post(
        "/api/v1/bots/react1/messages", json={"content": "Merci !"}
    )
    assert created.status_code == 201, created.data
    mid = created.json["id"]

    heart = auth_client.post(
        "/api/v1/bots/react1/reactions",
        json={"emoji": "❤️", "message_id": mid},
    )
    assert heart.status_code == 200, heart.data
    assert heart.json["meta"]["reactions"] == ["❤️"]
    assert heart.json["content"] == "Merci !"

    again = auth_client.post(
        "/api/v1/bots/react1/reactions",
        json={"emoji": "❤️", "message_id": mid},
    )
    assert again.status_code == 200
    assert again.json["meta"]["reactions"] == ["❤️"]

    thumb = auth_client.post(
        "/api/v1/bots/react1/reactions",
        json={"emoji": "👍", "message_id": mid},
    )
    assert thumb.status_code == 200
    assert thumb.json["meta"]["reactions"] == ["❤️", "👍"]


def test_reaction_rejects_plain_text(auth_client):
    from autonomous.services import reactions as reactions_svc

    auth_client.post("/api/v1/bots", json={"name": "react2"})
    created = auth_client.post(
        "/api/v1/bots/react2/messages", json={"content": "Merci !"}
    )
    mid = created.json["id"]
    word = auth_client.post(
        "/api/v1/bots/react2/reactions",
        json={"emoji": "Merci", "message_id": mid},
    )
    assert word.status_code == 400
    reactions_svc.set_turn_message("react2", None)
    missing = auth_client.post(
        "/api/v1/bots/react2/reactions",
        json={"emoji": "❤️"},
    )
    assert missing.status_code == 400


def test_reaction_uses_current_turn(auth_client, home):
    from autonomous.services import chat as chat_svc
    from autonomous.services import reactions as reactions_svc

    auth_client.post("/api/v1/bots", json={"name": "react3"})
    msg = chat_svc.send_message("react3", "Merci !", home=home, trigger_agent=False)
    reactions_svc.set_turn_message("react3", msg["id"])
    heart = auth_client.post(
        "/api/v1/bots/react3/reactions",
        json={"emoji": "❤️"},
    )
    assert heart.status_code == 200, heart.data
    assert heart.json["id"] == msg["id"]
    assert heart.json["meta"]["reactions"] == ["❤️"]

    assistant = chat_svc.create_message(
        "react3", "de rien", role="assistant", home=home
    )
    denied = auth_client.post(
        "/api/v1/bots/react3/reactions",
        json={"emoji": "❤️", "message_id": assistant["id"]},
    )
    assert denied.status_code == 400
