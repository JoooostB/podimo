# Build stage: install dependencies into a virtualenv with uv.
# uv comes from PyPI rather than ghcr.io/astral-sh/uv so the build
# only depends on Docker Hub and PyPI.
FROM python:3.14-alpine AS builder

WORKDIR /src

RUN pip install --no-cache-dir uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/src/.venv

# Dependency layer first: cached until pyproject.toml or uv.lock changes.
# The app runs as `python main.py` from /src, so only the dependencies are
# installed, not the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .

# Runtime stage: just Python, the virtualenv and the application
FROM python:3.14-alpine

WORKDIR /src

COPY --from=builder /src /src

# Run as a fixed non-root user. Host-mounted cache directories need to be
# writable by UID 1000: chown -R 1000:1000 ./cache
RUN addgroup -g 1000 podimo && adduser -D -u 1000 -G podimo podimo \
    && mkdir -p /src/cache && chown -R podimo:podimo /src

USER podimo

ENV PATH="/src/.venv/bin:$PATH" \
    # Inside a container the server must bind beyond loopback to be reachable
    PODIMO_BIND_HOST="0.0.0.0:12104"

EXPOSE 12104

ENTRYPOINT ["python", "main.py"]
