from functools import lru_cache
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized configuration for the chat backend."""

    # Required settings
    openai_api_key: str = Field(..., env="OPENAI_API_KEY", description="OpenAI API key for LLM")

    # MCP Server configuration
    mcp_server_url: str = Field(
        "http://localhost:3001/mcp",
        env="MCP_SERVER_URL",
        description="URL of the Grafana MCP server"
    )
    mcp_server_urls: Union[str, List[str]] = Field(
        default="",
        env="MCP_SERVER_URLS",
        description="Comma-separated list of additional MCP server URLs"
    )
    mcp_server_names: Union[str, List[str]] = Field(
        default="",
        env="MCP_SERVER_NAMES",
        description="Comma-separated list of MCP server labels"
    )
    mcp_execution_mode: str = Field(
        "suggest",
        env="MCP_EXECUTION_MODE",
        description="Execution mode for command tools: suggest or execute"
    )
    mcp_command_allowlist: Union[str, List[str]] = Field(
        default="ping,curl,nmap,snmpwalk,sshprobe",
        env="MCP_COMMAND_ALLOWLIST",
        description="Comma-separated allowlist for command execution tools"
    )
    mcp_audit_dir: str = Field(
        "mcp-audit",
        env="MCP_AUDIT_DIR",
        description="Directory to write MCP command audit logs"
    )

    # LLM configuration
    model: str = Field("gpt-4o", env="OPENAI_MODEL", description="OpenAI model to use")
    enable_tracing: bool = Field(
        False,
        env="ENABLE_LANGCHAIN_TRACING",
        description="Enable LangChain tracing for debugging"
    )

    # Alert analysis storage
    kb_dir: str = Field(
        "kb",
        env="KB_DIR",
        description="Path to local knowledge base files for alert analysis"
    )
    alert_analysis_dir: str = Field(
        "alert-analyses",
        env="ALERT_ANALYSIS_DIR",
        description="Path to store alert analysis outputs"
    )
    
    # Webhook configuration
    webhook_base_url: Optional[str] = Field(
        None,
        env="WEBHOOK_BASE_URL",
        description="Public URL base for webhooks (e.g., https://sm3.example.com). If not set, defaults to http://localhost:8000"
    )

    # CORS configuration
    cors_origins: Union[str, List[str]] = Field(
        default="http://localhost:3000,http://localhost:8001",
        env="CORS_ORIGINS",
        description="Allowed CORS origins (comma-separated string or list)"
    )
    cors_allow_credentials: bool = Field(
        True,
        env="CORS_ALLOW_CREDENTIALS",
        description="Allow credentials in CORS requests"
    )

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_api_key(cls, v: str) -> str:
        """Validate that OpenAI API key is not empty."""
        if not v or v.strip() == "":
            raise ValueError("OPENAI_API_KEY must be set and not empty")
        if not v.startswith("sk-"):
            raise ValueError("OPENAI_API_KEY must start with 'sk-'")
        return v

    @field_validator("mcp_server_url")
    @classmethod
    def validate_mcp_server_url(cls, v: str) -> str:
        """Validate that MCP server URL is a valid HTTP(S) URL."""
        if not v or v.strip() == "":
            raise ValueError("MCP_SERVER_URL must be set and not empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError("MCP_SERVER_URL must start with http:// or https://")
        return v

    @field_validator("mcp_execution_mode")
    @classmethod
    def validate_mcp_execution_mode(cls, v: str) -> str:
        mode = v.strip().lower()
        if mode not in {"suggest", "execute"}:
            raise ValueError("MCP_EXECUTION_MODE must be 'suggest' or 'execute'")
        return mode

    @field_validator("cors_origins", mode="after")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            # Split by comma and strip whitespace
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("mcp_server_urls", mode="after")
    @classmethod
    def parse_mcp_server_urls(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [url.strip() for url in v.split(",") if url.strip()]
        return v

    @field_validator("mcp_server_names", mode="after")
    @classmethod
    def parse_mcp_server_names(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [name.strip() for name in v.split(",") if name.strip()]
        return v

    @field_validator("mcp_command_allowlist", mode="after")
    @classmethod
    def parse_mcp_command_allowlist(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [cmd.strip() for cmd in v.split(",") if cmd.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Disable JSON parsing for complex types from env vars
        env_parse_enums=True,
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance with validation."""
    return Settings()
