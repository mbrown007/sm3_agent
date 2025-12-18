"""
Anomaly detection engine for metrics and logs.

Provides multiple detection methods: statistical, pattern-based, and ML-based.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Anomaly:
    """Represents a detected anomaly."""

    timestamp: datetime
    metric_name: str
    value: float
    expected_value: float
    deviation: float
    severity: str  # low, medium, high, critical
    method: str  # detection method used
    context: Dict[str, Any]
    confidence: float  # 0-1


@dataclass
class TimeSeriesPoint:
    """Single time series data point."""

    timestamp: datetime
    value: float


class AnomalyDetector:
    """
    Multi-method anomaly detection for time series data.

    Supports:
    - Statistical methods (Z-score, IQR, MAD)
    - Rate of change detection
    - Threshold-based detection
    - Pattern matching
    """

    def __init__(self):
        self.logger = logger

    def detect_anomalies(
        self,
        data: List[TimeSeriesPoint],
        metric_name: str,
        methods: List[str] = None
    ) -> List[Anomaly]:
        """
        Detect anomalies using multiple methods.

        Args:
            data: Time series data points
            metric_name: Name of the metric being analyzed
            methods: List of detection methods to use (default: all)

        Returns:
            List of detected anomalies
        """
        if not data or len(data) < 3:
            logger.warning(f"Insufficient data for anomaly detection: {len(data) if data else 0} points")
            return []

        if methods is None:
            methods = ["zscore", "iqr", "rate_change"]

        all_anomalies = []

        # Apply each detection method
        if "zscore" in methods:
            all_anomalies.extend(self._detect_zscore(data, metric_name))

        if "iqr" in methods:
            all_anomalies.extend(self._detect_iqr(data, metric_name))

        if "mad" in methods:
            all_anomalies.extend(self._detect_mad(data, metric_name))

        if "rate_change" in methods:
            all_anomalies.extend(self._detect_rate_change(data, metric_name))

        # Deduplicate and sort by severity
        all_anomalies = self._deduplicate_anomalies(all_anomalies)
        all_anomalies.sort(key=lambda a: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[a.severity],
            -a.confidence
        ))

        logger.info(f"Detected {len(all_anomalies)} anomalies in {metric_name}")
        return all_anomalies

    def _detect_zscore(
        self,
        data: List[TimeSeriesPoint],
        metric_name: str,
        threshold: float = 3.0
    ) -> List[Anomaly]:
        """
        Detect anomalies using Z-score method.

        Points beyond threshold standard deviations are anomalies.
        """
        anomalies = []
        values = [p.value for p in data]

        if len(values) < 3:
            return anomalies

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)

        if stdev == 0:
            return anomalies

        for point in data:
            z_score = abs((point.value - mean) / stdev)

            if z_score > threshold:
                severity = self._calculate_severity(z_score, threshold, threshold * 2)
                confidence = min(z_score / (threshold * 3), 1.0)

                anomalies.append(Anomaly(
                    timestamp=point.timestamp,
                    metric_name=metric_name,
                    value=point.value,
                    expected_value=mean,
                    deviation=point.value - mean,
                    severity=severity,
                    method="zscore",
                    context={
                        "z_score": z_score,
                        "mean": mean,
                        "stdev": stdev,
                        "threshold": threshold
                    },
                    confidence=confidence
                ))

        return anomalies

    def _detect_iqr(
        self,
        data: List[TimeSeriesPoint],
        metric_name: str,
        multiplier: float = 1.5
    ) -> List[Anomaly]:
        """
        Detect anomalies using Interquartile Range (IQR) method.

        More robust to outliers than Z-score.
        """
        anomalies = []
        values = sorted([p.value for p in data])

        if len(values) < 4:
            return anomalies

        # Calculate quartiles
        q1_idx = len(values) // 4
        q3_idx = (3 * len(values)) // 4
        q1 = values[q1_idx]
        q3 = values[q3_idx]
        iqr = q3 - q1

        if iqr == 0:
            return anomalies

        lower_bound = q1 - (multiplier * iqr)
        upper_bound = q3 + (multiplier * iqr)

        median = statistics.median(values)

        for point in data:
            if point.value < lower_bound or point.value > upper_bound:
                # Calculate how far beyond bounds
                if point.value < lower_bound:
                    distance = lower_bound - point.value
                    expected = lower_bound
                else:
                    distance = point.value - upper_bound
                    expected = upper_bound

                severity = self._calculate_severity(
                    distance / iqr if iqr > 0 else 0,
                    multiplier,
                    multiplier * 2
                )

                confidence = min(distance / (iqr * 3), 1.0)

                anomalies.append(Anomaly(
                    timestamp=point.timestamp,
                    metric_name=metric_name,
                    value=point.value,
                    expected_value=expected,
                    deviation=point.value - median,
                    severity=severity,
                    method="iqr",
                    context={
                        "q1": q1,
                        "q3": q3,
                        "iqr": iqr,
                        "lower_bound": lower_bound,
                        "upper_bound": upper_bound
                    },
                    confidence=confidence
                ))

        return anomalies

    def _detect_mad(
        self,
        data: List[TimeSeriesPoint],
        metric_name: str,
        threshold: float = 3.5
    ) -> List[Anomaly]:
        """
        Detect anomalies using Median Absolute Deviation (MAD).

        Very robust to outliers.
        """
        anomalies = []
        values = [p.value for p in data]

        if len(values) < 3:
            return anomalies

        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations)

        if mad == 0:
            # Use mean absolute deviation as fallback
            mad = statistics.mean(deviations)
            if mad == 0:
                return anomalies

        for point in data:
            modified_z_score = 0.6745 * abs(point.value - median) / mad

            if modified_z_score > threshold:
                severity = self._calculate_severity(
                    modified_z_score,
                    threshold,
                    threshold * 2
                )

                confidence = min(modified_z_score / (threshold * 2), 1.0)

                anomalies.append(Anomaly(
                    timestamp=point.timestamp,
                    metric_name=metric_name,
                    value=point.value,
                    expected_value=median,
                    deviation=point.value - median,
                    severity=severity,
                    method="mad",
                    context={
                        "modified_z_score": modified_z_score,
                        "median": median,
                        "mad": mad,
                        "threshold": threshold
                    },
                    confidence=confidence
                ))

        return anomalies

    def _detect_rate_change(
        self,
        data: List[TimeSeriesPoint],
        metric_name: str,
        threshold: float = 0.5
    ) -> List[Anomaly]:
        """
        Detect anomalies based on rate of change.

        Catches sudden spikes or drops.
        """
        anomalies = []

        if len(data) < 2:
            return anomalies

        # Calculate rate of change between consecutive points
        for i in range(1, len(data)):
            prev_point = data[i - 1]
            curr_point = data[i]

            if prev_point.value == 0:
                continue

            # Percent change
            pct_change = abs((curr_point.value - prev_point.value) / prev_point.value)

            if pct_change > threshold:
                severity = self._calculate_severity(pct_change, threshold, threshold * 3)
                confidence = min(pct_change / (threshold * 5), 1.0)

                anomalies.append(Anomaly(
                    timestamp=curr_point.timestamp,
                    metric_name=metric_name,
                    value=curr_point.value,
                    expected_value=prev_point.value,
                    deviation=curr_point.value - prev_point.value,
                    severity=severity,
                    method="rate_change",
                    context={
                        "percent_change": pct_change * 100,
                        "previous_value": prev_point.value,
                        "threshold": threshold * 100
                    },
                    confidence=confidence
                ))

        return anomalies

    def _calculate_severity(
        self,
        score: float,
        medium_threshold: float,
        high_threshold: float
    ) -> str:
        """Calculate severity level based on score."""
        if score > high_threshold * 1.5:
            return "critical"
        elif score > high_threshold:
            return "high"
        elif score > medium_threshold:
            return "medium"
        else:
            return "low"

    def _deduplicate_anomalies(self, anomalies: List[Anomaly]) -> List[Anomaly]:
        """
        Remove duplicate anomalies detected by multiple methods.

        Keeps the one with highest confidence.
        """
        if not anomalies:
            return []

        # Group by timestamp
        grouped: Dict[datetime, List[Anomaly]] = {}
        for anomaly in anomalies:
            if anomaly.timestamp not in grouped:
                grouped[anomaly.timestamp] = []
            grouped[anomaly.timestamp].append(anomaly)

        # Keep best anomaly for each timestamp
        deduplicated = []
        for timestamp, group in grouped.items():
            # Sort by confidence and severity
            best = max(group, key=lambda a: (
                a.confidence,
                {"critical": 4, "high": 3, "medium": 2, "low": 1}[a.severity]
            ))
            deduplicated.append(best)

        return deduplicated

    def analyze_metric(
        self,
        metric_name: str,
        query: str,
        time_range: str = "1h",
        methods: List[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze a Prometheus/Loki metric for anomalies.

        Args:
            metric_name: Name of the metric
            query: PromQL or LogQL query
            time_range: Time range to analyze (e.g., "1h", "24h")
            methods: Detection methods to use

        Returns:
            Analysis results with anomalies and recommendations
        """
        # This would integrate with the MCP client to fetch data
        # For now, return structure
        return {
            "metric_name": metric_name,
            "query": query,
            "time_range": time_range,
            "anomalies": [],
            "summary": {
                "total_points": 0,
                "anomalies_detected": 0,
                "severity_breakdown": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0
                }
            },
            "recommendations": []
        }


class PatternDetector:
    """Detect patterns in time series data."""

    def detect_trends(self, data: List[TimeSeriesPoint]) -> Dict[str, Any]:
        """
        Detect trends in time series.

        Returns:
            Trend information (increasing, decreasing, stable)
        """
        if len(data) < 3:
            return {"trend": "unknown", "confidence": 0}

        values = [p.value for p in data]

        # Simple linear regression
        n = len(values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator

        # Determine trend
        if abs(slope) < 0.01:
            trend = "stable"
        elif slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        # Calculate confidence based on R-squared
        y_pred = [slope * xi + (y_mean - slope * x_mean) for xi in x]
        ss_tot = sum((values[i] - y_mean) ** 2 for i in range(n))
        ss_res = sum((values[i] - y_pred[i]) ** 2 for i in range(n))

        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        return {
            "trend": trend,
            "slope": slope,
            "confidence": max(0, min(1, r_squared))
        }

    def detect_seasonality(self, data: List[TimeSeriesPoint]) -> Dict[str, Any]:
        """
        Detect seasonality patterns.

        Returns:
            Seasonality information
        """
        # Simplified seasonality detection
        # Would use FFT or autocorrelation in production
        if len(data) < 24:  # Need at least 24 points
            return {"has_seasonality": False, "period": None}

        values = [p.value for p in data]

        # Check for repeating patterns
        # This is a simplified version
        return {
            "has_seasonality": False,
            "period": None,
            "confidence": 0
        }


# Global singleton
_anomaly_detector: Optional[AnomalyDetector] = None
_pattern_detector: Optional[PatternDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get or create global anomaly detector."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
        logger.info("Initialized anomaly detector")
    return _anomaly_detector


def get_pattern_detector() -> PatternDetector:
    """Get or create global pattern detector."""
    global _pattern_detector
    if _pattern_detector is None:
        _pattern_detector = PatternDetector()
        logger.info("Initialized pattern detector")
    return _pattern_detector
