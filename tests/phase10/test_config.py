"""
Phase 10 Configuration Tests
==============================
Tests for defaults, env overrides, weight validation, and bounded limits.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from tars.phase10.config import Settings


class TestDefaults:
    """Test default configuration values."""

    def test_learning_enabled_default(self):
        s = Settings()
        assert s.LEARNING_ENABLED is True

    def test_learning_version_default(self):
        s = Settings()
        assert s.LEARNING_VERSION == "phase10.v1"

    def test_min_evaluated_cases_default(self):
        s = Settings()
        assert s.LEARNING_MIN_EVALUATED_CASES == 5

    def test_min_distinct_missions_default(self):
        s = Settings()
        assert s.LEARNING_MIN_DISTINCT_MISSIONS == 3

    def test_min_confidence_default(self):
        s = Settings()
        assert s.LEARNING_MIN_CONFIDENCE == 0.60

    def test_min_success_rate_default(self):
        s = Settings()
        assert s.LEARNING_MIN_SUCCESS_RATE == 0.70

    def test_max_false_positive_rate_default(self):
        s = Settings()
        assert s.LEARNING_MAX_FALSE_POSITIVE_RATE == 0.20

    def test_batch_limit_default(self):
        s = Settings()
        assert s.LEARNING_BATCH_LIMIT == 100

    def test_evidence_page_size_default(self):
        s = Settings()
        assert s.LEARNING_EVIDENCE_PAGE_SIZE == 50

    def test_api_port_default(self):
        s = Settings()
        assert s.LEARNING_API_PORT == 8007


class TestScoringWeights:
    """Test scoring weight validation."""

    def test_default_weights_sum_to_one(self):
        s = Settings()
        s.validate()  # Should not raise

    def test_weights_property(self):
        s = Settings()
        weights = s.scoring_weights
        assert "support_strength" in weights
        assert "outcome_strength" in weights
        assert "evaluation_quality" in weights
        assert "evidence_diversity" in weights
        assert "contradiction_penalty_adjusted" in weights
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_invalid_weight_sum_raises(self):
        s = Settings()
        s.SCORING_SUPPORT_WEIGHT = 0.50
        s.SCORING_OUTCOME_WEIGHT = 0.50
        # Sum is now > 1.0
        with pytest.raises(ValueError, match="sum to"):
            s.validate()

    def test_negative_weight_raises(self):
        s = Settings()
        s.SCORING_SUPPORT_WEIGHT = -0.1
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()

    def test_weight_above_one_raises(self):
        s = Settings()
        s.SCORING_SUPPORT_WEIGHT = 1.5
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()


class TestBoundedLimits:
    """Test bounded limit validation."""

    def test_zero_min_cases_raises(self):
        s = Settings()
        s.LEARNING_MIN_EVALUATED_CASES = 0
        with pytest.raises(ValueError, match="must be >= 1"):
            s.validate()

    def test_zero_batch_limit_raises(self):
        s = Settings()
        s.LEARNING_BATCH_LIMIT = 0
        with pytest.raises(ValueError, match="must be >= 1"):
            s.validate()

    def test_negative_min_missions_raises(self):
        s = Settings()
        s.LEARNING_MIN_DISTINCT_MISSIONS = -1
        with pytest.raises(ValueError, match="must be >= 1"):
            s.validate()


class TestBoundedRates:
    """Test bounded rate validation."""

    def test_confidence_above_one_raises(self):
        s = Settings()
        s.LEARNING_MIN_CONFIDENCE = 1.5
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()

    def test_confidence_below_zero_raises(self):
        s = Settings()
        s.LEARNING_MIN_CONFIDENCE = -0.1
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()

    def test_success_rate_above_one_raises(self):
        s = Settings()
        s.LEARNING_MIN_SUCCESS_RATE = 1.1
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()

    def test_false_positive_rate_below_zero_raises(self):
        s = Settings()
        s.LEARNING_MAX_FALSE_POSITIVE_RATE = -0.01
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            s.validate()
