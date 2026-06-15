FROM python:3.15.0b2-alpine

# Install supercronic v0.2.46 — a container-native cron runner that propagates the
# container environment to jobs natively, logs stdout/stderr to docker logs, and
# uses standard crontab syntax.
# Update the version string and sha1sums for the corresponding release when upgrading.
# Latest releases: https://github.com/aptible/supercronic/releases
ARG TARGETARCH
RUN set -e; \
    case "$TARGETARCH" in \
        amd64) sha1sum="5bcefed628e32adc08e32634db2d10e9230dbca0" ;; \
        arm64) sha1sum="639ab81a72771990790df7ee87d9acfe88e5fa83" ;; \
        *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    wget -qO /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/v0.2.46/supercronic-linux-${TARGETARCH}"; \
    echo "${sha1sum}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic

# rndc is needed to trigger DNS zone reloads in the bind container after zone file changes.
# Running as root is required: the generatedzones shared volume is initialised by the
# bind container (also root), so the sync container must also run as root to write zone files.
RUN apk add --no-cache bind

COPY rndc.conf /etc/bind/rndc.conf

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# VERSION must come after the expensive layers above so a new deploy tag does not
# bust the supercronic/apk/pip cache.
ARG VERSION
ENV VERSION=$VERSION

COPY crontab /crontab
COPY config-sync.py .
COPY templates ./templates

CMD ["supercronic", "/crontab"]
