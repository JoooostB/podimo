import os
import tempfile

# podimo.config reads the environment at import time and creates the cache
# directory, so point it at a throwaway location before anything imports it.
os.environ.setdefault("CACHE_DIR", tempfile.mkdtemp(prefix="podimo-test-cache-"))
