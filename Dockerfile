# One image serves the frontend and runs the agent (`AGENTS.md` §3).
#
# There is no JavaScript toolchain here on purpose: the frontend has no build step (§5), so
# FE/ is copied in as-is and served by the same Python process. Node is used only to *check*
# the frontend, never to build or ship it.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so the vendor SDKs are re-resolved only when the package metadata or the
# core changes — not on every frontend tweak. src/ is here because the build backend reads it.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY backend ./backend
COPY FE ./FE

# Anything not copied above is also absent from the build context — see `.gcloudignore`.
RUN useradd --create-home --uid 1000 runner && chown -R runner:runner /app
USER runner

# Cloud Run injects $PORT. `exec` replaces the shell so uvicorn is PID 1 and gets the SIGTERM
# that ends a scale-to-zero instance cleanly.
CMD exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8080}
