import chainlit as cl
import uuid

from backend.app.config import get_settings
from backend.agents.agent_manager import AgentManager
from backend.utils.logger import get_logger


settings = get_settings()
agent_manager = AgentManager(settings=settings)
logger = get_logger(__name__)

# Initialize agent on startup
_initialized = False


async def ensure_initialized():
    """Ensure agent is initialized before handling messages."""
    global _initialized
    if not _initialized:
        logger.info("Initializing Grafana MCP agent for Chainlit")
        await agent_manager.initialize()
        _initialized = True
        logger.info("Agent initialization complete")


@cl.on_chat_start
async def start():
    """Initialize chat session when user connects."""
    await ensure_initialized()

    # Generate unique session ID for this chat
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)

    logger.info(f"New chat session started: {session_id}")

    welcome_message = """👋 Welcome to the Grafana MCP Assistant!

I can help you with:
- Querying Prometheus metrics and Loki logs
- Searching and analyzing Grafana dashboards
- Investigating alerts and incidents
- Checking on-call schedules
- And much more!

What would you like to explore?"""

    await cl.Message(content=welcome_message).send()


@cl.on_message
async def handle_message(message: cl.Message):
    """Handle incoming user messages."""
    await ensure_initialized()

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
