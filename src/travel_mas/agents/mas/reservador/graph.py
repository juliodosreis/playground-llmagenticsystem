"""Subgrafo privado do reservador."""

from ..agent import build_agent
from ..contracts import Relatorio
from .prompts import SYSTEM_PROMPT

TOOL_NAMES = ("create_booking", "get_booking", "list_bookings", "cancel_booking")


def build_graph(model, toolbox, context):
    return build_agent(model, toolbox.select(*TOOL_NAMES), SYSTEM_PROMPT, Relatorio, context)
