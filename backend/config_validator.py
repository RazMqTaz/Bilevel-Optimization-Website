"""
config_validator.py

Validation layer for user-submitted SACE optimization configs.
Called in the FastAPI endpoint BEFORE anything is persisted or dispatched.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional


# ── Whitelists (must mirror SACE factory dicts exactly) ─────────────────
ALLOWED_PROBLEMS = frozenset({
    "smd1", "smd2", "smd3", "smd4", "smd5", "smd6",
    "smd7", "smd8", "smd9", "smd10", "smd11", "smd12",
    "sp1", "sp2",
    "sa1",
    "hyper_representation",
})

ALLOWED_ALGORITHMS = frozenset({
    "nestedde",
    "biga_lazy", "biga_aggressive",
    "sace_es", "sace_es_independent", "sace_es_mogp", "sace_es_heteroscedastic",
    "kktsolver",
    "bboa_kkt",
    "gbsa",
    "sace_pso",
})

# ── Limits ──────────────────────────────────────────────────────────────
MAX_INDEPENDENT_RUNS = 50
MAX_PROBLEMS = 10
MAX_ALGORITHMS = 5
MAX_TOTAL_RUNS = 500
MAX_CONFIG_SIZE_BYTES = 64 * 1024  # 64 KB


# ── Param schemas (extra="allow" lets unknown keys pass through to SACE) ─
class ProblemParams(BaseModel):
    """Whitelisted problem constructor kwargs with safe ranges."""
    # SMD suite
    ul_dim: Optional[int] = Field(None, ge=1, le=100)
    ll_dim: Optional[int] = Field(None, ge=1, le=100)
    p: Optional[int] = Field(None, ge=1, le=50)
    q: Optional[int] = Field(None, ge=1, le=50)
    r: Optional[int] = Field(None, ge=1, le=50)
    # Synthetic suite (SP1, SP2)
    n_dim: Optional[int] = Field(None, ge=1, le=200)
    # Hyper-representation suite
    n: Optional[int] = Field(None, ge=1, le=1000)
    m: Optional[int] = Field(None, ge=1, le=100)

    class Config:
        extra = "allow"


class AlgorithmParams(BaseModel):
    """Whitelisted algorithm constructor kwargs with safe ranges."""
    ul_pop_size: Optional[int] = Field(None, ge=2, le=500)
    ll_pop_size: Optional[int] = Field(None, ge=2, le=500)
    generations: Optional[int] = Field(None, ge=1, le=10_000)
    ul_max_nfe: Optional[int] = Field(None, ge=1, le=500_000)
    ll_max_nfe: Optional[int] = Field(None, ge=1, le=500_000)
    surrogate_type: Optional[str] = Field(None, pattern=r"^(gp|rbf|kriging)$")
    strategy: Optional[str] = Field(None, pattern=r"^(lazy|aggressive)$")

    class Config:
        extra = "allow"


# ── Top-level schemas ──────────────────────────────────────────────────
class ProblemConfig(BaseModel):
    name: str
    params: Optional[ProblemParams] = ProblemParams()

    @field_validator("name")
    @classmethod
    def name_must_be_allowed(cls, v: str) -> str:
        if v.lower() not in ALLOWED_PROBLEMS:
            raise ValueError(
                f"Unknown problem '{v}'. Allowed: {sorted(ALLOWED_PROBLEMS)}"
            )
        return v


class AlgorithmConfig(BaseModel):
    name: str
    params: Optional[AlgorithmParams] = AlgorithmParams()

    @field_validator("name")
    @classmethod
    def name_must_be_allowed(cls, v: str) -> str:
        if v.lower() not in ALLOWED_ALGORITHMS:
            raise ValueError(
                f"Unknown algorithm '{v}'. Allowed: {sorted(ALLOWED_ALGORITHMS)}"
            )
        return v


class ExperimentSettings(BaseModel):
    independent_runs: int = Field(default=30, ge=1, le=MAX_INDEPENDENT_RUNS)
    seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)

    class Config:
        extra = "forbid"


class BatchConfig(BaseModel):
    experiment_name: str = Field(
        max_length=128,
        pattern=r"^[a-zA-Z0-9_\- ]+$",
    )
    settings: ExperimentSettings = ExperimentSettings()
    problems: list[ProblemConfig] = Field(min_length=1, max_length=MAX_PROBLEMS)
    algorithms: list[AlgorithmConfig] = Field(min_length=1, max_length=MAX_ALGORITHMS)

    class Config:
        extra = "forbid"

    @model_validator(mode="after")
    def cap_total_work(self):
        total = (
            len(self.problems)
            * len(self.algorithms)
            * self.settings.independent_runs
        )
        if total > MAX_TOTAL_RUNS:
            raise ValueError(
                f"Total scheduled runs ({total}) exceeds the {MAX_TOTAL_RUNS}-run "
                "safety cap. Reduce problems, algorithms, or independent_runs."
            )
        return self


# ── Public API ──────────────────────────────────────────────────────────
class ConfigValidationError(Exception):
    """Raised when a user-submitted config fails validation."""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def validate_config(raw_dict: dict) -> dict:
    """
    Validate a config dict and return a sanitised copy.

    Accepts the dict extracted from the user's JSON payload (i.e. the
    ``submission_data`` level, NOT the outer ``{"data": ...}`` wrapper).

    Returns a clean dict containing only whitelisted fields — safe to
    persist in the DB and dispatch to Celery/SACE.

    Raises ConfigValidationError with a user-friendly message on failure.
    """
    import json

    # 1. Size gate — serialise to check byte length before heavy validation
    try:
        raw_json = json.dumps(raw_dict)
    except (TypeError, ValueError) as e:
        raise ConfigValidationError(f"Payload is not valid JSON: {e}")

    if len(raw_json.encode()) > MAX_CONFIG_SIZE_BYTES:
        raise ConfigValidationError(
            f"Config too large. Maximum is {MAX_CONFIG_SIZE_BYTES} bytes."
        )

    # 2. Parse + validate via Pydantic
    try:
        config = BatchConfig.model_validate(raw_dict)
    except Exception as e:
        raise ConfigValidationError(f"Invalid config: {e}") from e

    # 3. Return validated dict — only whitelisted fields survive
    return config.model_dump()