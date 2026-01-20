"""
Webhook Manager Service.

Manages webhook registration status and provides webhook URLs for customers.
AlertManager webhooks are configured via alertmanager.yml - this service tracks
the expected configuration and validates connectivity.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from backend.app.config import get_settings
from backend.app.mcp_servers import get_mcp_server_manager
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class WebhookStatus(Enum):
    """Webhook registration status."""
    UNKNOWN = "unknown"  # Not yet checked
    CONFIGURED = "configured"  # Webhook is properly configured and working
    PENDING = "pending"  # Waiting for first alert
    ERROR = "error"  # Configuration error or unreachable
    NOT_CONFIGURED = "not_configured"  # Webhook not set up in AlertManager


@dataclass
class CustomerWebhook:
    """Webhook configuration for a customer."""
    customer_name: str
    webhook_url: str  # The URL AlertManager should POST to
    alertmanager_url: str  # The customer's AlertManager URL
    status: WebhookStatus = WebhookStatus.UNKNOWN
    last_alert_received: Optional[datetime] = None
    total_alerts_received: int = 0
    last_check: Optional[datetime] = None
    last_error: Optional[str] = None
    config_instructions: Optional[str] = None


@dataclass
class WebhookValidationResult:
    """Result of webhook validation."""
    customer_name: str
    is_valid: bool
    alertmanager_reachable: bool
    webhook_configured: bool
    error: Optional[str] = None


class WebhookManager:
    """
    Manages webhook registrations for all customers.
    
    Since AlertManager webhooks are configured via alertmanager.yml (not API),
    this manager:
    1. Tracks expected webhook configurations
    2. Provides webhook URLs for each customer
    3. Validates AlertManager connectivity
    4. Tracks alert reception status
    """
    
    _instance: Optional["WebhookManager"] = None
    
    def __init__(self):
        self._webhooks: Dict[str, CustomerWebhook] = {}
        self._settings = get_settings()
        self._initialized = False
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "WebhookManager":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _get_webhook_base_url(self) -> str:
        """Get the base URL for webhooks (this server's public URL)."""
        # In production, this would be the public URL of the SM3 agent
        # For dev, we use the configured value or default
        return self._settings.webhook_base_url or "http://localhost:8000"
    
    def _get_webhook_url(self, customer_name: str) -> str:
        """Get the webhook URL for a customer."""
        base = self._get_webhook_base_url()
        return f"{base}/api/alerts/ingest/{customer_name}"
    
    def _build_config_instructions(self, customer_name: str, webhook_url: str) -> str:
        """Build AlertManager configuration instructions."""
        return f"""# AlertManager Webhook Configuration for {customer_name}
# Add this to your alertmanager.yml receivers section:

receivers:
  - name: 'sm3-webhook'
    webhook_configs:
      - url: '{webhook_url}'
        send_resolved: true
        http_config:
          # Optional: Add basic auth if required
          # basic_auth:
          #   username: 'sm3'
          #   password: 'your-password'

# Then reference this receiver in your route:
route:
  receiver: 'sm3-webhook'
  # Or add it as a sub-route for specific alerts
  routes:
    - match_re:
        severity: critical|major
      receiver: 'sm3-webhook'
      continue: true
"""
    
    async def initialize(self) -> None:
        """Initialize webhook manager with all customer configurations."""
        async with self._lock:
            if self._initialized:
                return
            
            logger.info("Initializing webhook manager...")
            server_manager = get_mcp_server_manager()
            customer_names = server_manager.get_customer_names()
            
            for customer_name in customer_names:
                customer = server_manager.get_customer(customer_name)
                if not customer:
                    continue
                
                # Get AlertManager URL from customer config
                alertmanager_url = None
                for mcp_server in customer.mcp_servers:
                    if mcp_server.type == "alertmanager":
                        # URL can be in mcp_server.url or in config.alertmanager_url
                        alertmanager_url = mcp_server.url or mcp_server.config.get("alertmanager_url")
                        break
                
                if not alertmanager_url:
                    logger.debug(f"No AlertManager configured for {customer_name}")
                    continue
                
                webhook_url = self._get_webhook_url(customer_name)
                
                self._webhooks[customer_name] = CustomerWebhook(
                    customer_name=customer_name,
                    webhook_url=webhook_url,
                    alertmanager_url=alertmanager_url,
                    status=WebhookStatus.UNKNOWN,
                    config_instructions=self._build_config_instructions(customer_name, webhook_url)
                )
                
                logger.info(f"Registered webhook config for {customer_name}: {webhook_url}")
            
            self._initialized = True
            logger.info(f"Webhook manager initialized with {len(self._webhooks)} customers")
    
    def get_webhook(self, customer_name: str) -> Optional[CustomerWebhook]:
        """Get webhook configuration for a customer."""
        return self._webhooks.get(customer_name)
    
    def get_all_webhooks(self) -> List[CustomerWebhook]:
        """Get all webhook configurations."""
        return list(self._webhooks.values())
    
    def record_alert_received(self, customer_name: str) -> None:
        """Record that an alert was received for a customer."""
        webhook = self._webhooks.get(customer_name)
        if webhook:
            webhook.last_alert_received = datetime.utcnow()
            webhook.total_alerts_received += 1
            webhook.status = WebhookStatus.CONFIGURED
            webhook.last_error = None
    
    def record_error(self, customer_name: str, error: str) -> None:
        """Record an error for a customer webhook."""
        webhook = self._webhooks.get(customer_name)
        if webhook:
            webhook.status = WebhookStatus.ERROR
            webhook.last_error = error
    
    async def validate_alertmanager(self, customer_name: str) -> WebhookValidationResult:
        """
        Validate AlertManager connectivity for a customer.
        
        Note: We can't validate webhook configuration via API since it's in
        alertmanager.yml. We can only check if AlertManager is reachable.
        """
        webhook = self._webhooks.get(customer_name)
        if not webhook:
            return WebhookValidationResult(
                customer_name=customer_name,
                is_valid=False,
                alertmanager_reachable=False,
                webhook_configured=False,
                error=f"No webhook configuration for {customer_name}"
            )
        
        try:
            import httpx
            
            # Try to reach AlertManager status endpoint
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                # AlertManager API v2 status endpoint
                url = f"{webhook.alertmanager_url}/api/v2/status"
                response = await client.get(url)
                
                webhook.last_check = datetime.utcnow()
                
                if response.status_code == 200:
                    # If we've received alerts, it's configured
                    is_configured = webhook.total_alerts_received > 0
                    webhook.status = WebhookStatus.CONFIGURED if is_configured else WebhookStatus.PENDING
                    
                    return WebhookValidationResult(
                        customer_name=customer_name,
                        is_valid=True,
                        alertmanager_reachable=True,
                        webhook_configured=is_configured
                    )
                elif response.status_code in (401, 403):
                    # Auth required - AlertManager is reachable but we can't access API directly
                    # This is OK - the webhook works in the opposite direction (AM calls us)
                    is_configured = webhook.total_alerts_received > 0
                    webhook.status = WebhookStatus.CONFIGURED if is_configured else WebhookStatus.PENDING
                    
                    return WebhookValidationResult(
                        customer_name=customer_name,
                        is_valid=True,
                        alertmanager_reachable=True,
                        webhook_configured=is_configured,
                        error=f"AlertManager reachable (auth required for API access)"
                    )
                else:
                    webhook.status = WebhookStatus.ERROR
                    webhook.last_error = f"AlertManager returned {response.status_code}"
                    return WebhookValidationResult(
                        customer_name=customer_name,
                        is_valid=False,
                        alertmanager_reachable=False,
                        webhook_configured=False,
                        error=f"AlertManager returned {response.status_code}"
                    )
                    
        except Exception as e:
            webhook.status = WebhookStatus.ERROR
            webhook.last_error = str(e)
            return WebhookValidationResult(
                customer_name=customer_name,
                is_valid=False,
                alertmanager_reachable=False,
                webhook_configured=False,
                error=str(e)
            )
    
    async def validate_all(self) -> List[WebhookValidationResult]:
        """Validate all customer AlertManager connections."""
        results = []
        for customer_name in self._webhooks:
            result = await self.validate_alertmanager(customer_name)
            results.append(result)
        return results
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of all webhook statuses."""
        total = len(self._webhooks)
        by_status = {}
        for webhook in self._webhooks.values():
            status = webhook.status.value
            by_status[status] = by_status.get(status, 0) + 1
        
        recent_alerts = sum(1 for w in self._webhooks.values() if w.total_alerts_received > 0)
        
        return {
            "total_customers": total,
            "by_status": by_status,
            "customers_with_alerts": recent_alerts,
            "webhook_base_url": self._get_webhook_base_url()
        }


def get_webhook_manager() -> WebhookManager:
    """Get the webhook manager singleton."""
    return WebhookManager.get_instance()
