from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.agents import Tool as LangChainTool
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
import inspect

from backend.app.config import Settings
from backend.app.mcp_servers import get_mcp_server_manager, Customer, MCPServer
from backend.agents.suggestions import get_suggestion_engine
from backend.containers import get_container_manager, ContainerState, DOCKER_AVAILABLE
from backend.schemas.models import AgentResult
from backend.tools.tool_wrappers import build_mcp_tools, build_mcp_tools_for_servers
from backend.utils.logger import get_logger
from backend.utils.prompts import SYSTEM_PROMPT


logger = get_logger(__name__)
suggestion_engine = get_suggestion_engine()


@dataclass
class CustomerSwitchResult:
    """Result of switching to a customer."""
    success: bool
    customer_name: str
    message: str
    connected_mcps: List[str]  # List of MCP types that connected successfully
    failed_mcps: List[str]  # List of MCP types that failed
    tool_count: int
    is_starting: bool = False  # True if containers are still starting


class AgentManager:
    """Orchestrates LLM calls, tools, and per-session memory using modern LangChain patterns."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = ChatOpenAI(
            model=settings.model,
            temperature=0.1,
            api_key=settings.openai_api_key,
            streaming=True  # Enable streaming for better UX
        )
        self.tools: List[LangChainTool] = []
        self._initialized = False
        self._current_server_url: Optional[str] = None
        self._current_server_name: Optional[str] = None
        self._current_customer: Optional[Customer] = None
        self._current_mcp_servers: List[MCPServer] = []

        # Store separate memory for each session
        self.session_memories: Dict[str, ConversationBufferMemory] = {}

        # Prompt for tool-calling agent (no ReAct text parsing)
        self.prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                SYSTEM_PROMPT + (
                    "\n\n## CRITICAL: Tool Usage Rules"
                    "\n\n1. **NEVER call the same tool twice in a row with the same arguments**"
                    "\n2. **After a tool returns data, USE that data - don't re-call the tool**"
                    "\n3. **For Prometheus queries:**"
                    "\n   - If you already know the datasource UID (like 'prometheus'), use it directly"
                    "\n   - Otherwise, call list_datasources ONCE to get the UID"
                    "\n   - Then immediately use query_prometheus with that UID"
                    "\n4. **For dashboards:**"
                    "\n   - Call search_dashboards ONCE"
                    "\n   - Summarize the results in your response"
                    "\n   - Do NOT call it again unless the user asks a new question"
                    "\n\nThe default Prometheus datasource UID is 'prometheus' - use this if available."
                )
            ),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

    async def initialize(self, server_url: Optional[str] = None) -> None:
        """
        Initialize the agent with MCP tools.

        This must be called before run_chat. It's separate from __init__
        because tool discovery is async.

        Args:
            server_url: Optional specific Grafana MCP server URL to connect to.
                       If not provided, uses the default from settings.
        """
        if self._initialized and server_url == self._current_server_url:
            return

        # If we're switching servers, mark as not initialized
        if server_url != self._current_server_url:
            self._initialized = False
            logger.info(f"Switching Grafana server from {self._current_server_url} to {server_url}")

        logger.info("Initializing agent with MCP tools", extra={"server_url": server_url})
        
        # Temporarily override the settings if a custom URL is provided
        if server_url:
            original_url = self.settings.mcp_server_url
            self.settings.mcp_server_url = server_url
            try:
                self.tools = await build_mcp_tools(settings=self.settings)
            finally:
                self.settings.mcp_server_url = original_url
            self._current_server_url = server_url
        else:
            self.tools = await build_mcp_tools(settings=self.settings)
            self._current_server_url = self.settings.mcp_server_url

        logger.info(f"Agent initialized with {len(self.tools)} tools")
        self._initialized = True

    async def switch_grafana_server(self, server_name: str) -> bool:
        """
        Switch to a different Grafana server by name.
        DEPRECATED: Use switch_customer() instead.

        Args:
            server_name: Name of the server from grafana_servers.json

        Returns:
            True if switch was successful, False otherwise
        """
        # Backwards compatibility - delegate to switch_customer
        result = await self.switch_customer(server_name)
        return result.success
    
    async def switch_customer(self, customer_name: str, use_containers: bool = True) -> CustomerSwitchResult:
        """
        Switch to a different customer, activating ALL their MCP servers.

        This starts containers on-demand for the customer's MCP servers,
        waits for health checks, and makes all tools available to the agent.

        Args:
            customer_name: Name of the customer from mcp_servers.json
            use_containers: Whether to use dynamic container management (default True)

        Returns:
            CustomerSwitchResult with status of the switch
        """
        server_manager = get_mcp_server_manager()
        customer = server_manager.get_customer(customer_name)
        
        if not customer:
            logger.error(f"Unknown customer: {customer_name}")
            return CustomerSwitchResult(
                success=False,
                customer_name=customer_name,
                message=f"Customer '{customer_name}' not found",
                connected_mcps=[],
                failed_mcps=[],
                tool_count=0
            )
        
        logger.info(
            f"Switching to customer: {customer_name} with {len(customer.mcp_servers)} MCP server(s)",
            extra={"server_types": customer.get_server_types(), "has_genesys": customer.has_genesys}
        )
        
        self._current_customer = customer
        self._current_server_name = customer_name
        self._current_mcp_servers = customer.mcp_servers
        self._initialized = False
        
        connected_mcps = []
        failed_mcps = []
        
        # Use dynamic containers if enabled, Docker is available, and config has container settings
        if use_containers and DOCKER_AVAILABLE and server_manager.config.container_settings:
            try:
                container_manager = get_container_manager()
                
                # Configure manager from settings
                cs = server_manager.config.container_settings
                container_manager.configure(
                    max_warm=cs.max_warm_containers,
                    network_name=cs.network_name,
                    health_timeout=cs.health_check_timeout_seconds,
                    health_interval=cs.health_check_interval_seconds,
                    startup_timeout=cs.container_startup_timeout_seconds,
                    port_ranges=cs.port_ranges,
                    images=cs.images,
                )
                
                # Start containers for this customer
                customer_containers = await container_manager.start_customer_containers(
                    customer_name=customer_name,
                    mcp_servers=customer._raw_mcp_servers,
                    wait_for_healthy=True
                )
                
                # Update MCP server URLs from running containers
                container_urls = container_manager.get_container_urls(customer_name)
                for mcp_server in customer.mcp_servers:
                    if mcp_server.type in container_urls:
                        mcp_server.url = container_urls[mcp_server.type]
                        connected_mcps.append(mcp_server.type)
                    else:
                        failed_mcps.append(mcp_server.type)
                
                # Check container states for any failures
                for mcp_type, status in customer_containers.containers.items():
                    if status.state not in (ContainerState.HEALTHY, ContainerState.RUNNING):
                        if mcp_type.value not in failed_mcps:
                            failed_mcps.append(mcp_type.value)
                        logger.warning(
                            f"Container {mcp_type.value} for {customer_name} is {status.state.value}: {status.error_message}"
                        )
                
            except Exception as e:
                logger.error(f"Container management failed for {customer_name}: {e}")
                # Fall back to static URLs if containers fail
                logger.info("Falling back to static MCP URLs")
                for mcp_server in customer.mcp_servers:
                    if mcp_server.url:
                        connected_mcps.append(mcp_server.type)
                    else:
                        failed_mcps.append(mcp_server.type)
        else:
            # Use static URLs from config (legacy mode)
            for mcp_server in customer.mcp_servers:
                if mcp_server.url:
                    connected_mcps.append(mcp_server.type)
                else:
                    failed_mcps.append(mcp_server.type)
        
        # Get the primary Grafana URL for backwards compatibility
        grafana_server = customer.get_server_by_type("grafana")
        if grafana_server:
            self._current_server_url = grafana_server.url
        
        # Build tools from ALL connected MCP servers
        try:
            # Filter to only connected servers
            connected_servers = [s for s in customer.mcp_servers if s.type in connected_mcps and s.url]
            
            if not connected_servers:
                return CustomerSwitchResult(
                    success=False,
                    customer_name=customer_name,
                    message="No MCP servers available",
                    connected_mcps=connected_mcps,
                    failed_mcps=failed_mcps,
                    tool_count=0
                )
            
            self.tools = await build_mcp_tools_for_servers(
                settings=self.settings,
                mcp_servers=connected_servers
            )
            logger.info(f"Customer {customer_name} initialized with {len(self.tools)} tools")
            self._initialized = True
            
            return CustomerSwitchResult(
                success=True,
                customer_name=customer_name,
                message=f"Connected to {len(connected_mcps)} MCP server(s)",
                connected_mcps=connected_mcps,
                failed_mcps=failed_mcps,
                tool_count=len(self.tools)
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize tools for customer {customer_name}: {e}")
            return CustomerSwitchResult(
                success=False,
                customer_name=customer_name,
                message=str(e),
                connected_mcps=connected_mcps,
                failed_mcps=failed_mcps,
                tool_count=0
            )
    
    def get_current_customer(self) -> Optional[Customer]:
        """Get the currently selected customer."""
        return self._current_customer

    def get_current_server_name(self) -> Optional[str]:
        """Get the name of the currently selected Grafana server."""
        return self._current_server_name

    def get_current_server_url(self) -> Optional[str]:
        """Get the URL of the currently selected Grafana server."""
        return self._current_server_url

    def get_or_create_memory(self, session_id: str) -> ConversationBufferMemory:
        """
        Get or create memory for a specific session.

        Each session gets its own isolated conversation history.
        """
        if session_id not in self.session_memories:
            logger.info(f"Creating new memory for session: {session_id}")
            self.session_memories[session_id] = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                output_key="output"
            )
        return self.session_memories[session_id]


    def create_agent_executor(self, memory: ConversationBufferMemory) -> AgentExecutor:
        """
        Create a ReAct agent executor with the given memory.

        Uses the modern create_react_agent pattern instead of deprecated initialize_agent.
        """
        # Create the tool-calling agent to avoid brittle ReAct parsing
        agent = create_tool_calling_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )

        # Wrap in AgentExecutor for execution
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,
            verbose=True,  # Enable verbose to debug tool outputs
            handle_parsing_errors=True,
            max_iterations=10,  # Increased to allow more complex queries
            max_execution_time=90,  # 90 second timeout for complex queries
            return_intermediate_steps=True  # Return tool calls for logging
        )

        return agent_executor

    async def run_chat(self, message: str, session_id: str | None) -> AgentResult:
        """
        Execute a chat turn and return the agent response.

        Args:
            message: User message to process
            session_id: Session identifier for conversation isolation

        Returns:
            AgentResult with the response and any tool calls
        """
        # Ensure agent is initialized
        if not self._initialized:
            await self.initialize()

        # Use a default session if none provided
        if session_id is None:
            session_id = "default"

        # Get session-specific memory
        memory = self.get_or_create_memory(session_id)

        # Create agent executor with session-specific memory
        agent_executor = self.create_agent_executor(memory)

        logger.info(f"Processing message for session: {session_id}")

        try:
            # Execute the agent
            result = await agent_executor.ainvoke({"input": message})

            # Extract the response
            response = result.get("output", "")

            # Extract tool calls from intermediate steps
            tool_calls = []
            last_tool_name = None
            last_tool_args = {}
            last_result = None

            if "intermediate_steps" in result:
                for step in result["intermediate_steps"]:
                    if len(step) >= 2:
                        action, observation = step[0], step[1]

                        # Resolve coroutine observations if any
                        if inspect.iscoroutine(observation):
                            observation = await observation

                        tool_calls.append({
                            "tool": action.tool,
                            "input": action.tool_input,
                            "output": str(observation)[:200]  # Truncate for logging
                        })

                        # Track last tool for suggestions
                        last_tool_name = action.tool
                        last_tool_args = action.tool_input if isinstance(action.tool_input, dict) else {}
                        last_result = observation

            # Generate suggestions based on tool usage
            suggestions = []
            if last_tool_name:
                suggestions = suggestion_engine.generate_suggestions(
                    tool_name=last_tool_name,
                    tool_args=last_tool_args,
                    result=last_result,
                    message=message
                )

            logger.info(f"Completed processing for session {session_id}, used {len(tool_calls)} tools, generated {len(suggestions)} suggestions")

            return AgentResult(message=response, tool_calls=tool_calls, suggestions=suggestions)

        except Exception as e:
            logger.error(f"Error executing agent: {e}", exc_info=True)
            return AgentResult(
                message=f"I encountered an error while processing your request: {str(e)}",
                tool_calls=[],
                suggestions=[]
            )

    async def run_chat_stream(self, message: str, session_id: str | None):
        """
        Execute a chat turn and stream the response.

        Args:
            message: User message to process
            session_id: Session identifier for conversation isolation

        Yields:
            Dict chunks with type and content for streaming
        """
        # Ensure agent is initialized
        if not self._initialized:
            await self.initialize()

        # Use a default session if none provided
        if session_id is None:
            session_id = "default"

        # Get session-specific memory
        memory = self.get_or_create_memory(session_id)

        # Create agent executor with session-specific memory
        agent_executor = self.create_agent_executor(memory)

        logger.info(f"Processing streaming message for session: {session_id}")

        try:
            # Stream the agent response
            response_text = ""
            tool_calls = []

            async for chunk in agent_executor.astream({"input": message}):
                # Handle different chunk types
                if "actions" in chunk:
                    # Tool execution started
                    for action in chunk["actions"]:
                        tool_name = action.tool
                        tool_input = action.tool_input
                        if inspect.iscoroutine(tool_input):
                            tool_input = await tool_input

                        yield {
                            "type": "tool",
                            "status": "executing",
                            "tool": tool_name,
                            "arguments": tool_input,
                        }

                        tool_calls.append({
                            "tool": tool_name,
                            "arguments": tool_input
                        })

                elif "steps" in chunk:
                    # Tool execution completed
                    for step in chunk["steps"]:
                        # LangChain may return an AgentStep object or a tuple/list
                        action = getattr(step, "action", None)
                        observation = getattr(step, "observation", None)

                        if action is None and isinstance(step, (tuple, list)) and len(step) >= 2:
                            action, observation = step[0], step[1]

                        if action is None:
                            continue

                        # Resolve coroutine observations if any
                        if inspect.iscoroutine(observation):
                            observation = await observation

                        yield {
                            "type": "tool",
                            "status": "completed",
                            "tool": action.tool,
                            "arguments": getattr(action, "tool_input", None),
                            "result": observation,
                        }

                        # Attach observation output to the most recent matching tool call
                        logger.info(
                            f"[DEBUG] Tool completed - tool={action.tool}, "
                            f"observation_length={len(str(observation))}, "
                            f"observation_preview='{str(observation)[:100]}...'"
                        )
                        for existing in reversed(tool_calls):
                            if existing.get("tool") == action.tool and "output" not in existing:
                                existing["output"] = str(observation)[:200]
                                logger.info(f"[DEBUG] Attached observation to existing tool call: {action.tool}")
                                break
                        else:
                            tool_calls.append({
                                "tool": action.tool,
                                "input": getattr(action, "tool_input", None),
                                "output": str(observation)[:200]
                            })
                            logger.info(f"[DEBUG] Created new tool call entry: {action.tool}")

                elif "output" in chunk:
                    # Final output
                    response_text = chunk["output"]
                    logger.info(
                        f"[DEBUG] Output chunk received for session {session_id}: "
                        f"length={len(response_text)}, "
                        f"first_100_chars='{response_text[:100]}...', "
                        f"tool_calls_count={len(tool_calls)}"
                    )

                    # Don't stream word-by-word - just send the complete response as one token
                    # This avoids spacing issues and ensures frontend gets exact content
                    yield {
                        "type": "token",
                        "message": response_text
                    }

            # Send completion event
            logger.info(
                f"[DEBUG] Sending complete event - session={session_id}, "
                f"response_length={len(response_text)}, "
                f"tool_calls_count={len(tool_calls)}, "
                f"response_preview='{response_text[:200]}...'"
            )
            yield {
                "type": "complete",
                "message": response_text,
                "tool_calls": tool_calls
            }

            logger.info(f"Completed streaming for session {session_id}, used {len(tool_calls)} tools")

        except Exception as e:
            logger.error(f"Error in streaming chat: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"I encountered an error: {str(e)}"
            }
