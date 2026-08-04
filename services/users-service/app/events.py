"""Handlers de eventos (consumer). Se registran en HANDLERS por tipo de evento."""
from shared.events.consumer import EventHandler

HANDLERS: dict[str, EventHandler] = {}
