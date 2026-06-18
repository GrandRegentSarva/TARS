"""
Phase 9 Configuration Tests
=============================
Tests for evaluation configuration and weight validation.
"""

from __future__ import annotations

import pytest

from tars.phase9.config import Settings


class TestSettings:
    """Test configuration loading and validation."""

    def test_default_settings(self):
        """Default settings should be valid."""
        s = Settings()
        s.validate_weights()  # Should not raise

    def test_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        s = Settings()
        total = (
            s.EVALUATION_ROOT_CAUSE_WEIGHT
            + s.EVALUATION_RECOMMENDATION_WEIGHT
            + s.EVALUATION_CONSISTENCY_WEIGHT
            + s.EVALUATION_FALSE_POSITIVE_WEIGHT
            + s.EVALUATION_FALSE_NEGATIVE_WEIGHT
        )
        assert abs(total - 1.0) < 0.01

    def test_invalid_weight_sum_rejected(self):
        """Weights that don't sum to 1.0 should be rejected."""
        s = Settings()
        s.EVALUATION_ROOT_CAUSE_WEIGHT = 0.5
        s.EVALUATION_RECOMMENDATION_WEIGHT = 0.5
        s.EVALUATION_CONSISTENCY_WEIGHT = 0.5
        with pytest.raises(ValueError, match="must sum to 1.0"):
            s.validate_weights()

    def test_negative_weight_rejected(self):
        """Negative weights should be rejected."""
        s = Settings()
        s.EVALUATION_ROOT_CAUSE_WEIGHT = -0.1
        with pytest.raises(ValueError, match="must be between"):
            s.validate_weights()

    def test_weight_over_one_rejected(self):
        """Weights over 1.0 should be rejected."""
        s = Settings()
        s.EVALUATION_ROOT_CAUSE_WEIGHT = 1.5
        with pytest.raises(ValueError, match="must be between"):
            s.validate_weights()

    def test_weight_config_property(self):
        """weight_config should return a dict with all weight keys."""
        s = Settings()
        config = s.weight_config
        assert "root_cause_accuracy" in config
        assert "recommendation_accuracy" in config
        assert "response_consistency" in config
        assert "false_positive_penalty" in config
        assert "false_negative_penalty" in config

    def test_default_evaluation_enabled(self):
        """Evaluation should be enabled by default."""
        s = Settings()
        assert s.EVALUATION_ENABLED is True

    def test_default_version(self):
        """Default evaluator version should be v1.0."""
        s = Settings()
        assert s.EVALUATION_VERSION == "v1.0"

    def test_default_batch_limit(self):
        """Default batch limit should be 50."""
        s = Settings()
        assert s.EVALUATION_BATCH_LIMIT == 50

    def test_default_consistency_min_cases(self):
        """Default consistency min cases should be 3."""
        s = Settings()
        assert s.EVALUATION_CONSISTENCY_MIN_CASES == 3

    def test_default_phoenix_export_disabled(self):
        """Phoenix export should be disabled by default."""
        s = Settings()
        assert s.EVALUATION_EXPORT_PHOENIX is False

    def test_default_operator_label_not_required(self):
        """Operator label should not be required by default."""
        s = Settings()
        assert s.EVALUATION_REQUIRE_OPERATOR_LABEL is False
