"""
API endpoints for handling Grafana alert webhooks.

Receives alerts from Grafana, investigates with AI, and creates ServiceNow tickets.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from backend.agents.agent_manager import AgentManager
from backend.app.config import get_settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])

# Directory for mock ServiceNow tickets (local testing)
TICKETS_DIR = Path("/tmp/servicenow_tickets")
TICKETS_DIR.mkdir(exist_ok=True)


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


def _get_analysis_dir() -> Path:
    settings = get_settings()
    analysis_dir = Path(settings.alert_analysis_dir)
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


def _build_analysis_id(alert: AlertmanagerAlert) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    fingerprint = alert.fingerprint or uuid4().hex[:8]
    return f"alert-{timestamp}-{fingerprint}"


async def process_alertmanager_alert(alert: AlertmanagerAlert, analysis_id: str) -> None:
    """
    Process Alertmanager alert: match KB, investigate with AI, write analysis file.
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


def _build_analysis_record(
    analysis_id: str,
    alert: AlertmanagerAlert,
    alert_name: str,
    severity: str,
    kb_matches: List[Dict[str, Any]],
    investigation_result: AlertInvestigationResult
) -> Dict[str, Any]:
    investigated_at = investigation_result.investigation.investigated_at.isoformat() + "Z"
    return {
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
async def list_alert_analyses(limit: int = 50):
    """List recent alert analyses."""
    analysis_dir = _get_analysis_dir()
    analysis_files = sorted(
        analysis_dir.glob("*.json"),
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
        "analyses": analyses
    }


@router.get("/analyses/{analysis_id}")
async def get_alert_analysis(analysis_id: str):
    """Get a specific alert analysis."""
    analysis_file = _get_analysis_dir() / f"{analysis_id}.json"

    if not analysis_file.exists():
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")

    return json.loads(analysis_file.read_text(encoding="utf-8"))


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
