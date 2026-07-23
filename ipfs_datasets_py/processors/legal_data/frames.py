"""Compatibility exports for frame-based evidence aggregation primitives."""

try:
    from lib.formal_logic.frames import Frame, FrameKnowledgeBase, FrameSlotEvidence
except ImportError:  # pragma: no cover - standalone ipfs_datasets_py fallback
    from dataclasses import dataclass, field
    from typing import Any, Dict, List, Set

    @dataclass
    class FrameSlotEvidence:
        value: Any
        sources: Set[str] = field(default_factory=set)

        def to_dict(self) -> Dict[str, Any]:
            return {"value": self.value, "sources": sorted(self.sources)}


    @dataclass
    class Frame:
        name: str
        slots: Dict[str, List[FrameSlotEvidence]] = field(default_factory=dict)

        def add(self, slot: str, value: Any, source: str) -> None:
            entries = self.slots.setdefault(slot, [])
            for entry in entries:
                if entry.value == value:
                    entry.sources.add(source)
                    return
            entries.append(FrameSlotEvidence(value=value, sources={source}))

        def get_values(self, slot: str) -> List[Any]:
            return [entry.value for entry in self.slots.get(slot, [])]

        def to_dict(self) -> Dict[str, Any]:
            return {
                "name": self.name,
                "slots": {
                    slot: [entry.to_dict() for entry in values]
                    for slot, values in sorted(self.slots.items())
                },
            }


    class FrameKnowledgeBase:
        def __init__(self) -> None:
            self.frames: Dict[str, Frame] = {}

        def ensure_frame(self, frame_id: str, name: str) -> Frame:
            frame = self.frames.get(frame_id)
            if frame is None:
                frame = Frame(name=name)
                self.frames[frame_id] = frame
            return frame

        def add_fact(self, frame_id: str, name: str, slot: str, value: Any, source: str) -> None:
            self.ensure_frame(frame_id, name).add(slot, value, source)

        def frame_count(self) -> int:
            return len(self.frames)

        def to_dict(self) -> Dict[str, Any]:
            return {frame_id: frame.to_dict() for frame_id, frame in sorted(self.frames.items())}


__all__ = ["Frame", "FrameKnowledgeBase", "FrameSlotEvidence"]
