"""
API endpoints for handling Grafana alert webhooks.

Receives alerts from Grafana, investigates with AI, and creates ServiceNow tickets.
Supports multi-customer webhooks with auto-starting MCP containers.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from backend.agents.agent_manager import AgentManager
from backend.app.config import get_settings
from backend.app.mcp_servers import get_mcp_server_manager
from backend.containers.manager import get_container_manager
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])

# Directory for mock ServiceNow tickets (local testing)
TICKETS_DIR = Path("/tmp/servicenow_tickets")
TICKETS_DIR.mkdir(exist_ok=True)

# Customer webhook state tracking
_customer_webhook_state: Dict[str, Dict[str, Any]] = {}

# Notification callbacks for forwarding analyses (ServiceNow, Slack, etc.)
_notification_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []


def register_notification_callback(callback: Callable[[str, Dict[str, Any]], None]) -> None:
    """
    Register a callback to be notified when an alert analysis is complete.
    
    Callback signature: callback(customer_name: str, analysis: dict)
    Use this for ServiceNow, Slack, or other integrations.
    """
    _notification_callbacks.append(callback)


def get_webhook_state(customer_name: str) -> Dict[str, Any]:
    """Get webhook state for a customer."""
    return _customer_webhook_state.get(customer_name, {
        "last_alert_received": None,
        "total_alerts_received": 0,
        "pending_analyses": 0,
        "completed_analyses": 0,
        "last_analysis_completed": None,
        "mcp_containers_ready": False,
        "errors": []
    })


def _update_webhook_state(customer_name: str, **updates) -> None:
    """Update webhook state for a customer."""
    if customer_name not in _customer_webhook_state:
        _customer_webhook_state[customer_name] = {
            "last_alert_received": None,
            "total_alerts_received": 0,
            "pending_analyses": 0,
            "completed_analyses": 0,
            "last_analysis_completed": None,
            "mcp_containers_ready": False,
            "errors": []
        }
    _customer_webhook_state[customer_name].update(updates)


@dataclass
class KnowledgeBaseEntry:
    title: str
    source_file: str
    alert_name: Optional[str] = None
    alert_expression: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    impact: Optional[str] = None
    possible_causes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    extra_notes: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


KB_CACHE: Dict[str, Any] = {
    "entries": [],
    "files": {}
}


def _get_kb_dir() -> Path:
    settings = get_settings()
    kb_dir = Path(settings.kb_dir)
    kb_dir.mkdir(parents=True, exist_ok=True)
    return kb_dir


def _get_analysis_dir(customer_name: Optional[str] = None) -> Path:
    """
    Get analysis directory, optionally scoped to a customer.
    
    If customer_name is provided, returns customer-specific subdirectory.
    """
    settings = get_settings()
    base_dir = Path(settings.alert_analysis_dir)
    
    if customer_name:
        # Customer-scoped directory
        analysis_dir = base_dir / customer_name
    else:
        analysis_dir = base_dir
    
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir


def _normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


_STOPWORDS = {
    "alert",
    "alerts",
    "runbook",
    "service",
    "system",
    "manager",
    "communication",
    "monitoring",
    "status",
    "issue",
    "error",
    "errors",
    "warning",
    "critical",
    "high",
    "low",
    "medium",
    "host",
    "instance",
    "service",
    "device",
    "node",
    "server",
    "application",
    "problem",
    "failure",
}


def _tokenize(value: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", value.lower())
    return [token for token in tokens if token not in _STOPWORDS]


def _parse_kb_entry(content: str, source_file: str) -> KnowledgeBaseEntry:
    lines = [line.strip() for line in content.splitlines()]
    title = next((line for line in lines if line), source_file)

    section_map = {
        "alert name": "alert_name",
        "alert expression": "alert_expression",
        "category": "category",
        "description": "description",
        "possible cause": "possible_causes",
        "possible causes": "possible_causes",
        "impact": "impact",
        "next steps": "next_steps",
        "extra notes": "extra_notes"
    }

    sections: Dict[str, List[str]] = {}
    current_section = None

    for line in lines:
        if not line:
            continue
        match = re.match(r"^\s*([A-Za-z /()]+)\s*:\s*(.*)$", line)
        if match:
            header = match.group(1).lower()
            header = re.sub(r"\(.*?\)", "", header).strip()
            value = match.group(2).strip()
            section_key = section_map.get(header)
            if section_key:
                current_section = section_key
                sections.setdefault(section_key, [])
                if value:
                    sections[section_key].append(value)
                continue
        if current_section:
            sections.setdefault(current_section, [])
            sections[current_section].append(line)

    def to_text(section: str) -> Optional[str]:
        items = sections.get(section, [])
        cleaned = [item.strip(" -\t") for item in items if item.strip()]
        return " ".join(cleaned) if cleaned else None

    def to_list(section: str) -> List[str]:
        items = sections.get(section, [])
        cleaned = [item.strip(" -\t") for item in items if item.strip()]
        return cleaned

    entry = KnowledgeBaseEntry(
        title=title,
        source_file=source_file,
        alert_name=to_text("alert_name"),
        alert_expression=to_text("alert_expression"),
        category=to_text("category"),
        description=to_text("description"),
        impact=to_text("impact"),
        possible_causes=to_list("possible_causes"),
        next_steps=to_list("next_steps"),
        extra_notes=to_list("extra_notes")
    )

    keyword_source = " ".join(
        part for part in [
            entry.title,
            entry.alert_name,
            entry.alert_expression,
            entry.category,
            entry.description,
            entry.impact
        ]
        if part
    )
    entry.keywords = sorted(set(_tokenize(keyword_source)))
    return entry


def _load_kb_entries() -> List[KnowledgeBaseEntry]:
    kb_dir = _get_kb_dir()
    files = list(kb_dir.glob("*.txt"))
    if not files:
        return []

    current_files = {str(path): path.stat().st_mtime for path in files}
    if KB_CACHE["files"] == current_files:
        return KB_CACHE["entries"]

    entries = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            entries.append(_parse_kb_entry(content, path.name))
        except Exception as exc:
            logger.warning(f"Failed to read KB file {path}: {exc}")

    KB_CACHE["entries"] = entries
    KB_CACHE["files"] = current_files
    return entries


def _match_kb_entries(
    alert_name: str,
    labels: Dict[str, Any],
    annotations: Dict[str, Any],
    entries: List[KnowledgeBaseEntry],
    limit: int = 3
) -> List[Dict[str, Any]]:
    if not entries:
        return []

    score_threshold = 2.0
    alert_name_normalized = _normalize_text(alert_name or "")
    search_blob = " ".join(
        str(value)
        for value in [
            alert_name,
            *labels.values(),
            *annotations.values()
        ]
        if value is not None
    )
    search_tokens = set(_tokenize(search_blob))

    matches = []
    for entry in entries:
        score = 0.0
        matched_terms = set()
        if entry.alert_name:
            entry_alert = _normalize_text(entry.alert_name)
            if entry_alert and (
                entry_alert == alert_name_normalized
                or entry_alert in alert_name_normalized
                or alert_name_normalized in entry_alert
            ):
                score += 3.0

        keyword_tokens = set(entry.keywords)
        overlap = search_tokens.intersection(keyword_tokens)
        if overlap:
            matched_terms.update(overlap)
            score += min(2.0, len(overlap) / 3)

        if score >= score_threshold:
            matches.append({
                "entry": entry,
                "score": round(score, 2),
                "matched_terms": sorted(matched_terms)
            })

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:limit]


def _build_kb_context(matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return ""

    sections = []
    for match in matches:
        entry: KnowledgeBaseEntry = match["entry"]
        lines = [
            f"KB Title: {entry.title}",
            f"Alert Name: {entry.alert_name}" if entry.alert_name else None,
            f"Category: {entry.category}" if entry.category else None,
            f"Description: {entry.description}" if entry.description else None,
            f"Impact: {entry.impact}" if entry.impact else None
        ]

        if entry.possible_causes:
            lines.append("Possible Causes:")
            lines.extend([f"- {cause}" for cause in entry.possible_causes])

        if entry.next_steps:
            lines.append("Next Steps:")
            lines.extend([f"- {step}" for step in entry.next_steps])

        if entry.extra_notes:
            lines.append("Extra Notes:")
            lines.extend([f"- {note}" for note in entry.extra_notes])

        sections.append("\n".join(line for line in lines if line))

    return "\n\n".join(sections)

# Grafana Alert Webhook Models
class GrafanaAlertLabel(BaseModel):
    """Alert label from Grafana."""
    alertname: Optional[str] = None
    grafana_folder: Optional[str] = None
    severity: Optional[str] = None


class GrafanaAlertAnnotation(BaseModel):
    """Alert annotation from Grafana."""
    description: Optional[str] = None
    summary: Optional[str] = None
    runbook_url: Optional[str] = None


class GrafanaAlertValue(BaseModel):
    """Alert value/metric data."""
    instance: Optional[str] = None
    metric: Optional[str] = None
    value: Optional[float] = None


class GrafanaAlert(BaseModel):
    """Single alert from Grafana webhook."""
    status: str  # firing, resolved
    labels: Dict[str, Any]
    annotations: Dict[str, Any]
    startsAt: str
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: str
    values: Optional[Dict[str, float]] = None


class GrafanaWebhookPayload(BaseModel):
    """Grafana webhook payload structure."""
    receiver: str
    status: str  # firing, resolved
    alerts: List[GrafanaAlert]
    groupLabels: Dict[str, Any]
    commonLabels: Dict[str, Any]
    commonAnnotations: Dict[str, Any]
    externalURL: str
    version: str = "4"
    groupKey: str
    truncatedAlerts: int = 0


class AlertmanagerAlert(BaseModel):
    """Single alert from Alertmanager webhook."""
    status: str  # firing, resolved
    labels: Dict[str, Any]
    annotations: Dict[str, Any]
    startsAt: str
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class AlertmanagerWebhookPayload(BaseModel):
    """Alertmanager webhook payload structure."""
    version: str
    groupKey: str
    status: str
    receiver: str
    groupLabels: Dict[str, Any]
    commonLabels: Dict[str, Any]
    commonAnnotations: Dict[str, Any]
    externalURL: Optional[str] = None
    alerts: List[AlertmanagerAlert]


class AlertInvestigation(BaseModel):
    """AI-generated investigation result."""
    alert_name: str
    severity: str
    summary: str
    root_cause_hypothesis: str
    impact_assessment: str
    recommended_actions: List[str]
    related_evidence: List[str]
    confidence: float  # 0-1
    investigated_at: datetime


class AlertInvestigationResult(BaseModel):
    """Alert investigation with raw AI response."""
    investigation: AlertInvestigation
    raw_response: str


class ServiceNowTicket(BaseModel):
    """Mock ServiceNow ticket for local testing."""
    ticket_number: str
    priority: str  # P1, P2, P3
    short_description: str
    description: str
    assignment_group: str = "platform-ops"
    category: str = "Infrastructure"
    state: str = "New"
    created_at: datetime
    ai_generated: bool = True
    investigation_summary: str


# Severity mapping
SEVERITY_MAPPING = {
    "critical": {"priority": "P1", "snow_priority": "1", "action": "page"},
    "high": {"priority": "P2", "snow_priority": "2", "action": "ticket"},
    "warning": {"priority": "P3", "snow_priority": "3", "action": "ticket"},
    "info": {"priority": "P4", "snow_priority": "4", "action": "email_only"}
}


@router.post("/webhook")
async def grafana_webhook(
    payload: GrafanaWebhookPayload,
    background_tasks: BackgroundTasks
):
    """
    Receive alert webhook from Grafana.

    Grafana sends alerts here when they fire or resolve.
    For major/critical alerts, triggers AI investigation and creates ServiceNow ticket.
    """
    logger.info(f"Received Grafana webhook: {payload.status}, {len(payload.alerts)} alert(s)")

    # Only process firing alerts (ignore resolved for now)
    if payload.status != "firing":
        logger.info(f"Ignoring {payload.status} alert")
        return {"status": "ignored", "reason": f"Alert status is {payload.status}"}

    # Process each alert
    processed = []
    for alert in payload.alerts:
        # Extract severity
        severity = alert.labels.get("severity", "info").lower()

        # Only process major/critical alerts
        if severity not in ["critical", "high"]:
            logger.info(f"Skipping {severity} alert - only processing major/critical")
            continue

        # Process in background to not block webhook response
        background_tasks.add_task(
            process_alert,
            alert=alert,
            common_labels=payload.commonLabels,
            common_annotations=payload.commonAnnotations
        )

        processed.append({
            "fingerprint": alert.fingerprint,
            "severity": severity,
            "status": "queued_for_investigation"
        })

    return {
        "status": "received",
        "processed_count": len(processed),
        "alerts": processed
    }


@router.post("/ingest")
async def alertmanager_ingest(
    payload: AlertmanagerWebhookPayload,
    background_tasks: BackgroundTasks,
    sync: bool = False
):
    """
    Receive alert webhook from Alertmanager and write analysis files.
    
    DEPRECATED: Use /ingest/{customer_name} for multi-customer support.
    This endpoint processes alerts without customer context.

    Use ?sync=true to process in-request (slower but immediate output).
    """
    logger.info(f"Received Alertmanager webhook: {payload.status}, {len(payload.alerts)} alert(s)")

    if payload.status != "firing":
        logger.info(f"Ignoring {payload.status} alert")
        return {"status": "ignored", "reason": f"Alert status is {payload.status}"}

    processed = []
    for alert in payload.alerts:
        analysis_id = _build_analysis_id(alert)
        if sync:
            await process_alertmanager_alert(alert=alert, analysis_id=analysis_id)
            status = "processed"
        else:
            background_tasks.add_task(
                process_alertmanager_alert,
                alert=alert,
                analysis_id=analysis_id
            )
            status = "queued"

        processed.append({
            "analysis_id": analysis_id,
            "fingerprint": alert.fingerprint,
            "status": status
        })

    return {
        "status": "received",
        "processed_count": len(processed),
        "alerts": processed
    }


@router.post("/ingest/{customer_name}")
async def alertmanager_ingest_customer(
    customer_name: str,
    payload: AlertmanagerWebhookPayload,
    background_tasks: BackgroundTasks,
    sync: bool = False
):
    """
    Receive alert webhook from Alertmanager for a specific customer.
    
    This endpoint:
    1. Auto-starts the customer's MCP containers if not running
    2. Processes alerts with customer context
    3. Uses customer's Grafana/AlertManager MCP for investigation
    4. Stores analyses in customer-specific directory
    5. Triggers notification callbacks (ServiceNow, Slack, etc.)

    Configure AlertManager to send webhooks to:
        http://<sm3-agent>/api/alerts/ingest/{customer_name}

    Use ?sync=true to process in-request (slower but immediate output).
    """
    logger.info(f"Received Alertmanager webhook for {customer_name}: {payload.status}, {len(payload.alerts)} alert(s)")

    # Validate customer exists
    server_manager = get_mcp_server_manager()
    customer = server_manager.get_customer(customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_name}' not found")

    # Update webhook state
    _update_webhook_state(
        customer_name,
        last_alert_received=datetime.utcnow().isoformat(),
        total_alerts_received=get_webhook_state(customer_name).get("total_alerts_received", 0) + len(payload.alerts)
    )

    if payload.status != "firing":
        logger.info(f"Ignoring {payload.status} alert for {customer_name}")
        return {"status": "ignored", "reason": f"Alert status is {payload.status}"}

    # Start MCP containers in background (don't block webhook response)
    background_tasks.add_task(
        _ensure_customer_containers,
        customer_name=customer_name,
        customer=customer
    )

    processed = []
    pending_count = get_webhook_state(customer_name).get("pending_analyses", 0)
    
    for alert in payload.alerts:
        analysis_id = _build_analysis_id(alert)
        pending_count += 1
        
        if sync:
            await process_alertmanager_alert_customer(
                alert=alert,
                analysis_id=analysis_id,
                customer_name=customer_name,
                customer=customer
            )
            status = "processed"
            pending_count -= 1
        else:
            background_tasks.add_task(
                process_alertmanager_alert_customer,
                alert=alert,
                analysis_id=analysis_id,
                customer_name=customer_name,
                customer=customer
            )
            status = "queued"

        processed.append({
            "analysis_id": analysis_id,
            "customer": customer_name,
            "fingerprint": alert.fingerprint,
            "status": status
        })

    _update_webhook_state(customer_name, pending_analyses=pending_count)

    return {
        "status": "received",
        "customer": customer_name,
        "processed_count": len(processed),
        "alerts": processed
    }


@router.get("/status/{customer_name}")
async def get_customer_webhook_status(customer_name: str):
    """
    Get webhook and analysis status for a customer.
    
    Returns:
    - last_alert_received: Timestamp of last alert
    - total_alerts_received: Total count of alerts received
    - pending_analyses: Number of analyses in progress
    - completed_analyses: Number of completed analyses
    - mcp_containers_ready: Whether MCP containers are running
    - errors: Recent errors
    """
    # Validate customer exists
    server_manager = get_mcp_server_manager()
    customer = server_manager.get_customer(customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_name}' not found")

    state = get_webhook_state(customer_name)
    
    # Check if containers are running
    try:
        container_manager = get_container_manager()
        if container_manager and customer_name in container_manager._customers:
            customer_containers = container_manager._customers[customer_name]
            state["mcp_containers_ready"] = customer_containers.all_healthy()
        else:
            state["mcp_containers_ready"] = False
    except Exception:
        state["mcp_containers_ready"] = False

    # Count analyses files for this customer
    analysis_dir = _get_analysis_dir(customer_name)
    if analysis_dir.exists():
        state["analysis_files"] = len(list(analysis_dir.glob("*.json")))
    else:
        state["analysis_files"] = 0

    return state


@router.get("/webhook-status")
async def get_all_webhook_statuses():
    """
    Get webhook status for all customers.
    
    Returns a list of customers with their webhook status,
    useful for displaying connection health on dashboards.
    """
    server_manager = get_mcp_server_manager()
    customers = server_manager.list_customers()
    
    statuses = []
    for customer_info in customers:
        customer_name = customer_info.get("name", "")
        if not customer_name:
            continue
            
        state = get_webhook_state(customer_name)
        
        # Check container health
        try:
            container_manager = get_container_manager()
            if container_manager and customer_name in container_manager._customers:
                customer_containers = container_manager._customers[customer_name]
                state["mcp_containers_ready"] = customer_containers.all_healthy()
        except Exception:
            pass
        
        # Count analysis files
        analysis_dir = _get_analysis_dir(customer_name)
        if analysis_dir.exists():
            state["analysis_files"] = len(list(analysis_dir.glob("*.json")))
        else:
            state["analysis_files"] = 0
        
        statuses.append({
            "customer_name": customer_name,
            "webhook_url": f"/api/alerts/ingest/{customer_name}",
            **state
        })
    
    return {
        "customers": statuses,
        "total_customers": len(statuses),
        "customers_with_alerts": len([s for s in statuses if s.get("total_alerts_received", 0) > 0])
    }


async def _ensure_customer_containers(customer_name: str, customer: Any) -> bool:
    """
    Ensure customer MCP containers are running.
    Called when an alert is received for a customer.
    """
    try:
        container_manager = get_container_manager()
        if not container_manager:
            logger.warning(f"Container manager not available for {customer_name}")
            _update_webhook_state(customer_name, mcp_containers_ready=False)
            return False

        # Get MCP server configs
        mcp_servers = customer._raw_mcp_servers if hasattr(customer, '_raw_mcp_servers') else []
        
        if not mcp_servers:
            logger.info(f"No MCP servers configured for {customer_name}")
            _update_webhook_state(customer_name, mcp_containers_ready=False)
            return False

        # Start containers
        logger.info(f"Ensuring MCP containers for {customer_name} (alert triggered)")
        customer_containers = await container_manager.start_customer_containers(
            customer_name=customer_name,
            mcp_servers=mcp_servers,
            wait_for_healthy=True
        )
        
        is_healthy = customer_containers.all_healthy()
        _update_webhook_state(customer_name, mcp_containers_ready=is_healthy)
        
        if is_healthy:
            logger.info(f"MCP containers ready for {customer_name}")
        else:
            logger.warning(f"Some MCP containers unhealthy for {customer_name}")
        
        return is_healthy
        
    except Exception as e:
        logger.error(f"Error starting containers for {customer_name}: {e}", exc_info=True)
        _update_webhook_state(
            customer_name,
            mcp_containers_ready=False,
            errors=get_webhook_state(customer_name).get("errors", [])[-9:] + [str(e)]
        )
        return False


def _build_analysis_id(alert: AlertmanagerAlert) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    fingerprint = alert.fingerprint or uuid4().hex[:8]
    return f"alert-{timestamp}-{fingerprint}"


async def process_alertmanager_alert(alert: AlertmanagerAlert, analysis_id: str) -> None:
    """
    Process Alertmanager alert: match KB, investigate with AI, write analysis file.
    
    DEPRECATED: Use process_alertmanager_alert_customer for multi-customer support.
    """
    try:
        alert_name = alert.labels.get("alertname", "Unknown Alert")
        severity = str(alert.labels.get("severity", "info")).lower()
        description = alert.annotations.get("description", "No description")
        summary = alert.annotations.get("summary", alert_name)

        kb_entries = _load_kb_entries()
        kb_matches = _match_kb_entries(
            alert_name=alert_name,
            labels=alert.labels,
            annotations=alert.annotations,
            entries=kb_entries
        )
        kb_context = _build_kb_context(kb_matches)

        investigation_result = await investigate_alert_with_ai(
            alert_name=alert_name,
            severity=severity,
            description=description,
            summary=summary,
            metric_values={},
            labels=alert.labels,
            annotations=alert.annotations,
            kb_context=kb_context
        )

        analysis_record = _build_analysis_record(
            analysis_id=analysis_id,
            alert=alert,
            alert_name=alert_name,
            severity=severity,
            kb_matches=kb_matches,
            investigation_result=investigation_result
        )

        analysis_dir = _get_analysis_dir()
        analysis_file = analysis_dir / f"{analysis_id}.json"
        analysis_file.write_text(
            json.dumps(analysis_record, indent=2),
            encoding="utf-8"
        )

        logger.info(f"Alert analysis written: {analysis_file}")
    except Exception as exc:
        logger.error(f"Error processing Alertmanager alert {analysis_id}: {exc}", exc_info=True)


async def process_alertmanager_alert_customer(
    alert: AlertmanagerAlert,
    analysis_id: str,
    customer_name: str,
    customer: Any
) -> None:
    """
    Process Alertmanager alert for a specific customer.
    
    Uses customer's MCP servers for investigation and stores analysis per-customer.
    Triggers notification callbacks on completion.
    """
    try:
        alert_name = alert.labels.get("alertname", "Unknown Alert")
        severity = str(alert.labels.get("severity", "info")).lower()
        description = alert.annotations.get("description", "No description")
        summary = alert.annotations.get("summary", alert_name)

        logger.info(f"Processing alert for {customer_name}: {alert_name} ({severity})")

        kb_entries = _load_kb_entries()
        kb_matches = _match_kb_entries(
            alert_name=alert_name,
            labels=alert.labels,
            annotations=alert.annotations,
            entries=kb_entries
        )
        kb_context = _build_kb_context(kb_matches)

        # Use customer-specific investigation
        investigation_result = await investigate_alert_with_ai_customer(
            alert_name=alert_name,
            severity=severity,
            description=description,
            summary=summary,
            metric_values={},
            labels=alert.labels,
            annotations=alert.annotations,
            kb_context=kb_context,
            customer_name=customer_name,
            customer=customer
        )

        analysis_record = _build_analysis_record(
            analysis_id=analysis_id,
            alert=alert,
            alert_name=alert_name,
            severity=severity,
            kb_matches=kb_matches,
            investigation_result=investigation_result,
            customer_name=customer_name
        )

        # Write to customer-specific directory
        analysis_dir = _get_analysis_dir(customer_name)
        analysis_file = analysis_dir / f"{analysis_id}.json"
        analysis_file.write_text(
            json.dumps(analysis_record, indent=2),
            encoding="utf-8"
        )

        logger.info(f"Alert analysis written for {customer_name}: {analysis_file}")

        # Update webhook state
        state = get_webhook_state(customer_name)
        _update_webhook_state(
            customer_name,
            pending_analyses=max(0, state.get("pending_analyses", 1) - 1),
            completed_analyses=state.get("completed_analyses", 0) + 1,
            last_analysis_completed=datetime.utcnow().isoformat()
        )

        # Trigger notification callbacks (ServiceNow, Slack, etc.)
        for callback in _notification_callbacks:
            try:
                callback(customer_name, analysis_record)
            except Exception as cb_err:
                logger.error(f"Notification callback error: {cb_err}")

    except Exception as exc:
        logger.error(f"Error processing alert {analysis_id} for {customer_name}: {exc}", exc_info=True)
        state = get_webhook_state(customer_name)
        _update_webhook_state(
            customer_name,
            pending_analyses=max(0, state.get("pending_analyses", 1) - 1),
            errors=state.get("errors", [])[-9:] + [f"{alert_name}: {str(exc)}"]
        )


def _build_analysis_record(
    analysis_id: str,
    alert: AlertmanagerAlert,
    alert_name: str,
    severity: str,
    kb_matches: List[Dict[str, Any]],
    investigation_result: AlertInvestigationResult,
    customer_name: Optional[str] = None
) -> Dict[str, Any]:
    investigated_at = investigation_result.investigation.investigated_at.isoformat() + "Z"
    record = {
        "id": analysis_id,
        "source": "alertmanager",
        "status": alert.status,
        "alert_name": alert_name,
        "severity": severity,
        "received_at": datetime.utcnow().isoformat() + "Z",
        "labels": alert.labels,
        "annotations": alert.annotations,
        "kb_matches": [
            {
                "title": match["entry"].title,
                "alert_name": match["entry"].alert_name,
                "source_file": match["entry"].source_file,
                "score": match["score"],
                "matched_terms": match["matched_terms"]
            }
            for match in kb_matches
        ],
        "investigation": {
            "summary": investigation_result.investigation.summary,
            "root_cause_hypothesis": investigation_result.investigation.root_cause_hypothesis,
            "impact_assessment": investigation_result.investigation.impact_assessment,
            "recommended_actions": investigation_result.investigation.recommended_actions,
            "related_evidence": investigation_result.investigation.related_evidence,
            "confidence": investigation_result.investigation.confidence,
            "investigated_at": investigated_at
        },
        "raw_response": investigation_result.raw_response
    }
    
    if customer_name:
        record["customer_name"] = customer_name
    
    return record

async def process_alert(
    alert: GrafanaAlert,
    common_labels: Dict[str, Any],
    common_annotations: Dict[str, Any]
):
    """
    Process a single alert: investigate with AI and create ServiceNow ticket.

    Runs in background task.
    """
    try:
        logger.info(f"Processing alert: {alert.fingerprint}")

        # Extract alert details
        alert_name = alert.labels.get("alertname", "Unknown Alert")
        severity = alert.labels.get("severity", "unknown").lower()

        # Get alert description and summary
        description = alert.annotations.get("description", "No description")
        summary = alert.annotations.get("summary", alert_name)

        # Extract metric values
        metric_values = alert.values or {}

        # Run AI investigation
        investigation_result = await investigate_alert_with_ai(
            alert_name=alert_name,
            severity=severity,
            description=description,
            summary=summary,
            metric_values=metric_values,
            labels=alert.labels,
            annotations=alert.annotations
        )

        # Create ServiceNow ticket (mock for now)
        ticket = await create_servicenow_ticket(
            alert=alert,
            investigation=investigation_result.investigation,
            severity=severity
        )

        logger.info(f"Created ticket {ticket.ticket_number} for alert {alert_name}")

    except Exception as e:
        logger.error(f"Error processing alert {alert.fingerprint}: {e}", exc_info=True)


async def investigate_alert_with_ai(
    alert_name: str,
    severity: str,
    description: str,
    summary: str,
    metric_values: Dict[str, float],
    labels: Dict[str, Any],
    annotations: Dict[str, Any],
    kb_context: Optional[str] = None
) -> AlertInvestigationResult:
    """
    Use AI agent to investigate the alert and gather context.
    """
    logger.info(f"Starting AI investigation for: {alert_name}")

    # Build investigation prompt
    metrics_str = "\n".join([f"  - {k}: {v}" for k, v in metric_values.items()])
    labels_str = "\n".join([f"  - {k}: {v}" for k, v in labels.items()])

    knowledge_context = ""
    if kb_context:
        knowledge_context = f"""
**Knowledge Base References:**
{kb_context}
"""

    investigation_prompt = f"""
An alert has fired in production and requires investigation:

**Alert Details:**
- Name: {alert_name}
- Severity: {severity.upper()}
- Summary: {summary}
- Description: {description}

**Current Metric Values:**
{metrics_str or "  No metric values provided"}

**Labels:**
{labels_str}
{knowledge_context}

**Your Task:**
Please investigate this alert by:

1. **Check Recent Trends**: Query relevant Prometheus metrics for the last hour to see if this is a spike or ongoing issue
2. **Gather Context**: Check related metrics (CPU, memory, network, error rates) for the affected service/instance
3. **Review Logs**: Query Loki for error logs around the alert time
4. **Check Dashboards**: Look for relevant dashboards that show the service health
5. **Correlate**: Are other instances/services affected?

**Provide in your response:**
- **Root Cause Hypothesis**: What likely caused this alert? (2-3 sentences)
- **Impact Assessment**: What's affected and how severe? (2-3 sentences)
- **Recommended Actions**: List 3-4 specific steps to resolve (bullet points)
- **Evidence**: Cite specific metrics, log entries, or dashboard data you found

Focus on actionable insights for the on-call engineer.
"""

    try:
        # Get agent manager
        settings = get_settings()
        agent_manager = AgentManager(settings)
        await agent_manager.initialize()

        # Run investigation
        session_id = f"alert-investigation-{datetime.utcnow().timestamp()}"
        result = await agent_manager.run_chat(
            message=investigation_prompt,
            session_id=session_id
        )

        # Parse the AI response
        ai_response = result.message

        # Log the full AI response for debugging
        logger.info(f"AI Investigation Response:\n{ai_response}\n{'='*80}")

        # Extract structured data from response
        # (In production, you'd use more sophisticated parsing or structured output)
        investigation = AlertInvestigation(
            alert_name=alert_name,
            severity=severity,
            summary=summary,
            root_cause_hypothesis=extract_section(ai_response, "Root Cause"),
            impact_assessment=extract_section(ai_response, "Impact"),
            recommended_actions=extract_actions(ai_response),
            related_evidence=extract_evidence(ai_response),
            confidence=calculate_confidence(result),
            investigated_at=datetime.utcnow()
        )

        logger.info(f"Investigation completed for {alert_name}")
        return AlertInvestigationResult(
            investigation=investigation,
            raw_response=ai_response
        )

    except Exception as e:
        logger.error(f"Error during AI investigation: {e}", exc_info=True)

        # Fallback investigation if AI fails
        investigation = AlertInvestigation(
            alert_name=alert_name,
            severity=severity,
            summary=summary,
            root_cause_hypothesis="AI investigation failed - manual investigation required",
            impact_assessment=f"Alert triggered: {description}",
            recommended_actions=["Check Grafana dashboard", "Review recent deployments", "Check service logs"],
            related_evidence=["AI investigation unavailable"],
            confidence=0.0,
            investigated_at=datetime.utcnow()
        )
        return AlertInvestigationResult(
            investigation=investigation,
            raw_response="AI investigation failed"
        )


async def investigate_alert_with_ai_customer(
    alert_name: str,
    severity: str,
    description: str,
    summary: str,
    metric_values: Dict[str, float],
    labels: Dict[str, Any],
    annotations: Dict[str, Any],
    customer_name: str,
    customer: Any,
    kb_context: Optional[str] = None
) -> AlertInvestigationResult:
    """
    Use AI agent to investigate the alert using customer's MCP servers.
    
    This version switches to the customer's MCP servers before investigation,
    allowing queries against the customer's specific Grafana/Prometheus/Loki.
    """
    logger.info(f"Starting AI investigation for {customer_name}: {alert_name}")

    # Build investigation prompt
    metrics_str = "\n".join([f"  - {k}: {v}" for k, v in metric_values.items()])
    labels_str = "\n".join([f"  - {k}: {v}" for k, v in labels.items()])

    knowledge_context = ""
    if kb_context:
        knowledge_context = f"""
**Knowledge Base References:**
{kb_context}
"""

    investigation_prompt = f"""
An alert has fired for customer **{customer_name}** and requires investigation:

**Alert Details:**
- Name: {alert_name}
- Severity: {severity.upper()}
- Summary: {summary}
- Description: {description}

**Current Metric Values:**
{metrics_str or "  No metric values provided"}

**Labels:**
{labels_str}
{knowledge_context}

**Your Task:**
Please investigate this alert by:

1. **Check Recent Trends**: Query relevant Prometheus metrics for the last hour to see if this is a spike or ongoing issue
2. **Gather Context**: Check related metrics (CPU, memory, network, error rates) for the affected service/instance
3. **Review Logs**: Query Loki for error logs around the alert time
4. **Check Dashboards**: Look for relevant dashboards that show the service health
5. **Correlate**: Are other instances/services affected?

**Provide in your response:**
- **Root Cause Hypothesis**: What likely caused this alert? (2-3 sentences)
- **Impact Assessment**: What's affected and how severe? (2-3 sentences)
- **Recommended Actions**: List 3-4 specific steps to resolve (bullet points)
- **Evidence**: Cite specific metrics, log entries, or dashboard data you found

Focus on actionable insights for the on-call engineer.
"""

    try:
        # Get agent manager and switch to customer
        settings = get_settings()
        agent_manager = AgentManager(settings)
        await agent_manager.initialize()
        
        # Switch to customer's MCP servers
        mcp_servers = customer._raw_mcp_servers if hasattr(customer, '_raw_mcp_servers') else []
        if mcp_servers:
            try:
                await agent_manager.switch_customer(customer_name, mcp_servers)
                logger.info(f"Switched to {customer_name}'s MCP servers for investigation")
            except Exception as switch_err:
                logger.warning(f"Failed to switch to {customer_name}'s MCP: {switch_err}")
                # Continue with default MCP servers

        # Run investigation
        session_id = f"alert-investigation-{customer_name}-{datetime.utcnow().timestamp()}"
        result = await agent_manager.run_chat(
            message=investigation_prompt,
            session_id=session_id
        )

        # Parse the AI response
        ai_response = result.message

        # Log the full AI response for debugging
        logger.info(f"AI Investigation Response for {customer_name}:\n{ai_response}\n{'='*80}")

        # Extract structured data from response
        investigation = AlertInvestigation(
            alert_name=alert_name,
            severity=severity,
            summary=summary,
            root_cause_hypothesis=extract_section(ai_response, "Root Cause"),
            impact_assessment=extract_section(ai_response, "Impact"),
            recommended_actions=extract_actions(ai_response),
            related_evidence=extract_evidence(ai_response),
            confidence=calculate_confidence(result),
            investigated_at=datetime.utcnow()
        )

        logger.info(f"Investigation completed for {customer_name}: {alert_name}")
        return AlertInvestigationResult(
            investigation=investigation,
            raw_response=ai_response
        )

    except Exception as e:
        logger.error(f"Error during AI investigation for {customer_name}: {e}", exc_info=True)

        # Fallback investigation if AI fails
        investigation = AlertInvestigation(
            alert_name=alert_name,
            severity=severity,
            summary=summary,
            root_cause_hypothesis="AI investigation failed - manual investigation required",
            impact_assessment=f"Alert triggered for {customer_name}: {description}",
            recommended_actions=["Check Grafana dashboard", "Review recent deployments", "Check service logs"],
            related_evidence=["AI investigation unavailable"],
            confidence=0.0,
            investigated_at=datetime.utcnow()
        )
        return AlertInvestigationResult(
            investigation=investigation,
            raw_response="AI investigation failed"
        )


async def create_servicenow_ticket(
    alert: GrafanaAlert,
    investigation: AlertInvestigation,
    severity: str
) -> ServiceNowTicket:
    """
    Create ServiceNow ticket (mock version - writes to file).

    In production, this would call ServiceNow REST API.
    """
    # Get priority mapping
    severity_config = SEVERITY_MAPPING.get(severity, SEVERITY_MAPPING["info"])
    priority = severity_config["priority"]

    # Generate ticket number (mock)
    ticket_number = f"INC{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # Format description
    description = format_ticket_description(investigation)

    # Create ticket object
    ticket = ServiceNowTicket(
        ticket_number=ticket_number,
        priority=priority,
        short_description=f"[{severity.upper()}] {investigation.alert_name}",
        description=description,
        created_at=datetime.utcnow(),
        investigation_summary=investigation.root_cause_hypothesis
    )

    # Write to file (mock ServiceNow)
    ticket_file = TICKETS_DIR / f"{ticket_number}.json"
    ticket_file.write_text(
        json.dumps(ticket.dict(), indent=2, default=str),
        encoding="utf-8"
    )

    # Also write human-readable version
    ticket_txt = TICKETS_DIR / f"{ticket_number}.txt"
    ticket_txt.write_text(format_ticket_text(ticket), encoding="utf-8")

    logger.info(f"Mock ServiceNow ticket written to {ticket_file}")

    return ticket


def format_ticket_description(investigation: AlertInvestigation) -> str:
    """Format investigation into ServiceNow ticket description."""
    actions = "\n".join([f"  {i+1}. {action}" for i, action in enumerate(investigation.recommended_actions)])
    evidence = "\n".join([f"  - {item}" for item in investigation.related_evidence])

    return f"""
=== ALERT DETAILS ===
Alert: {investigation.alert_name}
Severity: {investigation.severity.upper()}
Summary: {investigation.summary}
Investigated: {investigation.investigated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
Confidence: {investigation.confidence:.0%}

=== ROOT CAUSE HYPOTHESIS ===
{investigation.root_cause_hypothesis}

=== IMPACT ASSESSMENT ===
{investigation.impact_assessment}

=== RECOMMENDED ACTIONS ===
{actions}

=== SUPPORTING EVIDENCE ===
{evidence}

---
This ticket was generated automatically by the Grafana AI Agent.
""".strip()


def format_ticket_text(ticket: ServiceNowTicket) -> str:
    """Format ticket as human-readable text file."""
    return f"""
╔══════════════════════════════════════════════════════════════╗
║                    SERVICENOW TICKET (MOCK)                   ║
╚══════════════════════════════════════════════════════════════╝

Ticket Number:    {ticket.ticket_number}
Priority:         {ticket.priority}
State:            {ticket.state}
Created:          {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
Assignment Group: {ticket.assignment_group}
Category:         {ticket.category}

─────────────────────────────────────────────────────────────────

SHORT DESCRIPTION:
{ticket.short_description}

─────────────────────────────────────────────────────────────────

DESCRIPTION:

{ticket.description}

─────────────────────────────────────────────────────────────────

** This is a MOCK ticket for local testing **
** In production, this would be created in ServiceNow via REST API **

""".strip()


# Helper functions for parsing AI response
def extract_section(text: str, section_name: str) -> str:
    """Extract a section from AI response."""
    # Simple extraction - in production use more robust parsing
    lines = text.split('\n')
    in_section = False
    section_lines = []

    for line in lines:
        if section_name.lower() in line.lower() and (':**' in line or '###' in line or '**' in line):
            in_section = True
            continue
        elif in_section and (line.startswith('**') or line.startswith('###') or not line.strip()):
            if section_lines:  # We've collected some lines
                break
        elif in_section:
            section_lines.append(line.strip())

    return ' '.join(section_lines) if section_lines else f"See full investigation for {section_name}"


def extract_actions(text: str) -> List[str]:
    """Extract recommended actions from AI response."""
    lines = text.split('\n')
    actions = []
    in_actions = False

    for line in lines:
        if 'recommended' in line.lower() and 'action' in line.lower():
            in_actions = True
            continue
        elif in_actions:
            # Look for bullet points or numbered lists
            stripped = line.strip()
            if stripped and (stripped.startswith('-') or stripped.startswith('*') or stripped[0].isdigit()):
                # Remove bullet/number
                action = stripped.lstrip('-*0123456789. ')
                if action:
                    actions.append(action)
            elif stripped and not stripped.startswith('**'):
                # Plain text action
                actions.append(stripped)
            elif stripped.startswith('**') or stripped.startswith('###'):
                # New section started
                break

    return actions[:5] if actions else ["Review alert in Grafana", "Check service logs", "Escalate if needed"]


def extract_evidence(text: str) -> List[str]:
    """Extract evidence from AI response."""
    # Look for metric values, log entries, dashboard references
    evidence = []
    lines = text.split('\n')

    for line in lines:
        if any(keyword in line.lower() for keyword in ['metric', 'log', 'dashboard', 'query', 'value', 'error']):
            if ':' in line and not line.startswith('#'):
                evidence.append(line.strip())

    return evidence[:10] if evidence else ["See investigation details above"]


def calculate_confidence(result) -> float:
    """Calculate confidence score based on investigation quality."""
    # Simple heuristic - in production, use more sophisticated scoring
    tool_calls = len(result.tool_calls) if hasattr(result, 'tool_calls') else 0
    message_length = len(result.message) if hasattr(result, 'message') else 0

    # More tool calls and longer analysis = higher confidence
    confidence = min(1.0, (tool_calls * 0.15) + min(0.4, message_length / 2000))
    return round(confidence, 2)


# Management endpoints
@router.get("/analyses")
async def list_alert_analyses(limit: int = 50, customer_name: Optional[str] = None):
    """
    List recent alert analyses.
    
    Args:
        limit: Maximum number of analyses to return
        customer_name: Optional filter by customer. If provided, only returns
                       analyses for that customer. Otherwise returns all.
    """
    if customer_name:
        # Get customer-specific analyses
        analysis_dir = _get_analysis_dir(customer_name)
        analysis_files = sorted(
            analysis_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True
        )[:limit]
    else:
        # Get all analyses (both root and customer subdirectories)
        base_dir = _get_analysis_dir()
        analysis_files = []
        
        # Root level analyses (legacy)
        analysis_files.extend(base_dir.glob("*.json"))
        
        # Customer subdirectory analyses
        for subdir in base_dir.iterdir():
            if subdir.is_dir():
                analysis_files.extend(subdir.glob("*.json"))
        
        # Sort by modification time and limit
        analysis_files = sorted(
            analysis_files,
            key=lambda path: path.stat().st_mtime,
            reverse=True
        )[:limit]

    analyses = []
    for analysis_file in analysis_files:
        try:
            data = json.loads(analysis_file.read_text(encoding="utf-8"))
            investigation = data.get("investigation", {})
            analyses.append({
                "id": data.get("id", analysis_file.stem),
                "customer_name": data.get("customer_name"),
                "alert_name": data.get("alert_name", "Unknown Alert"),
                "severity": data.get("severity", "info"),
                "status": data.get("status", "unknown"),
                "received_at": data.get("received_at"),
                "kb_matches": data.get("kb_matches", []),
                "summary": investigation.get("root_cause_hypothesis", ""),
                "confidence": investigation.get("confidence", 0)
            })
        except Exception as exc:
            logger.error(f"Error reading analysis {analysis_file}: {exc}")

    return {
        "count": len(analyses),
        "customer_name": customer_name,
        "analyses": analyses
    }


@router.get("/analyses/{analysis_id}")
async def get_alert_analysis(analysis_id: str, customer_name: Optional[str] = None):
    """
    Get a specific alert analysis.
    
    Args:
        analysis_id: The analysis ID
        customer_name: Optional customer name to look in customer-specific directory
    """
    # Try customer-specific directory first if provided
    if customer_name:
        analysis_file = _get_analysis_dir(customer_name) / f"{analysis_id}.json"
        if analysis_file.exists():
            return json.loads(analysis_file.read_text(encoding="utf-8"))
    
    # Try root directory
    analysis_file = _get_analysis_dir() / f"{analysis_id}.json"
    if analysis_file.exists():
        return json.loads(analysis_file.read_text(encoding="utf-8"))
    
    # Search all customer directories
    base_dir = _get_analysis_dir()
    for subdir in base_dir.iterdir():
        if subdir.is_dir():
            analysis_file = subdir / f"{analysis_id}.json"
            if analysis_file.exists():
                return json.loads(analysis_file.read_text(encoding="utf-8"))

    raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")


@router.get("/tickets")
async def list_tickets(limit: int = 50):
    """
    List mock ServiceNow tickets created locally.

    Useful for reviewing what would have been sent to ServiceNow.
    """
    tickets = []

    for ticket_file in sorted(TICKETS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            ticket_data = json.loads(ticket_file.read_text())
            tickets.append(ticket_data)
        except Exception as e:
            logger.error(f"Error reading ticket {ticket_file}: {e}")

    return {
        "count": len(tickets),
        "tickets": tickets
    }


@router.get("/tickets/{ticket_number}")
async def get_ticket(ticket_number: str):
    """Get a specific mock ServiceNow ticket."""
    ticket_file = TICKETS_DIR / f"{ticket_number}.json"

    if not ticket_file.exists():
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_number} not found")

    ticket_data = json.loads(ticket_file.read_text())
    return ticket_data


@router.delete("/tickets")
async def clear_tickets():
    """Clear all mock ServiceNow tickets (for testing)."""
    count = 0
    for ticket_file in TICKETS_DIR.glob("*"):
        ticket_file.unlink()
        count += 1

    return {"status": "cleared", "deleted": count}
