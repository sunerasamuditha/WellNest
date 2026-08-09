import time
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Callable

@dataclass
class TraceEvent:
    timestamp: float
    timestamp_str: str
    agent: str
    event_type: str
    message: str
    data: dict

class TraceCollector:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.events: List[TraceEvent] = []
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []

    def log(self, agent: str, event_type: str, message: str, data: dict = None):
        """
        Record a trace event and broadcast it to active listeners (like SSE streams).
        Strictly emoji-free standard prefix logs.
        """
        now = time.time()
        # Format timestamp as HH:MM:SS.mmm
        time_struct = time.localtime(now)
        ms = int((now - int(now)) * 1000)
        timestamp_str = f"{time.strftime('%H:%M:%S', time_struct)}.{ms:03d}"
        
        event = TraceEvent(
            timestamp=now,
            timestamp_str=timestamp_str,
            agent=agent.upper(),
            event_type=event_type.upper(),
            message=message,
            data=data or {}
        )
        
        self.events.append(event)
        
        # Broadcast event
        event_dict = asdict(event)
        for listener in self._listeners:
            try:
                listener(event_dict)
            except Exception as e:
                print(f"[TraceCollector Broadcast Error]: {e}")

    def add_listener(self, callback: Callable[[Dict[str, Any]], None]):
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[Dict[str, Any]], None]):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_logs(self) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self.events]
