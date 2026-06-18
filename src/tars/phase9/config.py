"""
Phase 9 Configuration
=====================
Environment-based settings for the Evaluation Layer.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.

Validates that scoring weights sum to 1.0 (within tolerance).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 9 configuration loaded from environment variables."""

    # Feature flag
    EVALUATION_ENABLED: bool = os.getenv(
        "EVALUATION_ENABLED", "true"
    ).lower() in ("true", "1", "yes")

    # PostgreSQL connection
    EVALUATION_DATABASE_URL: str = os.getenv(
        "EVALUATION_DATABASE_URL",
        "postgresql+asyncpg://tars:tars@localhost:5432/tars",
    )

    # Evaluator version stamped on results
    EVALUATION_VERSION: str = os.getenv("EVALUATION_VERSION", "v1.0")

    # API server
    EVALUATION_API_HOST: str = os.getenv("EVALUATION_API_HOST", "0.0.0.0")
    EVALUATION_API_PORT: int = int(os.getenv("EVALUATION_API_PORT", "8006"))

    # Batch limits
    EVALUATION_BATCH_LIMIT: int = int(
        os.getenv("EVALUATION_BATCH_LIMIT", "50")
    )

    # Consistency scoring
    EVALUATION_CONSISTENCY_MIN_CASES: int = int(
        os.getenv("EVALUATION_CONSISTENCY_MIN_CASES", "3")
    )
    EVALUATION_SIMILARITY_LIMIT: int = int(
        os.getenv("EVALUATION_SIMILARITY_LIMIT", "20")
    )

    # Phoenix export
    EVALUATION_EXPORT_PHOENIX: bool = os.getenv(
        "EVALUATION_EXPORT_PHOENIX", "false"
    ).lower() in ("true", "1", "yes")

    # Label requirements
    EVALUATION_REQUIRE_OPERATOR_LABEL: bool = os.getenv(
        "EVALUATION_REQUIRE_OPERATOR_LABEL", "false"
    ).lower() in ("true", "1", "yes")

    # Scoring weights
    EVALUATION_ROOT_CAUSE_WEIGHT: float = float(
        os.getenv("EVALUATION_ROOT_CAUSE_WEIGHT", "0.40")
    )
    EVALUATION_RECOMMENDATION_WEIGHT: float = float(
        os.getenv("EVALUATION_RECOMMENDATION_WEIGHT", "0.35")
    )
    EVALUATION_CONSISTENCY_WEIGHT: float = float(
        os.getenv("EVALUATION_CONSISTENCY_WEIGHT", "0.15")
    )
    EVALUATION_FALSE_POSITIVE_WEIGHT: float = float(
        os.getenv("EVALUATION_FALSE_POSITIVE_WEIGHT", "0.05")
    )
    EVALUATION_FALSE_NEGATIVE_WEIGHT: float = float(
        os.getenv("EVALUATION_FALSE_NEGATIVE_WEIGHT", "0.05")
    )

    # Upstream API URLs
    PHASE4_API_URL: str = os.getenv("PHASE4_API_URL", "http://localhost:8003")
    PHASE5_API_URL: str = os.getenv("PHASE5_API_URL", "http://localhost:8004")
    PHASE7_API_URL: str = os.getenv("PHASE7_API_URL", "http://localhost:8005")

    # HTTP client timeout for upstream API calls (seconds)
    EVALUATION_CLIENT_TIMEOUT: float = float(
        os.getenv("EVALUATION_CLIENT_TIMEOUT", "30.0")
    )

    # Phoenix endpoint (reuses Phase 6 settings)
    PHOENIX_ENDPOINT: str = os.getenv(
        "PHOENIX_ENDPOINT", "http://localhost:6006"
    )

    # Maximum explanation length
    MAX_EXPLANATION_LENGTH: int = int(
        os.getenv("EVALUATION_MAX_EXPLANATION_LENGTH", "2000")
    )

    def validate_weights(self) -> None:
        """
        Validate that scoring weights sum to 1.0 within tolerance.

        Raises:
            ValueError: If weights are invalid.
        """
        weights = [
            self.EVALUATION_ROOT_CAUSE_WEIGHT,
            self.EVALUATION_RECOMMENDATION_WEIGHT,
            self.EVALUATION_CONSISTENCY_WEIGHT,
            self.EVALUATION_FALSE_POSITIVE_WEIGHT,
            self.EVALUATION_FALSE_NEGATIVE_WEIGHT,
        ]

        for i, w in enumerate(weights):
            if w < 0.0 or w > 1.0:
                raise ValueError(
                    f"Scoring weight at index {i} is {w}; "
                    f"must be between 0.0 and 1.0"
                )

        total = sum(weights)
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Scoring weights sum to {total}; must sum to 1.0 "
                f"(tolerance ±0.01)"
            )

    @property
    def weight_config(self) -> dict[str, float]:
        """Return scoring weights as a dict."""
        return {
            "root_cause_accuracy": self.EVALUATION_ROOT_CAUSE_WEIGHT,
            "recommendation_accuracy": self.EVALUATION_RECOMMENDATION_WEIGHT,
            "response_consistency": self.EVALUATION_CONSISTENCY_WEIGHT,
            "false_positive_penalty": self.EVALUATION_FALSE_POSITIVE_WEIGHT,
            "false_negative_penalty": self.EVALUATION_FALSE_NEGATIVE_WEIGHT,
        }


settings = Settings()
