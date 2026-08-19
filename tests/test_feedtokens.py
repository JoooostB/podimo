import asyncio

from podimo import feedtokens


def test_token_roundtrip():
    token = feedtokens.create_feed_token("a@b.com", "hunter2", "nl", "nl-NL", "abc-123")
    entry = feedtokens.resolve_feed_token(token)
    assert entry == {
        "email": "a@b.com",
        "password": "hunter2",
        "region": "nl",
        "locale": "nl-NL",
        "podcast_id": "abc-123",
    }


def test_tokens_are_unique_and_opaque():
    t1 = feedtokens.create_feed_token("a@b.com", "hunter2", "nl", "nl-NL", "abc-123")
    t2 = feedtokens.create_feed_token("a@b.com", "hunter2", "nl", "nl-NL", "abc-123")
    assert t1 != t2
    assert "a@b.com" not in t1
    assert "hunter2" not in t1


def test_unknown_token_resolves_to_none():
    assert feedtokens.resolve_feed_token("does-not-exist") is None


def test_tampered_blob_resolves_to_none():
    token = feedtokens.create_feed_token("a@b.com", "hunter2", "nl", "nl-NL", "abc-123")
    feedtokens.feed_store[token] = b"garbage"
    assert feedtokens.resolve_feed_token(token) is None


def test_form_submission_returns_token_url():
    import main

    async def submit():
        client = main.app.test_client()
        return await client.post(
            "/",
            form={
                "email": "a@b.com",
                "password": "hunter2",
                "podcast_id": "abc-123",
                "region": "nl",
                "locale": "nl-NL",
            },
        )

    response = asyncio.run(submit())
    assert response.status_code == 200
    # The page contains the secret feed URL, so it must never be cached
    assert response.headers["Cache-Control"] == "no-store"
    body = asyncio.run(response.get_data(as_text=True))
    assert "/f/" in body
    assert "hunter2" not in body


def test_token_feed_route_rejects_unknown_token():
    import main

    async def fetch():
        client = main.app.test_client()
        return await client.get("/f/nonexistenttoken.xml")

    response = asyncio.run(fetch())
    assert response.status_code == 404


def test_feed_routes_get_private_cache_headers():
    import main

    async def fetch(path):
        client = main.app.test_client()
        return await client.get(path)

    feed = asyncio.run(fetch("/f/nonexistenttoken.xml"))
    assert feed.headers["Cache-Control"] == "private, max-age=900"
    assert feed.headers["Vary"] == "Authorization"

    index = asyncio.run(fetch("/"))
    assert index.headers["Cache-Control"] == "max-age=900"
