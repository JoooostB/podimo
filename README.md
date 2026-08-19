<div align="center">

# Podimo to RSS

[![CI](https://github.com/JoooostB/podimo/actions/workflows/ci.yml/badge.svg)](https://github.com/JoooostB/podimo/actions/workflows/ci.yml)
[![License: EUPL-1.2](https://img.shields.io/badge/license-EUPL--1.2-blue)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

Podimo is a proprietary podcasting player that enables you to listen to various exclusive shows behind a paywall.
This tool allows you to stream Podimo podcasts with your preferred podcast player, without having to use the Podimo app.
</div>

## About this fork

This is a fork of [ThijsRay/podimo](https://github.com/ThijsRay/podimo) by Thijs Raymakers, who built the whole thing: the Podimo API client, the feed generation, the caching, the proxy support. All credit for the idea and the original implementation goes to him.

If this tool is useful to you, consider buying Thijs a coffee:

<a href="https://www.buymeacoffee.com/thijsr"><img src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=thijsr&button_colour=BD5FFF&font_colour=ffffff&font_family=Poppins&outline_colour=000000&coffee_colour=FFDD00" /></a>

### What this fork adds

- **Feed URLs without credentials:** upstream embeds your URL-encoded Podimo email and password in every feed URL. Here, the web form stores them on the server encrypted (Fernet, key in `PODIMO_ENCRYPTION_KEY` or an auto-generated `0600` key file) and hands out a random token URL like `/f/dK3x...xml` instead. Old-style URLs with embedded credentials still work, so existing subscriptions don't break.
- **Log hygiene:** credential-bearing URLs and account emails are never written to logs, and the example config no longer ships with debug logging on.
- **Cache privacy:** feed responses carry `Cache-Control: private` and `Vary: Authorization`, so an intermediate cache can't replay one user's feed to another.
- **Current dependencies, locked:** Python 3.13, Quart 0.21, aiohttp 3.14 and friends, managed with uv and a hash-pinned `uv.lock`. Upstream pinned 2023 versions in a requirements.txt.
- **CI and automated updates:** every push and pull request runs ruff, pytest, a pip-audit CVE check and a Docker smoke build. Renovate keeps dependencies current and merges automatically once CI is green; the CVE check blocks a bad release from auto-merging.
- **Signed multi-arch images:** linux/amd64 and linux/arm64 images publish to `ghcr.io/joooostb/podimo` on every push to main and on version tags, signed with keyless cosign. The container runs as a non-root user (UID 1000).
- **A redesigned web interface:** accessible forms with proper labels and error handling, dark mode, and a result page that works on plain-HTTP self-hosted instances.
- **A test suite:** upstream had none; the token store, URL generation, feed parsing helpers and routes are covered.
- **A Kubernetes example:** a hardened StatefulSet, Service and HTTPRoute (with an Ingress alternative) in [deploy/kubernetes.yaml](deploy/kubernetes.yaml).

## Running with Docker (recommended)

1. Pull the image:

```sh
docker pull ghcr.io/joooostb/podimo:latest
```

2. Run it. See [.env.example](.env.example) for all configuration options; each one can be set as an environment variable. The container runs as UID 1000, so give it ownership of the cache directory once before the first start.

```sh
mkdir -p cache && sudo chown -R 1000:1000 cache
docker run --rm \
    -p 12104:12104 \
    -v $(pwd)/cache:/src/cache \
    ghcr.io/joooostb/podimo:latest
```

3. Visit http://localhost:12104. You should see the site now!

Images are published for linux/amd64 and linux/arm64. The `latest` tag follows the main branch; version tags (`2`, `2.0`, `2.0.0`) follow releases.

## Running on Kubernetes

[deploy/kubernetes.yaml](deploy/kubernetes.yaml) holds a hardened example: a StatefulSet with a persistent cache volume, a Service, and an HTTPRoute (plus a commented Ingress alternative). It runs the pod as the image's non-root user with a read-only root filesystem, and reads the feed-credential encryption key from a Kubernetes Secret instead of the cache volume. The file's header comments cover creating that Secret and what to adjust.

## Installing directly on a server

Make sure you have Python 3.11 or newer installed.

1. Clone this repository and enter the newly created directory:

```sh
git clone https://github.com/JoooostB/podimo
cd podimo
```

2. Get the latest release and install it as a systemd service:

```sh
make update
make install
```

3. Start it:

```sh
make start
```

4. Visit http://localhost:12104. If you want to reach it from other machines, edit the configuration with:

```sh
make config
```

New to self-hosting? The [step-by-step tutorial](tutorial.md) walks through a full Raspberry Pi setup.

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/). If you prefer not to install anything on your machine, everything runs in a container:

```sh
docker build -t podimo .
docker run --rm -p 12104:12104 podimo
```

With uv installed, `uv sync` creates the environment, `uv run python main.py` starts the server, `uv run pytest` runs the tests and `uv run ruff check .` lints. CI runs the same checks on every push and pull request. Dependency updates are automated with Renovate.

## Configuration

A complete list of all configuration options can be found in the [.env.example file](.env.example).

## Bot detection

Depending on your usage patterns, it might be necessary to bypass Podimo's anti-bot mechanisms.
This can be done through Zenrows, ScraperAPI or a generic HTTP proxy.

### Setting up a Zenrows account

1. Go to [app.zenrows.com/register](https://app.zenrows.com/register) and create a free account
2. Copy your API key and add it to the `ZENROWS_API` environment variable

### Setting up a ScraperAPI account

1. Go to [dashboard.scraperapi.com/signup](https://dashboard.scraperapi.com/signup) and create a free account
2. Copy your API key and add it to the `SCRAPER_API` environment variable

## Privacy

The script keeps track of a few things:
- Your username and password. Feeds created through the web form store them on the server, encrypted with a key that lives in `PODIMO_ENCRYPTION_KEY` or in a `0600` key file next to the store. This is what lets the feed URL be a random token instead of containing your password. Deleting the entry from `cache/feed_tokens` revokes the feed.
- A cryptographic hash that is calculated based on your username and password.
- A Podimo access token, which is kept for accessing pages after logging in. It stays in memory unless `STORE_TOKENS_ON_DISK` is set to true.

Credentials and feed URLs are _never_ logged. One caution: if you configure `ZENROWS_API` or `SCRAPER_API`, your Podimo email and password pass through that third-party proxy on every login, because the proxy has to carry the login request to Podimo for you.

## Built with AI

The 2026 modernization of this fork (dependency updates, uv packaging, CI workflows, Renovate setup, the tokenized feed URLs, a security review, the redesigned web interface and this README) was done with Claude, working under the direction of the maintainer, who reviews what ships. The core application logic is Thijs Raymakers' original work.

## License

Licensed under the [EUPL, version 1.2](LICENSE) or later.

Copyright 2022-2023 Thijs Raymakers, modifications copyright 2026 Joost Buskermolen.
