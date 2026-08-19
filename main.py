# Copyright 2022 Thijs Raymakers
#
# Licensed under the EUPL, Version 1.2 or – as soon they
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# You may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
#
# https://joinup.ec.europa.eu/software/page/eupl
#
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.

import asyncio
import logging
import re
import traceback
from hashlib import sha256
from mimetypes import guess_type
from urllib.parse import quote, urlsplit

import cloudscraper
from aiohttp import ClientSession, ClientTimeout, CookieJar
from feedgen.feed import FeedGenerator
from hypercorn.asyncio import serve
from hypercorn.config import Config
from quart import Quart, Response, render_template, request

import podimo.cache as cache
from podimo import feedtokens
from podimo.client import PodimoClient
from podimo.config import (
    BLOCKED,
    CACHE_DIR,
    DEBUG,
    HEAD_CACHE_TIME,
    HTTP_PROXY,
    LOCAL_CREDENTIALS,
    LOCALES,
    PODCAST_CACHE_TIME,
    PODIMO_BIND_HOST,
    PODIMO_EMAIL,
    PODIMO_HOSTNAME,
    PODIMO_PASSWORD,
    PODIMO_PROTOCOL,
    PUBLIC_FEEDS,
    REGIONS,
    SCRAPER_API,
    STORE_TOKENS_ON_DISK,
    TOKEN_CACHE_TIME,
    ZENROWS_API,
)
from podimo.utils import generateHeaders, randomHexId

# Setup Quart, used for serving the web pages
app = Quart(__name__)
proxies = dict()

# Logging is configured in podimo.config, which respects the DEBUG setting


def example():
    return f"""Example
------------
Username: example@example.com
Password: this-is-my-password
Podcast ID: 12345-abcdef

The URL will be
https://example%40example.com:this-is-my-password@{PODIMO_HOSTNAME}/feed/12345-abcdef.xml

Note that the username and password should be URL encoded. This can be done with
a tool like https://gchq.github.io/CyberChef/#recipe=URL_Encode(true)
"""


@app.after_request
def allow_cors(response):
    response.headers.set("Access-Control-Allow-Origin", "*")
    response.headers.set("Access-Control-Allow-Methods", "GET, POST")
    if request.path.startswith("/feed/") or request.path.startswith("/f/"):
        # Feed responses are served under credentials or an opaque token:
        # intermediate caches must never replay them to another requester
        response.headers.set("Cache-Control", "private, max-age=900")
        response.headers.set("Vary", "Authorization")
        # Feed URLs grant access, so they never appear in logs
        logged_path = "[feed url redacted]"
    elif request.method == "POST":
        # The POST result page contains the generated feed URL
        response.headers.set("Cache-Control", "no-store")
        logged_path = request.path
    else:
        response.headers.set("Cache-Control", "max-age=900")
        logged_path = request.path
    logging.debug(
        f"Incoming {request.method} request for '{logged_path}' "
        f"from User-Agent {request.user_agent} at {request.remote_addr}."
    )
    return response


def authenticate():
    return Response(
        f"""401 Unauthorized.
You need to login with the correct credentials for Podimo.

{example()}""",
        401,
        {"Content-Type": "text/plain", "WWW-Authenticate": "Basic realm='Podimo credentials'"},
    )


def initialize_client(username: str, password: str, region: str, locale: str) -> PodimoClient:
    client = PodimoClient(username, password, region, locale)

    # Check if there is an authentication token already in memory. If so, use that one.
    # If it is expired, request a new token.
    key = client.key
    client.token = cache.getCacheEntry(key, cache.TOKENS)

    # Check if we previously created a cookie jar
    if key not in cache.cookie_jars:
        cache.cookie_jars[key] = CookieJar()
    client.cookie_jar = cache.cookie_jars[key]
    return client


async def check_auth(username, password, region, locale, scraper):
    try:
        client = initialize_client(username, password, region, locale)
        if client.token:
            return client

        await client.podimoLogin(scraper)
        cache.insertIntoTokenCache(client.key, client.token)
        return client

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        if DEBUG:
            traceback.print_exc()
    return None


podcast_id_pattern = re.compile(r"[0-9a-fA-F\-]+")


@app.route("/", methods=["POST", "GET"])
async def index():
    errors = []
    if request.method == "POST":
        form = await request.form
        email = form.get("email")
        password = form.get("password")
        podcast_id = form.get("podcast_id")
        region = form.get("region")
        locale = form.get("locale")

        if not LOCAL_CREDENTIALS:
            if email is None or email == "":
                errors.append("Email is required")
            if password is None or password == "":
                errors.append("Password is required")
        if podcast_id is None or podcast_id == "":
            errors.append("Podcast ID is required")
        elif podcast_id_pattern.fullmatch(podcast_id) is None:
            errors.append("Podcast ID is not valid")
        if region is None or region == "":
            errors.append("Region is required")
        elif region not in [region_code for (region_code, _) in REGIONS]:
            errors.append("Region is not valid")
        if locale is None or locale == "":
            errors.append("Locale is required")
        elif locale not in LOCALES:
            errors.append("Locale is not valid")

        if not errors:
            if LOCAL_CREDENTIALS:
                podcast_id = quote(str(podcast_id), safe="")
                region = quote(str(region), safe="")
                locale = quote(str(locale), safe="")
                url = f"{PODIMO_PROTOCOL}://{PODIMO_HOSTNAME}/feed/{podcast_id}.xml?{randomHexId(10)}&region={region}&locale={locale}"
            else:
                # Store the credentials encrypted on the server and hand out an
                # opaque token, so the feed URL itself contains no credentials
                token = feedtokens.create_feed_token(email, password, region, locale, podcast_id)
                url = f"{PODIMO_PROTOCOL}://{PODIMO_HOSTNAME}/f/{token}.xml"

            # The URL is never logged: it grants access to the feed
            logging.debug(f"Created a feed URL for podcast {podcast_id}.")
            return await render_template("feed_location.html", url=url)

    return await render_template(
        "index.html", errors=errors, locales=LOCALES, regions=REGIONS, need_credentials=not LOCAL_CREDENTIALS
    )


@app.errorhandler(404)
async def not_found(error):
    return Response(f"404 Not found.\n\n{example()}", 404, {"Content-Type": "text/plain"})


@app.route("/feed/<string:podcast_id>.xml")
async def serve_basic_auth_feed(podcast_id):
    if LOCAL_CREDENTIALS:
        args = request.args
        region = args.get("region")
        locale = args.get("locale")
        return await serve_feed(PODIMO_EMAIL, PODIMO_PASSWORD, podcast_id, region, locale)
    else:
        auth = request.authorization
        if not auth:
            return authenticate()
        else:
            username, region, locale = split_username_region_locale(auth.username)
            return await serve_feed(username, auth.password, podcast_id, region, locale)


feed_token_pattern = re.compile(r"[A-Za-z0-9_\-]+")


@app.route("/f/<string:token>.xml")
async def serve_token_feed(token):
    if feed_token_pattern.fullmatch(token) is None:
        return Response("Invalid feed token", 400, {})
    entry = feedtokens.resolve_feed_token(token)
    if entry is None:
        return Response("Feed not found", 404, {})
    return await serve_feed(entry["email"], entry["password"], entry["podcast_id"], entry["region"], entry["locale"])


def split_username_region_locale(string):
    s = string.split(",")
    if len(s) == 3:
        return tuple(s)
    else:
        return (s[0], "nl", "nl-NL")


def token_key(username, password):
    key = sha256(b"~".join([username.encode("utf-8"), password.encode("utf-8")])).hexdigest()
    return key


async def serve_feed(username, password, podcast_id, region, locale):

    logging.debug(
        f"Feed request for podcast {podcast_id} from IP {request.remote_addr} with User-Agent:{request.user_agent}."
    )

    # Check if it is a valid podcast id string
    if podcast_id_pattern.fullmatch(podcast_id) is None:
        return Response("Invalid podcast id format", 400, {})

    if region not in [region_code for (region_code, _) in REGIONS]:
        return Response("Invalid region", 400, {})
    if locale not in LOCALES:
        return Response("Invalid locale", 400, {})

    # Check if url contains unique ID or podcastID in blocked list. If so, return HTTP code 410 GONE
    # Token URLs don't contain the podcast id, so check it separately
    if podcast_id in BLOCKED or any(item in request.url for item in BLOCKED):
        logging.debug(f"Blocked! Podcast {podcast_id} is on local block list")
        return Response("Podcast is gone", 410, {})

    with cloudscraper.create_scraper() as scraper:
        scraper.proxies = proxies
        client = await check_auth(username, password, region, locale, scraper)
        if not client:
            return authenticate()

        # Get a list of valid podcasts
        try:
            podcasts = await podcastsToRss(podcast_id, await client.getPodcasts(podcast_id, scraper), locale)
        except Exception as e:
            exception = str(e)
            if "Podcast not found" in exception:
                return Response("Podcast not found. Are you sure you have the correct ID?", 404, {})
            logging.error(f"Error while fetching podcasts: {exception}")
            return Response("Something went wrong while fetching the podcasts", 500, {})
        return Response(podcasts, mimetype="text/xml")


async def urlHeadInfo(session, id, url, locale):
    entry = cache.getHeadEntry(id)
    if entry:
        return entry

    retries = 3  # Number of retries
    timeout = ClientTimeout(total=10)  # 10 seconds timeout for each try

    for attempt in range(retries):
        try:
            logging.debug(f"HEAD request to {url} (Attempt {attempt + 1})")
            async with session.head(
                url, allow_redirects=True, headers=generateHeaders(None, locale), timeout=timeout
            ) as response:
                content_length = 0
                content_type, _ = guess_type(url)
                if "content-length" in response.headers:
                    content_length = response.headers["content-length"]
                if content_type is None and "content-type" in response.headers:
                    content_type = response.headers["content-type"]
                else:
                    content_type = "audio/mpeg"
                cache.insertIntoHeadCache(id, content_length, content_type)
                return (content_length, content_type)

        except TimeoutError:
            if attempt < retries - 1:
                logging.info(f"Retrying HEAD request to {url} (Attempt {attempt + 2})")
                await asyncio.sleep(1)  # Wait for 1 second before retrying
            else:
                logging.error(f"All retries failed for HEAD request to {url}")
                raise  # Re-raise the last exception if all retries fail


def extract_audio_url(episode):
    duration = 0
    url = None
    if episode["audio"]:
        url = episode["audio"]["url"]
        duration = episode["audio"]["duration"]

    if url is None or url == "":
        if episode["streamMedia"]:
            url = episode["streamMedia"]["url"]
            duration = episode["streamMedia"]["duration"]
            if "hls-media" in url and "/main.m3u8" in url:
                url = url.replace("hls-media", "audios")
                url = url.replace("/main.m3u8", ".mp3")

    return url, duration


def set_itunes_image(target, image_url):
    # feedgen 1.0 rejects itunes image URLs that don't end in png/jpg. Podimo's
    # image URLs often carry a query string or no extension, so only set the
    # image when it passes that check and skip it otherwise (the feed is still
    # valid without per-item artwork) rather than failing the whole feed.
    if not image_url:
        return
    path = urlsplit(image_url).path.lower()
    if path.endswith((".png", ".jpg", ".jpeg")):
        target.podcast.itunes_image(image_url)


async def addFeedEntry(fg, episode, session, locale):
    fe = fg.add_entry()
    fe.guid(episode["id"])
    fe.title(episode["title"])
    fe.description(episode["description"])
    fe.pubDate(episode.get("publishDatetime", episode.get("datetime")))
    set_itunes_image(fe, episode["imageUrl"])

    url, duration = extract_audio_url(episode)
    if url is None:
        return
    logging.debug(f"Found podcast '{episode['title']}'")
    fe.podcast.itunes_duration(duration)
    content_length, content_type = await urlHeadInfo(session, episode["id"], url, locale)
    fe.enclosure(url, content_length, content_type)


def chunks(x, n):
    for i in range(0, len(x), n):
        yield x[i : i + n]


async def podcastsToRss(podcast_id, data, locale):
    fg = FeedGenerator()
    fg.load_extension("podcast")

    podcast = data["podcast"]
    episodes = data["episodes"]

    if len(episodes) > 0:
        last_episode = episodes[0]
        title = podcast["title"]
        if podcast["title"] is None:
            title = last_episode["podcastName"]
        fg.title(title)

        if podcast["description"]:
            fg.description(podcast["description"])
        else:
            fg.description(title)

        fg.link(href=f"https://podimo.com/shows/{podcast_id}", rel="alternate")

        image = podcast["images"]["coverImageUrl"]
        if image is None:
            image = last_episode["imageUrl"]
        fg.image(image)

        language = podcast["language"]
        if language is None:
            language = locale
        fg.language(language)

        artist = podcast["authorName"]
        if artist is None:
            artist = last_episode["artist"]
        fg.podcast.itunes_author(artist)

        if not PUBLIC_FEEDS:
            fg.podcast.itunes_block(True)

    async with ClientSession() as session:
        for chunk in chunks(episodes, 5):
            await asyncio.gather(*[addFeedEntry(fg, episode, session, locale) for episode in chunk])

    feed = fg.rss_str(pretty=True)
    return feed


async def spawn_web_server():
    config = Config()
    config.bind = [PODIMO_BIND_HOST]
    config.read_timeout = 60
    config.graceful_timeout = 5
    config.backlog = 1000
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    await serve(app, config)


async def main():
    if HTTP_PROXY:
        global proxies
        logging.info(f"Running with https proxy defined in environmental variable HTTP_PROXY: {HTTP_PROXY}")
        proxies["https"] = HTTP_PROXY
    tasks = [spawn_web_server()]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    if DEBUG:
        logging.info(f"""Spawning server on {PODIMO_BIND_HOST}
Configuration:
- DEBUG: {DEBUG}
- LOCAL CREDENTIALS: {LOCAL_CREDENTIALS}
- PODIMO_HOSTNAME: {PODIMO_HOSTNAME}
- PODIMO_BIND_HOST: {PODIMO_BIND_HOST}
- PODIMO_PROTOCOL: {PODIMO_PROTOCOL}
- PUBLIC_FEEDS: {PUBLIC_FEEDS}
- HTTP_PROXY: {HTTP_PROXY}
- ZENROWS_API: {ZENROWS_API}
- SCRAPER_API: {SCRAPER_API}
- CACHE_DIR: {CACHE_DIR}
- STORE_TOKENS_ON_DISK: {STORE_TOKENS_ON_DISK}
- TOKEN_CACHE_TIME: {TOKEN_CACHE_TIME} sec
- PODCAST_CACHE_TIME: {PODCAST_CACHE_TIME} sec
- HEAD_CACHE_TIME: {HEAD_CACHE_TIME} sec
- BLOCKING: {BLOCKED}
""")
    asyncio.run(main())
