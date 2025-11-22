from typing import Any, Dict
from broker_interface import BrokerInterface

def get_broker(name: str, **kwargs: Dict[str, Any]) -> BrokerInterface:
    """Return a broker implementation by name."""
    if name.lower() == "questrade":
        from questrade_api import QuestradeBroker
        return QuestradeBroker(**kwargs)
    elif name.lower() == "ibkr":
        from ibkr_api import IBKRBroker
        return IBKRBroker(**kwargs)
    else:
        raise ValueError(f"Unsupported broker: {name}")