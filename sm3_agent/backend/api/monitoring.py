"""
API endpoints for proactive monitoring and anomaly detection.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.proactive import (
    MonitoringTarget,
    ProactiveAlert,
    get_proactive_monitor
)
from backend.intelligence.anomaly import TimeSeriesPoint, get_anomaly_detector
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# Request/Response models
class MonitoringTargetCreate(BaseModel):
    """Request to create a monitoring target."""

    name: str = Field(..., description="Target name")
    query: str = Field(..., description="PromQL or LogQL query")
    datasource_uid: str = Field(..., description="Datasource UID")
    query_type: str = Field(..., description="Query type: prometheus or loki")
    check_interval: int = Field(300, description="Check interval in seconds")
    detection_methods: List[str] = Field(
        default=["zscore", "iqr"],
        description="Detection methods to use"
    )
    severity_threshold: str = Field("medium", description="Minimum severity to alert")
    enabled: bool = Field(True, description="Whether target is enabled")


class MonitoringTargetResponse(BaseModel):
    """Monitoring target response."""

    name: str
    query: str
    datasource_uid: str
    query_type: str
    check_interval: int
    detection_methods: List[str]
    severity_threshold: str
    enabled: bool
    last_check: Optional[datetime]


class AlertResponse(BaseModel):
    """Proactive alert response."""

    timestamp: datetime
    target_name: str
    anomaly_count: int
    severity: str
    acknowledged: bool
    summary: str


class MonitoringStatusResponse(BaseModel):
    """Monitoring system status."""

    running: bool
    targets_count: int
    enabled_targets: int
    total_alerts: int
    recent_alerts: int
    critical_alerts: int


class AnomalyDetectionRequest(BaseModel):
    """Request to analyze data for anomalies."""

    metric_name: str
    data_points: List[dict]  # {timestamp: str, value: float}
    methods: Optional[List[str]] = None


class AnomalyResponse(BaseModel):
    """Anomaly detection response."""

    timestamp: datetime
    value: float
    expected_value: float
    deviation: float
    severity: str
    method: str
    confidence: float


# Endpoints

@router.get("/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status():
    """
    Get proactive monitoring system status.

    Returns current status including number of targets, alerts, etc.
    """
    try:
        monitor = get_proactive_monitor()
        status = monitor.get_monitoring_status()
        return MonitoringStatusResponse(**status)
    except Exception as e:
        logger.error(f"Error getting monitoring status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_monitoring():
    """
    Start the proactive monitoring system.

    Begins continuous monitoring of configured targets.
    """
    try:
        monitor = get_proactive_monitor()
        await monitor.start()
        return {"status": "started", "message": "Proactive monitoring started"}
    except Exception as e:
        logger.error(f"Error starting monitoring: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_monitoring():
    """
    Stop the proactive monitoring system.

    Stops all monitoring checks.
    """
    try:
        monitor = get_proactive_monitor()
        await monitor.stop()
        return {"status": "stopped", "message": "Proactive monitoring stopped"}
    except Exception as e:
        logger.error(f"Error stopping monitoring: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/targets", response_model=List[MonitoringTargetResponse])
async def list_targets():
    """
    List all monitoring targets.

    Returns all configured monitoring targets.
    """
    try:
        monitor = get_proactive_monitor()
        targets = [
            MonitoringTargetResponse(
                name=t.name,
                query=t.query,
                datasource_uid=t.datasource_uid,
                query_type=t.query_type,
                check_interval=t.check_interval,
                detection_methods=t.detection_methods,
                severity_threshold=t.severity_threshold,
                enabled=t.enabled,
                last_check=t.last_check
            )
            for t in monitor.targets.values()
        ]
        return targets
    except Exception as e:
        logger.error(f"Error listing targets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/targets", response_model=MonitoringTargetResponse)
async def create_target(target: MonitoringTargetCreate):
    """
    Create a new monitoring target.

    Adds a new metric or log query to monitor for anomalies.
    """
    try:
        monitor = get_proactive_monitor()

        # Check if target already exists
        if target.name in monitor.targets:
            raise HTTPException(
                status_code=400,
                detail=f"Target '{target.name}' already exists"
            )

        # Create monitoring target
        monitoring_target = MonitoringTarget(
            name=target.name,
            query=target.query,
            datasource_uid=target.datasource_uid,
            query_type=target.query_type,
            check_interval=target.check_interval,
            detection_methods=target.detection_methods,
            severity_threshold=target.severity_threshold,
            enabled=target.enabled
        )

        monitor.add_target(monitoring_target)

        return MonitoringTargetResponse(
            name=monitoring_target.name,
            query=monitoring_target.query,
            datasource_uid=monitoring_target.datasource_uid,
            query_type=monitoring_target.query_type,
            check_interval=monitoring_target.check_interval,
            detection_methods=monitoring_target.detection_methods,
            severity_threshold=monitoring_target.severity_threshold,
            enabled=monitoring_target.enabled,
            last_check=monitoring_target.last_check
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/targets/{name}")
async def delete_target(name: str):
    """
    Delete a monitoring target.

    Removes a target from monitoring.
    """
    try:
        monitor = get_proactive_monitor()

        if name not in monitor.targets:
            raise HTTPException(status_code=404, detail=f"Target '{name}' not found")

        monitor.remove_target(name)
        return {"status": "deleted", "message": f"Target '{name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/targets/{name}/enable")
async def enable_target(name: str):
    """Enable a monitoring target."""
    try:
        monitor = get_proactive_monitor()

        if name not in monitor.targets:
            raise HTTPException(status_code=404, detail=f"Target '{name}' not found")

        monitor.targets[name].enabled = True
        return {"status": "enabled", "message": f"Target '{name}' enabled"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/targets/{name}/disable")
async def disable_target(name: str):
    """Disable a monitoring target."""
    try:
        monitor = get_proactive_monitor()

        if name not in monitor.targets:
            raise HTTPException(status_code=404, detail=f"Target '{name}' not found")

        monitor.targets[name].enabled = False
        return {"status": "disabled", "message": f"Target '{name}' disabled"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    minutes: int = 60,
    min_severity: str = "low",
    include_acknowledged: bool = False
):
    """
    Get recent proactive alerts.

    Args:
        minutes: Look back this many minutes
        min_severity: Minimum severity (low, medium, high, critical)
        include_acknowledged: Include acknowledged alerts
    """
    try:
        monitor = get_proactive_monitor()
        alerts = monitor.get_recent_alerts(minutes=minutes, min_severity=min_severity)

        if not include_acknowledged:
            alerts = [a for a in alerts if not a.acknowledged]

        return [
            AlertResponse(
                timestamp=alert.timestamp,
                target_name=alert.target.name,
                anomaly_count=len(alert.anomalies),
                severity=alert.severity,
                acknowledged=alert.acknowledged,
                summary=_format_alert_summary(alert)
            )
            for alert in alerts
        ]
    except Exception as e:
        logger.error(f"Error getting alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{target_name}/acknowledge")
async def acknowledge_alert(target_name: str):
    """
    Acknowledge an alert.

    Marks the most recent unacknowledged alert for a target as acknowledged.
    """
    try:
        monitor = get_proactive_monitor()

        # Find most recent unacknowledged alert for target
        for alert in reversed(monitor.alerts):
            if alert.target.name == target_name and not alert.acknowledged:
                monitor.acknowledge_alert(alert)
                return {
                    "status": "acknowledged",
                    "message": f"Alert for '{target_name}' acknowledged"
                }

        raise HTTPException(
            status_code=404,
            detail=f"No unacknowledged alerts found for '{target_name}'"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", response_model=List[AnomalyResponse])
async def analyze_data(request: AnomalyDetectionRequest):
    """
    Analyze time series data for anomalies.

    Allows ad-hoc anomaly detection on provided data.
    """
    try:
        detector = get_anomaly_detector()

        # Convert data points to TimeSeriesPoint objects
        time_series = [
            TimeSeriesPoint(
                timestamp=datetime.fromisoformat(point["timestamp"]),
                value=float(point["value"])
            )
            for point in request.data_points
        ]

        # Detect anomalies
        anomalies = detector.detect_anomalies(
            data=time_series,
            metric_name=request.metric_name,
            methods=request.methods
        )

        return [
            AnomalyResponse(
                timestamp=a.timestamp,
                value=a.value,
                expected_value=a.expected_value,
                deviation=a.deviation,
                severity=a.severity,
                method=a.method,
                confidence=a.confidence
            )
            for a in anomalies
        ]
    except Exception as e:
        logger.error(f"Error analyzing data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _format_alert_summary(alert: ProactiveAlert) -> str:
    """Format alert summary for display."""
    severity_emoji = {
        "low": "ℹ️",
        "medium": "⚠️",
        "high": "🔥",
        "critical": "🚨"
    }

    emoji = severity_emoji.get(alert.severity, "⚠️")
    anomaly_count = len(alert.anomalies)

    if anomaly_count == 1:
        anomaly = alert.anomalies[0]
        return (
            f"{emoji} {alert.target.name}: Detected {anomaly.method} anomaly - "
            f"value {anomaly.value:.2f} (expected {anomaly.expected_value:.2f})"
        )
    else:
        return (
            f"{emoji} {alert.target.name}: Detected {anomaly_count} anomalies "
            f"using multiple methods"
        )
