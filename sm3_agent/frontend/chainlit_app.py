import chainlit as cl
from chainlit.input_widget import Select
import uuid

from backend.app.config import get_settings
from backend.app.grafana_servers import get_grafana_server_manager
from backend.agents.agent_manager import AgentManager
from backend.utils.logger import get_logger


settings = get_settings()
agent_manager = AgentManager(settings=settings)
server_manager = get_grafana_server_manager()
logger = get_logger(__name__)

# Initialize agent on startup
_initialized = False


async def ensure_initialized(server_name: str = None):
    """Ensure agent is initialized before handling messages."""
    global _initialized
    
    # Get the selected server URL
    if server_name:
        server = server_manager.get_server(server_name)
        server_url = server.url if server else None
    else:
        server = server_manager.get_default()
        server_url = server.url if server else None
        server_name = server.name if server else "Default"
    
    if not _initialized or agent_manager.get_current_server_url() != server_url:
        logger.info(f"Initializing Grafana MCP agent for Chainlit with server: {server_name}")
        await agent_manager.initialize(server_url=server_url)
        agent_manager._current_server_name = server_name
        _initialized = True
        logger.info("Agent initialization complete")


@cl.on_chat_start
async def start():
    """Initialize chat session when user connects."""
    # Get server choices for the dropdown
    server_names = server_manager.get_server_names()
    default_server = server_manager.get_default()
    default_name = default_server.name if default_server else server_names[0] if server_names else "Local"
    
    # Create settings with server selector
    settings_widgets = [
        Select(
            id="grafana_server",
            label="🎯 Grafana Server",
            description="Select which Grafana instance to connect to",
            values=server_names,
            initial_value=default_name
        )
    ]
    
    await cl.ChatSettings(settings_widgets).send()
    
    # Initialize with default server
    await ensure_initialized(default_name)

    # Generate unique session ID for this chat
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("current_server", default_name)

    logger.info(f"New chat session started: {session_id} with server: {default_name}")

    # Get server info for welcome message
    current_server = server_manager.get_server(default_name)
    server_info = f"**Connected to:** {default_name}"
    if current_server and current_server.description:
        server_info += f" ({current_server.description})"

    welcome_message = f"""👋 Welcome to the Grafana MCP Assistant!

{server_info}

I can help you with:
- Querying Prometheus metrics and Loki logs
- Searching and analyzing Grafana dashboards
- Investigating alerts and incidents
- Checking on-call schedules
- And much more!

💡 **Tip:** Use the ⚙️ Settings button to switch between Grafana servers.

What would you like to explore?"""

    await cl.Message(content=welcome_message).send()


@cl.on_settings_update
async def on_settings_update(settings_dict):
    """Handle settings changes, particularly server selection."""
    new_server = settings_dict.get("grafana_server")
    current_server = cl.user_session.get("current_server")
    
    if new_server and new_server != current_server:
        logger.info(f"Switching Grafana server from {current_server} to {new_server}")
        
        # Show a status message
        status_msg = await cl.Message(
            content=f"🔄 Switching to **{new_server}**..."
        ).send()
        
        try:
            # Switch the server
            success = await agent_manager.switch_grafana_server(new_server)
            
            if success:
                cl.user_session.set("current_server", new_server)
                
                # Get server info
                server = server_manager.get_server(new_server)
                server_info = f"**{new_server}**"
                if server and server.description:
                    server_info += f" ({server.description})"
                
                await cl.Message(
                    content=f"✅ Successfully connected to {server_info}\n\nYou can now query this Grafana instance."
                ).send()
            else:
                await cl.Message(
                    content=f"❌ Failed to switch to **{new_server}**. Please check the server configuration."
                ).send()
                
        except Exception as e:
            logger.error(f"Error switching server: {e}", exc_info=True)
            await cl.Message(
                content=f"❌ Error switching server: {str(e)}"
            ).send()


@cl.on_message
async def handle_message(message: cl.Message):
    """Handle incoming user messages."""
    # Get current server from session
    current_server = cl.user_session.get("current_server")
    await ensure_initialized(current_server)

    # Get session ID from user session
    session_id = cl.user_session.get("session_id")
    if session_id is None:
        # Fallback: create session if not exists (shouldn't happen)
        session_id = str(uuid.uuid4())
        cl.user_session.set("session_id", session_id)
        logger.warning(f"Session ID not found, created new one: {session_id}")

    logger.info(f"Processing message for session {session_id}")

    try:
        # Send a processing indicator
        async with cl.Step(name="Processing", type="run") as step:
            result = await agent_manager.run_chat(message.content, session_id=session_id)

            # Log tool calls if any
            if result.tool_calls:
                step.output = f"Used {len(result.tool_calls)} tool(s)"

        # Send the response
        response_content = result.message

        # Add suggestions if available
        if result.suggestions:
            response_content += "\n\n**💡 Suggested follow-ups:**"
            for i, suggestion in enumerate(result.suggestions, 1):
                response_content += f"\n{i}. {suggestion}"

        await cl.Message(content=response_content).send()

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        error_message = f"Sorry, I encountered an error processing your request: {str(e)}"
        await cl.Message(content=error_message).send()
