"""
A/B Testing — create, track, and analyze split tests for titles,
thumbnails, ad copy, and CTAs.
"""
import math
import logging
from typing import Optional
import database as db

log = logging.getLogger("ab_testing")


def create_test(user_id: int, test_type: str, variants: list[dict],
                job_id: int = None) -> dict:
    """
    Create a new A/B test.

    Args:
        user_id: Owner user ID
        test_type: "title", "thumbnail", "ad_copy", "cta", "headline"
        variants: list of {"label": str, "content": str}
        job_id: Optional linked video job

    Returns: full test dict with variants
    """
    if len(variants) < 2:
        raise ValueError("A/B test requires at least 2 variants")

    test_id = db.create_ab_test(user_id, test_type, job_id)

    for v in variants:
        db.add_ab_variant(test_id, v["label"], v["content"])

    return db.get_ab_test(test_id)


def record_event(variant_id: str, event_type: str):
    """Record an impression, click, or conversion."""
    if event_type == "impression":
        db.record_ab_impression(variant_id)
    elif event_type == "click":
        db.record_ab_click(variant_id)
    elif event_type == "conversion":
        db.record_ab_conversion(variant_id)


def get_test_results(test_id: str) -> dict:
    """Get test with computed statistics."""
    test = db.get_ab_test(test_id)
    if not test:
        return None

    variants = test.get("variants", [])
    if len(variants) >= 2:
        # Compute statistical significance between top 2
        a = variants[0]
        b = variants[1]
        confidence = _compute_confidence(
            a.get("impressions", 0), a.get("clicks", 0),
            b.get("impressions", 0), b.get("clicks", 0),
        )
        for v in variants:
            v["confidence"] = round(confidence, 2) if v["id"] == a["id"] else 0

        test["is_significant"] = confidence >= 0.95
        test["recommended_winner"] = a["id"] if confidence >= 0.95 else None
    else:
        test["is_significant"] = False
        test["recommended_winner"] = None

    test["variants"] = variants
    return test


def auto_end_test(test_id: str, min_impressions: int = 100) -> Optional[str]:
    """
    Automatically end a test if we have statistical significance.
    Returns winner variant_id or None.
    """
    test = get_test_results(test_id)
    if not test or test["status"] != "running":
        return None

    variants = test.get("variants", [])
    total_impressions = sum(v.get("impressions", 0) for v in variants)

    if total_impressions < min_impressions:
        return None

    if test.get("is_significant"):
        winner = test["recommended_winner"]
        db.end_ab_test(test_id, winner)
        log.info("Auto-ended test %s, winner: %s", test_id, winner)
        return winner

    return None


def _compute_confidence(impressions_a: int, clicks_a: int,
                        impressions_b: int, clicks_b: int) -> float:
    """
    Compute statistical confidence using a two-proportion z-test.
    Returns confidence level (0.0 to 1.0).
    """
    if impressions_a < 10 or impressions_b < 10:
        return 0.0

    p_a = clicks_a / impressions_a
    p_b = clicks_b / impressions_b

    p_pool = (clicks_a + clicks_b) / (impressions_a + impressions_b)

    if p_pool == 0 or p_pool == 1:
        return 0.0

    se = math.sqrt(p_pool * (1 - p_pool) * (1/impressions_a + 1/impressions_b))

    if se == 0:
        return 0.0

    z = abs(p_a - p_b) / se

    # Approximate p-value from z-score using the standard normal CDF
    # Using the complementary error function approximation
    confidence = _norm_cdf(z)
    return confidence


def _norm_cdf(z: float) -> float:
    """Approximate the one-sided normal CDF for confidence."""
    # Abramowitz and Stegun approximation
    if z < 0:
        return 1 - _norm_cdf(-z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    p = d * math.exp(-z * z / 2.0) * (
        t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 +
        t * (-1.821255978 + t * 1.330274429))))
    )
    return 1.0 - p


def list_tests(user_id: int) -> list:
    """List all A/B tests for a user."""
    return db.get_ab_tests(user_id)


def end_test(test_id: str, winner_id: str = None):
    """Manually end a test, optionally specifying a winner."""
    db.end_ab_test(test_id, winner_id)
