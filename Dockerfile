# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.9.25-python3.14-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

FROM ghcr.io/astral-sh/uv:0.9.25-python3.14-bookworm-slim AS runtime

ARG PORT=8000
ENV PATH="/app/.venv/bin:$PATH" \
    PORT=${PORT} \
    PYTHONUNBUFFERED=1 \
    GIT_SSH_COMMAND="ssh -i /run/secrets/deploy_key -o UserKnownHostsFile=/run/secrets/known_hosts -o StrictHostKeyChecking=yes"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        git \
        openssh-client \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin recall

WORKDIR /app
COPY --from=build --chown=recall:recall /app/.venv /app/.venv
COPY --from=build --chown=recall:recall /app/src /app/src
COPY --chown=recall:recall docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

USER recall
EXPOSE ${PORT}
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=3)"
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["recall", "serve"]
