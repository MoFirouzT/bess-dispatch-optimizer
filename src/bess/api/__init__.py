"""api — FastAPI + Pydantic wrapper with graceful-degradation circuit breaker.
Top layer. (R1.5)

- ``app`` — FastAPI app (``POST /dispatch``, ``GET /health``).
- ``service`` — the circuit breaker (``dispatch``), pure and testable.
- ``models`` — request/response schemas.
"""
