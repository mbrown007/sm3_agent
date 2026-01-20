"""
API endpoints for webhook management.

Provides endpoints for viewing webhook configurations, status, and configuration instructions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.services.webhook_manager import get_webhook_manager, WebhookStatus
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Response Models
class WebhookConfigResponse(BaseModel):
    """Webhook configuration for a customer."""
    customer_name: str
    webhook_url: str
    alertmanager_url: str
    status: str
    last_alert_received: Optional[str] = None
    total_alerts_received: int = 0
    last_check: Optional[str] = None
    last_error: Optional[str] = None


class WebhookConfigDetailResponse(WebhookConfigResponse):
    """Detailed webhook configuration including setup instructions."""
    config_instructions: str


class WebhookStatusSummaryResponse(BaseModel):
    """Summary of all webhook statuses."""
    total_customers: int
    by_status: Dict[str, int]
    customers_with_alerts: int
    webhook_base_url: str


class WebhookValidationResponse(BaseModel):
    """Result of webhook validation."""
    customer_name: str
    is_valid: bool
    alertmanager_reachable: bool
    webhook_configured: bool
    error: Optional[str] = None


class AllWebhooksResponse(BaseModel):
    """Response containing all webhook configurations."""
    webhooks: List[WebhookConfigResponse]
    summary: WebhookStatusSummaryResponse


@router.get("", response_model=AllWebhooksResponse)
async def list_webhooks():
    """
    List all customer webhook configurations.
    
    Returns webhook URLs, AlertManager URLs, and status for each customer.
    """
    manager = get_webhook_manager()
    
    # Ensure initialized
    await manager.initialize()
    
    webhooks = manager.get_all_webhooks()
    
    webhook_list = [
        WebhookConfigResponse(
            customer_name=w.customer_name,
            webhook_url=w.webhook_url,
            alertmanager_url=w.alertmanager_url,
            status=w.status.value,
            last_alert_received=w.last_alert_received.isoformat() if w.last_alert_received else None,
            total_alerts_received=w.total_alerts_received,
            last_check=w.last_check.isoformat() if w.last_check else None,
            last_error=w.last_error
        )
        for w in webhooks
    ]
    
    summary = manager.get_status_summary()
    
    return AllWebhooksResponse(
        webhooks=webhook_list,
        summary=WebhookStatusSummaryResponse(**summary)
    )


@router.get("/summary", response_model=WebhookStatusSummaryResponse)
async def get_webhook_summary():
    """
    Get summary of webhook statuses.
    
    Returns counts by status and overall statistics.
    """
    manager = get_webhook_manager()
    await manager.initialize()
    
    summary = manager.get_status_summary()
    return WebhookStatusSummaryResponse(**summary)


@router.get("/{customer_name}", response_model=WebhookConfigDetailResponse)
async def get_webhook_config(customer_name: str):
    """
    Get webhook configuration for a specific customer.
    
    Includes AlertManager configuration instructions.
    """
    manager = get_webhook_manager()
    await manager.initialize()
    
    webhook = manager.get_webhook(customer_name)
    if not webhook:
        raise HTTPException(
            status_code=404,
            detail=f"No webhook configuration for customer: {customer_name}"
        )
    
    return WebhookConfigDetailResponse(
        customer_name=webhook.customer_name,
        webhook_url=webhook.webhook_url,
        alertmanager_url=webhook.alertmanager_url,
        status=webhook.status.value,
        last_alert_received=webhook.last_alert_received.isoformat() if webhook.last_alert_received else None,
        total_alerts_received=webhook.total_alerts_received,
        last_check=webhook.last_check.isoformat() if webhook.last_check else None,
        last_error=webhook.last_error,
        config_instructions=webhook.config_instructions or ""
    )


@router.post("/{customer_name}/validate", response_model=WebhookValidationResponse)
async def validate_webhook(customer_name: str):
    """
    Validate AlertManager connectivity for a customer.
    
    Checks if the customer's AlertManager is reachable.
    Note: Cannot validate webhook configuration since it's in alertmanager.yml.
    """
    manager = get_webhook_manager()
    await manager.initialize()
    
    webhook = manager.get_webhook(customer_name)
    if not webhook:
        raise HTTPException(
            status_code=404,
            detail=f"No webhook configuration for customer: {customer_name}"
        )
    
    result = await manager.validate_alertmanager(customer_name)
    
    return WebhookValidationResponse(
        customer_name=result.customer_name,
        is_valid=result.is_valid,
        alertmanager_reachable=result.alertmanager_reachable,
        webhook_configured=result.webhook_configured,
        error=result.error
    )


@router.post("/validate-all", response_model=List[WebhookValidationResponse])
async def validate_all_webhooks(background_tasks: BackgroundTasks):
    """
    Validate AlertManager connectivity for all customers.
    
    Runs validation for each customer's AlertManager.
    """
    manager = get_webhook_manager()
    await manager.initialize()
    
    results = await manager.validate_all()
    
    return [
        WebhookValidationResponse(
            customer_name=r.customer_name,
            is_valid=r.is_valid,
            alertmanager_reachable=r.alertmanager_reachable,
            webhook_configured=r.webhook_configured,
            error=r.error
        )
        for r in results
    ]


@router.get("/{customer_name}/instructions")
async def get_webhook_instructions(customer_name: str):
    """
    Get AlertManager configuration instructions for a customer.
    
    Returns YAML configuration snippet to add to alertmanager.yml.
    """
    manager = get_webhook_manager()
    await manager.initialize()
    
    webhook = manager.get_webhook(customer_name)
    if not webhook:
        raise HTTPException(
            status_code=404,
            detail=f"No webhook configuration for customer: {customer_name}"
        )
    
    return {
        "customer_name": customer_name,
        "webhook_url": webhook.webhook_url,
        "instructions": webhook.config_instructions,
        "alertmanager_url": webhook.alertmanager_url
    }
