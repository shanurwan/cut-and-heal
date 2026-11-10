# Controller image. The nodes under test and their shaper sidecars use the upstream DST image.
FROM python:3.12-slim

RUN useradd --uid 10001 --create-home cah
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# /proc/stat is read for host load; nothing else needs privileges. tar is used by `kubectl cp`.
USER 10001
ENTRYPOINT ["python", "-m", "cutandheal.controller"]
