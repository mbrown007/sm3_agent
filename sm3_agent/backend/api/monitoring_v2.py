"""
Customer-aware monitoring API endpoints.

Replaces the old global monitoring with per-customer isolated monitoring loops.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.agents.customer_monitoring import (
    MonitoringTarget,
    ProactiveAlert,
    CustomerHealth,
    Datasource,
    DatasourceType,
    get_customer_monitoring_manager,
    create_default_targets_for_customer
)
from backend.intelligence.anomaly import TimeSeriesPoint, get_anomaly_detector
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# ==================== Request/Response Models ====================

class MonitoringTargetCreate(BaseModel):
    """Request to create a monitoring target."""
    name: str = Field(..., description="Target name")
    query: str = Field(..., description="PromQL or LogQL query")
    datasource_uid: str = Field(..., description="Datasource UID")
    query_type: str = Field(..., description="Query type: prometheus or loki")
    check_interval: int = Field(300, description="Check interval in seconds")
    detection_methods: List[str] = Field(default=["zscore", "iqr"])
    severity_threshold: str = Field("medium", description="Minimum severity to alert")
    enabled: bool = Field(True)


class MonitoringTargetResponse(BaseModel):
    """Monitoring target response."""
    name: str
    customer_name: str
    query: str
    datasource_uid: str
    query_type: str
    check_interval: int
    detection_methods: List[str]
    severity_threshold: str
    enabled: bool
    last_check: Optional[datetime]
    last_error: Optional[str]


class AlertResponse(BaseModel):
    """Proactive alert response."""
    id: str
    timestamp: datetime
    customer_name: str
    target_name: str
    anomaly_count: int
    severity: str
    acknowledged: bool
    summary: str


class MonitoringStatusResponse(BaseModel):
    """Monitoring system status."""
    running: bool
    customer_name: Optional[str]
    targets_count: int
    enabled_targets: int
    total_alerts: int
    recent_alerts: int
    critical_alerts: int
    # Multi-customer fields
    running_customers: Optional[int] = None
    total_customers: Optional[int] = None


class CustomerHealthResponse(BaseModel):
    """Customer health for NOC dashboard."""
    customer_name: str
    is_monitoring: bool
    targets_count: int
    enabled_targets: int
    total_alerts: int
    critical_alerts: int
    warning_alerts: int
    last_check: Optional[datetime]
    status: str  # healthy, warning, critical, unknown


class DatasourceResponse(BaseModel):
    """Discovered datasource response."""
    uid: str
    name: str
    type: str
    url: Optional[str]
    is_default: bool


class NOCOverviewResponse(BaseModel):
    """NOC dashboard overview."""
    total_customers: int
    monitoring_customers: int
    healthy_count: int
    warning_count: int
    critical_count: int
    unknown_count: int
    customers: List[CustomerHealthResponse]


# ==================== Status Endpoints ====================

@router.get("/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status(customer_name: Optional[str] = Query(None)):
    """
    Get monitoring status, optionally for a specific customer.
    
    If customer_name is provided, returns status for that customer only.
    Otherwise returns aggregate status across all customers.
    """
    try:
        manager = get_customer_monitoring_manager()
        status = manager.get_monitoring_status(customer_name)
        return MonitoringStatusResponse(**status)
    except Exception as e:
        logger.error(f"Error getting monitoring status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/noc", response_model=NOCOverviewResponse)
async def get_noc_overview():
    """
    Get NOC dashboard overview showing all customers' health status.
    
    Returns aggregate counts and per-customer health for dashboard display.
    Shows all configured customers, not just those actively monitored.
    """
    try:
        from backend.app.mcp_servers import get_mcp_server_manager
        from backend.services.webhook_manager import get_webhook_manager
        
        manager = get_customer_monitoring_manager()
        server_manager = get_mcp_server_manager()
        webhook_manager = get_webhook_manager()
        
        # Get all configured customers
        all_customer_names = server_manager.get_customer_names()
        
        # Get monitoring health for customers that have monitoring state
        health_dict = {h.customer_name: h for h in manager.get_all_customer_health()}
        
        # Build health list for ALL customers
        health_list = []
        for name in all_customer_names:
            if name in health_dict:
                # Use existing health data
                health_list.append(health_dict[name])
            else:
                # Create default health entry for unconfigured customer
                # Check webhook status for any received alerts
                webhook = webhook_manager.get_webhook(name)
                has_alerts = webhook.total_alerts_received > 0 if webhook else False
                
                health_list.append(CustomerHealth(
                    customer_name=name,
                    is_monitoring=False,
                    targets_count=0,
                    enabled_targets=0,
                    total_alerts=webhook.total_alerts_received if webhook else 0,
                    critical_alerts=0,
                    warning_alerts=0,
                    last_check=webhook.last_alert_received if webhook else None,
                    status="unknown"
                ))
        
        # Sort: critical first, then warning, then healthy, then unknown
        health_list = sorted(health_list, key=lambda h: (
            {"critical": 0, "warning": 1, "healthy": 2, "unknown": 3}.get(h.status, 4),
            h.customer_name
        ))
        
        healthy = sum(1 for h in health_list if h.status == "healthy")
        warning = sum(1 for h in health_list if h.status == "warning")
        critical = sum(1 for h in health_list if h.status == "critical")
        unknown = sum(1 for h in health_list if h.status == "unknown")
        
        return NOCOverviewResponse(
            total_customers=len(health_list),
            monitoring_customers=sum(1 for h in health_list if h.is_monitoring),
            healthy_count=healthy,
            warning_count=warning,
            critical_count=critical,
            unknown_count=unknown,
            customers=[
                CustomerHealthResponse(
                    customer_name=h.customer_name,
                    is_monitoring=h.is_monitoring,
                    targets_count=h.targets_count,
                    enabled_targets=h.enabled_targets,
                    total_alerts=h.total_alerts,
                    critical_alerts=h.critical_alerts,
                    warning_alerts=h.warning_alerts,
                    last_check=h.last_check,
                    status=h.status
                )
                for h in health_list
            ]
        )
    except Exception as e:
        logger.error(f"Error getting NOC overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Start/Stop Endpoints ====================

@router.post("/start/{customer_name}")
async def start_customer_monitoring(customer_name: str):
    """Start monitoring for a specific customer."""
    try:
        manager = get_customer_monitoring_manager()
        await manager.start_customer_monitoring(customer_name)
        return {"status": "started", "customer": customer_name}
    except Exception as e:
        logger.error(f"Error starting monitoring for {customer_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/{customer_name}")
async def stop_customer_monitoring(customer_name: str):
    """Stop monitoring for a specific customer."""
    try:
        manager = get_customer_monitoring_manager()
        await manager.stop_customer_monitoring(customer_name)
        return {"status": "stopped", "customer": customer_name}
    except Exception as e:
        logger.error(f"Error stopping monitoring for {customer_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Datasource Discovery ====================

@router.get("/datasources/{customer_name}", response_model=List[DatasourceResponse])
async def get_customer_datasources(customer_name: str):
    """Get discovered datasources for a customer."""
    try:
        manager = get_customer_monitoring_manager()
        datasources = manager.get_datasources(customer_name)
        return [
            DatasourceResponse(
                uid=ds.uid,
                name=ds.name,
                type=ds.type.value,
                url=ds.url,
                is_default=ds.is_default
            )
            for ds in datasources
        ]
    except Exception as e:
        logger.error(f"Error getting datasources: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/datasources/{customer_name}/discover")
async def discover_customer_datasources(customer_name: str):
    """Trigger datasource discovery for a customer."""
    try:
        manager = get_customer_monitoring_manager()
        datasources = await manager.discover_datasources(customer_name)
        return {
            "status": "discovered",
            "count": len(datasources),
            "datasources": [
                {"uid": ds.uid, "name": ds.name, "type": ds.type.value}
                for ds in datasources
            ]
        }
    except Exception as e:
        logger.error(f"Error discovering datasources: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Target Management ====================

@router.get("/targets", response_model=List[MonitoringTargetResponse])
async def list_targets(customer_name: Optional[str] = Query(None)):
    """
    List monitoring targets, optionally filtered by customer.
    
    If customer_name is not provided, returns targets for all customers.
    """
    try:
        manager = get_customer_monitoring_manager()
        targets = manager.get_targets(customer_name)
        return [
            MonitoringTargetResponse(
                name=t.name,
                customer_name=t.customer_name,
                query=t.query,
                datasource_uid=t.datasource_uid,
                query_type=t.query_type,
                check_interval=t.check_interval,
                detection_methods=t.detection_methods,
                severity_threshold=t.severity_threshold,
                enabled=t.enabled,
                last_check=t.last_check,
                last_error=t.last_error
            )
            for t in targets
        ]
    except Exception as e:
        logger.error(f"Error listing targets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/targets/{customer_name}", response_model=MonitoringTargetResponse)
async def create_target(customer_name: str, target: MonitoringTargetCreate):
    """Create a new monitoring target for a customer."""
    try:
        manager = get_customer_monitoring_manager()
        
        # Check if target already exists
        existing = manager.get_targets(customer_name)
        if any(t.name == target.name for t in existing):
            raise HTTPException(
                status_code=400,
                detail=f"Target '{target.name}' already exists for {customer_name}"
            )
        
        monitoring_target = MonitoringTarget(
            name=target.name,
            customer_name=customer_name,
            query=target.query,
            datasource_uid=target.datasource_uid,
            query_type=target.query_type,
            check_interval=target.check_interval,
            detection_methods=target.detection_methods,
            severity_threshold=target.severity_threshold,
            enabled=target.enabled
        )
        
        manager.add_target(customer_name, monitoring_target)
        
        return MonitoringTargetResponse(
            name=monitoring_target.name,
            customer_name=customer_name,
            query=monitoring_target.query,
            datasource_uid=monitoring_target.datasource_uid,
            query_type=monitoring_target.query_type,
            check_interval=monitoring_target.check_interval,
            detection_methods=monitoring_target.detection_methods,
            severity_threshold=monitoring_target.severity_threshold,
            enabled=monitoring_target.enabled,
            last_check=None,
            last_error=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/targets/{customer_name}/defaults")
async def create_default_targets(customer_name: str, prometheus_uid: Optional[str] = None):
    """Create default monitoring targets for a customer."""
    try:
        manager = get_customer_monitoring_manager()
        
        # Try to find Prometheus datasource
        datasources = manager.get_datasources(customer_name)
        prom_uid = prometheus_uid
        if not prom_uid:
            for ds in datasources:
                if ds.type == DatasourceType.PROMETHEUS:
                    prom_uid = ds.uid
                    break
        
        if not prom_uid:
            prom_uid = "prometheus"  # Fallback
        
        defaults = create_default_targets_for_customer(customer_name, prom_uid)
        
        created = []
        for target in defaults:
            existing = manager.get_targets(customer_name)
            if not any(t.name == target.name for t in existing):
                manager.add_target(customer_name, target)
                created.append(target.name)
        
        return {
            "status": "created",
            "customer": customer_name,
            "datasource_uid": prom_uid,
            "created_targets": created
        }
    except Exception as e:
        logger.error(f"Error creating default targets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/targets/{customer_name}/{target_name}")
async def delete_target(customer_name: str, target_name: str):
    """Delete a monitoring target."""
    try:
        manager = get_customer_monitoring_manager()
        manager.remove_target(customer_name, target_name)
        return {"status": "deleted", "customer": customer_name, "target": target_name}
    except Exception as e:
        logger.error(f"Error deleting target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/targets/{customer_name}/{target_name}/enable")
async def enable_target(customer_name: str, target_name: str):
    """Enable a monitoring target."""
    try:
        manager = get_customer_monitoring_manager()
        manager.enable_target(customer_name, target_name)
        return {"status": "enabled", "customer": customer_name, "target": target_name}
    except Exception as e:
        logger.error(f"Error enabling target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/targets/{customer_name}/{target_name}/disable")
async def disable_target(customer_name: str, target_name: str):
    """Disable a monitoring target."""
    try:
        manager = get_customer_monitoring_manager()
        manager.disable_target(customer_name, target_name)
        return {"status": "disabled", "customer": customer_name, "target": target_name}
    except Exception as e:
        logger.error(f"Error disabling target: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Alerts ====================

@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    customer_name: Optional[str] = Query(None),
    minutes: int = 60,
    min_severity: str = "low",
    include_acknowledged: bool = False
):
    """
    Get recent alerts, optionally filtered by customer.
    
    If customer_name is not provided, returns alerts for all customers.
    """
    try:
        manager = get_customer_monitoring_manager()
        alerts = manager.get_alerts(
            customer_name=customer_name,
            min_severity=min_severity,
            minutes=minutes,
            include_acknowledged=include_acknowledged
        )
        
        return [
            AlertResponse(
                id=a.id,
                timestamp=a.timestamp,
                customer_name=a.customer_name,
                target_name=a.target_name,
                anomaly_count=len(a.anomalies),
                severity=a.severity,
                acknowledged=a.acknowledged,
                summary=_format_alert_summary(a)
            )
            for a in alerts
        ]
    except Exception as e:
        logger.error(f"Error getting alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{customer_name}/{alert_id}/acknowledge")
async def acknowledge_alert(customer_name: str, alert_id: str, user: str = "system"):
    """Acknowledge an alert."""
    try:
        manager = get_customer_monitoring_manager()
        success = manager.acknowledge_alert(customer_name, alert_id, user)
        
        if not success:
            raise HTTPException(status_code=404, detail="Alert not found")
        
        return {"status": "acknowledged", "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Helpers ====================

def _format_alert_summary(alert: ProactiveAlert) -> str:
    """Format alert summary for display."""
    severity_emoji = {
        "low": "ℹ️",
        "medium": "⚠️",
        "high": "🔥",
        "critical": "🚨"
    }
    emoji = severity_emoji.get(alert.severity, "⚠️")
    count = len(alert.anomalies)
    
    if count == 1:
        a = alert.anomalies[0]
        return (
            f"{emoji} {alert.customer_name}/{alert.target_name}: "
            f"{a.method} anomaly - value {a.value:.2f} (expected {a.expected_value:.2f})"
        )
    else:
        return (
            f"{emoji} {alert.customer_name}/{alert.target_name}: "
            f"{count} anomalies detected"
        )
