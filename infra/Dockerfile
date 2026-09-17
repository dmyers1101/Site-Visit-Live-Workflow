FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# The versioned prompt files are read from disk at runtime by extraction.py.
# They are part of the runtime contract, not build-time input, so they must
# ship in the image. Without this the deployed job cannot run L1/L2/L3.
COPY prompts ./prompts

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

ENTRYPOINT ["site-visit"]

# How to update this later: pin base-image digests and dependency versions only
# after offline tests and an image vulnerability review pass.
