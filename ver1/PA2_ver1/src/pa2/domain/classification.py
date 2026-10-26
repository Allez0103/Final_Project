from __future__ import annotations

import re
from pathlib import Path

from .models import PartType


RULE_VERSION = "filename-rules-v2-token-aliases"


def normalized_stem(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"(?i)\.(stp|step)$", "", name)
    return re.sub(r"\s+", " ", name.strip()).upper()


def classify_part(filename: str) -> PartType:
    value = normalized_stem(filename)
    prefix_rules = (
        ("MBD-", PartType.BODY),
        ("PLT-", PartType.PLATE),
        ("BLK-", PartType.BLOCK),
        ("BUS-", PartType.BUSBAR),
        ("RLY-", PartType.RELAY),
        ("COV-", PartType.COVER),
        ("SEL-", PartType.SEAL),
        ("AIR-", PartType.VENT),
        ("BLT-", PartType.BOLT),
        ("NUT-", PartType.NUT),
    )
    for prefix, part_type in prefix_rules:
        if value.startswith(prefix):
            return part_type
    if re.fullmatch(r"HVSC\s+\S(?:.*\S)?", value):
        return PartType.HV_CONNECTOR
    if value == "LV CONT":
        return PartType.LV_CONNECTOR
    # Keep the supplied CAD's rules above unchanged. Aliases are anchored at
    # token boundaries, never arbitrary substrings such as XBUS or BOLTED.
    alias_rules = (
        (r'(?:BOLT|SCREW|BLT)[_-].+', PartType.BOLT),
        (r'NUT_.+', PartType.NUT),
        (r'(?:HSG|HOUSING|MBD)_.+', PartType.BODY),
        (r'(?:CARRIER|PLT|PLATE)_.+', PartType.PLATE),
        (r'BLK_.+', PartType.BLOCK),
        (r'(?:BUS|BUSBAR)_.+', PartType.BUSBAR),
        (r'(?:RLY|RELAY|PRE_RELAY|PRECHARGE_RELAY)_.+', PartType.RELAY),
        (r'CONTACTOR_(?:BODY|COMPACT|FLAT|RADIAL|ROUND|SECTOR|UPRIGHT|S\d+)(?:_.+)?', PartType.RELAY),
        (r'(?:COVER|COV)_.+', PartType.COVER),
        (r'(?:GASKET|SEAL|SEL)_.+', PartType.SEAL),
        (r'(?:VENT|AIR)_.+', PartType.VENT),
        (r'HV_(?:SOCKET|CASE|DUAL_CASE|CONTACT|PIN)(?:_.+)?', PartType.HV_CONNECTOR),
        (r'LV_(?:SOCKET|REAR_SOCKET|INNER)(?:_.+)?', PartType.LV_CONNECTOR),
    )
    for pattern, part_type in alias_rules:
        if re.fullmatch(pattern, value):
            return part_type
    # Fuses, resistors, PCBs, sensors, terminals and fixtures do not all have
    # corresponding existing enums. UNKNOWN is a usable general part, not a
    # fastener or a failed STEP import. Do not invent an incorrect category.
    return PartType.UNKNOWN

