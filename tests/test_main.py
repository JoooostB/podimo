import asyncio

import main


def test_split_username_region_locale():
    assert main.split_username_region_locale("a@b.com,de,de-DE") == ("a@b.com", "de", "de-DE")
    # Fall back to Dutch defaults when region/locale are missing
    assert main.split_username_region_locale("a@b.com") == ("a@b.com", "nl", "nl-NL")


def test_extract_audio_url_prefers_direct_audio():
    episode = {
        "audio": {"url": "https://cdn.example.com/ep.mp3", "duration": 60},
        "streamMedia": None,
    }
    assert main.extract_audio_url(episode) == ("https://cdn.example.com/ep.mp3", 60)


def test_extract_audio_url_rewrites_hls_stream():
    episode = {
        "audio": None,
        "streamMedia": {
            "url": "https://cdn.example.com/hls-media/abc/main.m3u8",
            "duration": 90,
        },
    }
    url, duration = main.extract_audio_url(episode)
    assert url == "https://cdn.example.com/audios/abc.mp3"
    assert duration == 90


def test_extract_audio_url_handles_missing_sources():
    episode = {"audio": None, "streamMedia": None}
    assert main.extract_audio_url(episode) == (None, 0)


def test_set_itunes_image_accepts_and_skips_by_extension():
    class FakePodcast:
        def __init__(self):
            self.value = None

        def itunes_image(self, url):
            self.value = url

    class FakeEntry:
        def __init__(self):
            self.podcast = FakePodcast()

    # A plain jpg/png is accepted, including with a query string
    e = FakeEntry()
    main.set_itunes_image(e, "https://cdn.podimo.com/a/cover.jpg")
    assert e.podcast.value == "https://cdn.podimo.com/a/cover.jpg"

    e = FakeEntry()
    main.set_itunes_image(e, "https://cdn.podimo.com/a/cover.png?width=640")
    assert e.podcast.value == "https://cdn.podimo.com/a/cover.png?width=640"

    # No usable extension: skipped rather than raising
    e = FakeEntry()
    main.set_itunes_image(e, "https://cdn.podimo.com/a/cover")
    assert e.podcast.value is None

    e = FakeEntry()
    main.set_itunes_image(e, None)
    assert e.podcast.value is None


def test_extract_podcast_id():
    pid = "26b40936-8fa4-4c28-b038-16dc05db09a4"
    assert main.extract_podcast_id(pid) == pid
    assert main.extract_podcast_id(f"https://open.podimo.com/podcast/{pid}") == pid
    assert main.extract_podcast_id(f"https://open.podimo.com/podcast/{pid}/") == pid
    assert main.extract_podcast_id(f"  https://open.podimo.com/nl-nl/podcast/{pid}  ") == pid
    assert main.extract_podcast_id(None) is None


def test_chunks():
    assert list(main.chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_index_page_renders():
    async def fetch():
        client = main.app.test_client()
        return await client.get("/")

    response = asyncio.run(fetch())
    assert response.status_code == 200


def test_feed_without_auth_asks_for_credentials():
    async def fetch():
        client = main.app.test_client()
        return await client.get("/feed/abc123.xml")

    response = asyncio.run(fetch())
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
