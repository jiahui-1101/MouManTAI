"""P1 Real Inbound Channels: Telegram, Gmail, and WhatsApp."""

from .config import ChannelsConfig, GmailChannelConfig, TelegramChannelConfig, WhatsAppChannelConfig
from .gmail import GmailAdapter
from .manager import ChannelManager, get_channel_manager
from .router import router as channels_router
from .state import ChannelStateManager, get_state_manager
from .telegram import TelegramAdapter
from .whatsapp import WhatsAppAdapter

__all__ = [
    "ChannelsConfig",
    "TelegramChannelConfig",
    "GmailChannelConfig",
    "WhatsAppChannelConfig",
    "TelegramAdapter",
    "GmailAdapter",
    "WhatsAppAdapter",
    "ChannelManager",
    "ChannelStateManager",
    "get_channel_manager",
    "get_state_manager",
    "channels_router",
]
