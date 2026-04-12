from .session import Session, SessionABC
from .sqlite_session import SQLiteSession
from .util import SessionInputCallback

# Fixed import for OpenAIConversationsSession
try:
    from .openai_conversations_session import OpenAIConversationsSession
    _OPENAI_CONVERSATIONS_AVAILABLE = True
except ImportError:
    # Create a placeholder if the import fails
    class OpenAIConversationsSession:
        """Placeholder for OpenAIConversationsSession when not available"""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "OpenAIConversationsSession is not available. "
                "This may be due to missing dependencies or compatibility issues."
            )
    _OPENAI_CONVERSATIONS_AVAILABLE = False

__all__ = [
    "Session",
    "SessionABC", 
    "SessionInputCallback",
    "SQLiteSession",
    "OpenAIConversationsSession",
]