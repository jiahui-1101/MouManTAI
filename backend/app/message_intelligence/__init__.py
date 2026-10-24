"""Side-effect-free C3 message-intelligence adapters and candidate contracts."""

__all__ = ["MessageIntelligenceService"]


def __getattr__(name):
    if name == "MessageIntelligenceService":
        from .service import MessageIntelligenceService
        return MessageIntelligenceService
    raise AttributeError(name)
