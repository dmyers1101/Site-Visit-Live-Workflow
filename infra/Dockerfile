FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

ENTRYPOINT ["site-visit"]

# How to update this later: pin base-image digests and dependency versions only
# after offline tests and an image vulnerability review pass.
