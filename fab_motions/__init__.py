"""Search canonical Financial Advisory Board packets for recorded motions."""

from .models import MotionOutcome, MotionRecord, PacketSource
from .scanner import (
    deduplicate_motion_records,
    filter_motion_records,
    iter_fab_packet_sources,
    scan_fab_archive,
    scan_minutes_packet,
    scan_page_texts,
)

__all__ = [
    "MotionOutcome",
    "MotionRecord",
    "PacketSource",
    "deduplicate_motion_records",
    "filter_motion_records",
    "iter_fab_packet_sources",
    "scan_fab_archive",
    "scan_minutes_packet",
    "scan_page_texts",
]
