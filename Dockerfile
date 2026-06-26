# Dispatch service image (R1.5). Single synchronous FastAPI app over the solver,
# with the graceful-degradation circuit breaker. No K8s, no compose (spec scope).
FROM python:3.13-slim

# uv for reproducible, locked installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    BESS_LATENCY_BUDGET_S=2.0

# Install runtime deps only (no dev group); build the package from src.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000
# Serve. /health is the liveness + solver-availability probe (CI build smoke).
CMD ["uv", "run", "--no-dev", "uvicorn", "bess.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
