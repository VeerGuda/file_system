"""
models/recommendation.py

Standardized data model for diagnostic findings and cleanup recommendations.
"""

SEVERITY_ORDER = {
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1
}

VALID_CATEGORIES = {"performance", "cleanup", "security", "startup"}
VALID_SEVERITIES = {"high", "medium", "low", "info"}


def create_recommendation(
    rec_id,
    category,
    severity,
    title,
    reason,
    description=None,
    target=None,
    action=None,
    reclaimable_bytes=0,
    reversible=True
):
    """
    Creates a standardized recommendation dictionary.

    Args:
        rec_id (str): Unique identifier for the recommendation.
        category (str): One of 'performance', 'cleanup', 'security', 'startup'.
        severity (str): One of 'high', 'medium', 'low', 'info'.
        title (str): Concise human-readable title.
        reason (str): Why this recommendation was triggered.
        description (str, optional): Additional contextual details.
        target (str, optional): File path, PID, bundle ID, or service label.
        action (str, optional): Recommended safe action (e.g. 'move_to_trash', 'review_file').
        reclaimable_bytes (int): Estimated disk space that could be freed.
        reversible (bool): Whether the recommended action can be undone.

    Returns:
        dict: Standardized recommendation object.
    """
    cat = category.lower() if category.lower() in VALID_CATEGORIES else "cleanup"
    sev = severity.lower() if severity.lower() in VALID_SEVERITIES else "info"

    reclaimable_mb = round(reclaimable_bytes / (1024 ** 2), 2) if reclaimable_bytes > 0 else 0.0
    reclaimable_gb = round(reclaimable_bytes / (1024 ** 3), 2) if reclaimable_bytes > 0 else 0.0

    return {
        "id": rec_id,
        "category": cat,
        "severity": sev,
        "title": title,
        "reason": reason,
        "description": description or reason,
        "target": target,
        "action": action,
        "reclaimable_bytes": reclaimable_bytes,
        "reclaimable_mb": reclaimable_mb,
        "reclaimable_gb": reclaimable_gb,
        "reversible": reversible
    }


def sort_recommendations(recommendations):
    """
    Sorts recommendations by severity descending, then by reclaimable space descending.
    """
    return sorted(
        recommendations,
        key=lambda r: (
            SEVERITY_ORDER.get(r["severity"], 0),
            r.get("reclaimable_bytes", 0)
        ),
        reverse=True
    )


def filter_by_category(recommendations, category):
    """Filters recommendations by category."""
    return [r for r in recommendations if r["category"] == category]


def filter_by_severity(recommendations, severity):
    """Filters recommendations by severity."""
    return [r for r in recommendations if r["severity"] == severity]
