"""
Phase 10 Configuration
=======================
Environment-based settings for the Learning Engine.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.

Validates that confidence scoring weights sum to 1.0 (within tolerance),
that all rates and weights are bounded [0.0, 1.0], and that batch/page
limits are positive.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 10 configuration loaded from environment variables."""

    # Feature flag
    LEARNING_ENABLED: bool = os.getenv(
        "LEARNING_ENABLED", "true"
    ).lower() in ("true", "1", "yes")

    # PostgreSQL connection
    LEARNING_DATABASE_URL: str = os.getenv(
        "LEARNING_DATABASE_URL",
        "postgresql+asyncpg://tars:tars@localhost:5432/tars",
    )

    # Learning version stamped on candidates
    LEARNING_VERSION: str = os.getenv("LEARNING_VERSION", "phase10.v1")

    # API server
    LEARNING_API_HOST: str = os.getenv("LEARNING_API_HOST", "0.0.0.0")
    LEARNING_API_PORT: int = int(os.getenv("LEARNING_API_PORT", "8007"))

    # Minimum thresholds for candidate generation
    LEARNING_MIN_EVALUATED_CASES: int = int(
        os.getenv("LEARNING_MIN_EVALUATED_CASES", "5")
    )
    LEARNING_MIN_DISTINCT_MISSIONS: int = int(
        os.getenv("LEARNING_MIN_DISTINCT_MISSIONS", "3")
    )
    LEARNING_MIN_CONFIDENCE: float = float(
        os.getenv("LEARNING_MIN_CONFIDENCE", "0.60")
    )
    LEARNING_MIN_SUCCESS_RATE: float = float(
        os.getenv("LEARNING_MIN_SUCCESS_RATE", "0.70")
    )
    LEARNING_MAX_FALSE_POSITIVE_RATE: float = float(
        os.getenv("LEARNING_MAX_FALSE_POSITIVE_RATE", "0.20")
    )

    # Batch and page limits
    LEARNING_BATCH_LIMIT: int = int(
        os.getenv("LEARNING_BATCH_LIMIT", "100")
    )
    LEARNING_EVIDENCE_PAGE_SIZE: int = int(
        os.getenv("LEARNING_EVIDENCE_PAGE_SIZE", "50")
    )

    # Minimum contradiction cases to flag as weak
    LEARNING_MIN_CONTRADICTION_WEAK: int = int(
        os.getenv("LEARNING_MIN_CONTRADICTION_WEAK", "2")
    )

    # Upstream API URLs
    PHASE9_API_URL: str = os.getenv(
        "PHASE9_API_URL", "http://localhost:8006"
    )
    PHASE7_API_URL: str = os.getenv(
        "PHASE7_API_URL", "http://localhost:8005"
    )
    PHOENIX_BASE_URL: str = os.getenv(
        "PHOENIX_BASE_URL", "http://localhost:6006"
    )

    # Optional trace metadata
    LEARNING_TRACE_METADATA_ENABLED: bool = os.getenv(
        "LEARNING_TRACE_METADATA_ENABLED", "false"
    ).lower() in ("true", "1", "yes")

    # HTTP client timeout for upstream API calls (seconds)
    LEARNING_CLIENT_TIMEOUT: float = float(
        os.getenv("LEARNING_CLIENT_TIMEOUT", "30.0")
    )

    # Maximum statement length
    MAX_STATEMENT_LENGTH: int = int(
        os.getenv("LEARNING_MAX_STATEMENT_LENGTH", "500")
    )

    # Confidence scoring weights
    SCORING_SUPPORT_WEIGHT: float = float(
        os.getenv("LEARNING_SCORING_SUPPORT_WEIGHT", "0.35")
    )
    SCORING_OUTCOME_WEIGHT: float = float(
        os.getenv("LEARNING_SCORING_OUTCOME_WEIGHT", "0.25")
    )
    SCORING_EVALUATION_WEIGHT: float = float(
        os.getenv("LEARNING_SCORING_EVALUATION_WEIGHT", "0.20")
    )
    SCORING_DIVERSITY_WEIGHT: float = float(
        os.getenv("LEARNING_SCORING_DIVERSITY_WEIGHT", "0.10")
    )
    SCORING_CONTRADICTION_WEIGHT: float = float(
        os.getenv("LEARNING_SCORING_CONTRADICTION_WEIGHT", "0.10")
    )

    def validate(self) -> None:
        """
        Validate all configuration constraints.

        Raises:
            ValueError: If any constraint is violated.
        """
        self._validate_positive_counts()
        self._validate_bounded_rates()
        self._validate_scoring_weights()

    def _validate_positive_counts(self) -> None:
        """Ensure minimum counts and limits are positive."""
        checks = [
            ("LEARNING_MIN_EVALUATED_CASES", self.LEARNING_MIN_EVALUATED_CASES),
            ("LEARNING_MIN_DISTINCT_MISSIONS", self.LEARNING_MIN_DISTINCT_MISSIONS),
            ("LEARNING_BATCH_LIMIT", self.LEARNING_BATCH_LIMIT),
            ("LEARNING_EVIDENCE_PAGE_SIZE", self.LEARNING_EVIDENCE_PAGE_SIZE),
            ("LEARNING_MIN_CONTRADICTION_WEAK", self.LEARNING_MIN_CONTRADICTION_WEAK),
        ]
        for name, value in checks:
            if value < 1:
                raise ValueError(
                    f"{name} is {value}; must be >= 1"
                )

    def _validate_bounded_rates(self) -> None:
        """Ensure all rates are bounded [0.0, 1.0]."""
        checks = [
            ("LEARNING_MIN_CONFIDENCE", self.LEARNING_MIN_CONFIDENCE),
            ("LEARNING_MIN_SUCCESS_RATE", self.LEARNING_MIN_SUCCESS_RATE),
            ("LEARNING_MAX_FALSE_POSITIVE_RATE", self.LEARNING_MAX_FALSE_POSITIVE_RATE),
        ]
        for name, value in checks:
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"{name} is {value}; must be between 0.0 and 1.0"
                )

    def _validate_scoring_weights(self) -> None:
        """Validate that scoring weights are bounded and sum to 1.0."""
        weights = [
            ("SCORING_SUPPORT_WEIGHT", self.SCORING_SUPPORT_WEIGHT),
            ("SCORING_OUTCOME_WEIGHT", self.SCORING_OUTCOME_WEIGHT),
            ("SCORING_EVALUATION_WEIGHT", self.SCORING_EVALUATION_WEIGHT),
            ("SCORING_DIVERSITY_WEIGHT", self.SCORING_DIVERSITY_WEIGHT),
            ("SCORING_CONTRADICTION_WEIGHT", self.SCORING_CONTRADICTION_WEIGHT),
        ]

        for name, w in weights:
            if w < 0.0 or w > 1.0:
                raise ValueError(
                    f"{name} is {w}; must be between 0.0 and 1.0"
                )

        total = sum(w for _, w in weights)
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Scoring weights sum to {total}; must sum to 1.0 "
                f"(tolerance ±0.01)"
            )

    @property
    def scoring_weights(self) -> dict[str, float]:
        """Return scoring weights as a dict."""
        return {
            "support_strength": self.SCORING_SUPPORT_WEIGHT,
            "outcome_strength": self.SCORING_OUTCOME_WEIGHT,
            "evaluation_quality": self.SCORING_EVALUATION_WEIGHT,
            "evidence_diversity": self.SCORING_DIVERSITY_WEIGHT,
            "contradiction_penalty_adjusted": self.SCORING_CONTRADICTION_WEIGHT,
        }


settings = Settings()
