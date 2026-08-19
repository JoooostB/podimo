# Copyright 2026 Joost Buskermolen
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

# Opaque feed tokens: instead of embedding Podimo credentials in the feed URL,
# the web form stores them encrypted on disk and hands out a random token.
# The encryption key comes from PODIMO_ENCRYPTION_KEY, or is generated once
# and kept next to the store, so a copied database file alone is useless.

import json
import logging
import os
import secrets
from os.path import join

from cryptography.fernet import Fernet, InvalidToken
from diskcache import Cache

from podimo.config import CACHE_DIR, PODIMO_ENCRYPTION_KEY

feed_store = Cache(join(CACHE_DIR, "feed_tokens"))


def _load_key() -> bytes:
    if PODIMO_ENCRYPTION_KEY:
        return PODIMO_ENCRYPTION_KEY.encode("utf-8")

    key_file = join(CACHE_DIR, "feed_tokens.key")
    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            return f.read()

    key = Fernet.generate_key()
    # 0600 and O_EXCL: only the service user can read the key, and a race
    # between two workers cannot silently truncate it
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


_fernet = Fernet(_load_key())


def create_feed_token(email: str, password: str, region: str, locale: str, podcast_id: str) -> str:
    payload = json.dumps(
        {
            "email": email,
            "password": password,
            "region": region,
            "locale": locale,
            "podcast_id": podcast_id,
        }
    ).encode("utf-8")
    token = secrets.token_urlsafe(24)
    feed_store[token] = _fernet.encrypt(payload)
    return token


def resolve_feed_token(token: str) -> dict | None:
    blob = feed_store.get(token)
    if blob is None:
        return None
    try:
        return json.loads(_fernet.decrypt(blob))
    except InvalidToken:
        logging.error("Could not decrypt a stored feed entry. Was the encryption key changed?")
        return None
