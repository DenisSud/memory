FROM python:3.12-slim

WORKDIR /app

# The bundled server's dependencies, with mem0ai filtered out: the package comes
# from this repo (the fork), never from PyPI. PI-FORK.md explains why.
COPY server/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
 grep -v '^mem0ai' /tmp/requirements.txt > /tmp/requirements-fork.txt \
 && pip install -r /tmp/requirements-fork.txt

# This repo's own package: upstream mem0 plus our System One gates.
# Two copies on purpose: `COPY mem0/ /src/` would flatten the package directory
# into /src and the wheel would come out empty with no error.
COPY pyproject.toml README.md LICENSE /src/
COPY mem0/ /src/mem0/
RUN --mount=type=cache,target=/root/.cache/pip pip install /src && rm -rf /src

# Upstream's server, unchanged. Its standalone dashboard is excluded by the
# repository .dockerignore.
COPY server/ /app/

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
