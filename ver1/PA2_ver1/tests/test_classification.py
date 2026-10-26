import pytest

from pa2.domain.classification import classify_part, normalized_stem
from pa2.domain.models import PartType


@pytest.mark.parametrize(("name", "expected"), [
    ("MBD-KD000.STP", PartType.BODY), (" plt-kd000.step ", PartType.PLATE),
    ("BLK-KD000.STP", PartType.BLOCK), ("BUS-KD100.STP", PartType.BUSBAR),
    ("RLY-KET400.STP", PartType.RELAY), ("COV-KD000.STP", PartType.COVER),
    ("SEL-KD000.STP", PartType.SEAL), ("AIR-BENT0A.STP", PartType.VENT),
    ("BLT-WASM612A.STP", PartType.BOLT), ("NUT-FLGM5A.STP", PartType.NUT),
    ("HVSC   2800.STP", PartType.HV_CONNECTOR), ("lv cont.step", PartType.LV_CONNECTOR),
    ("XBUS-KD100.STP", PartType.UNKNOWN), ("LV CONT extra.STP", PartType.UNKNOWN),
])
def test_filename_rules(name, expected):
    assert classify_part(name) == expected


def test_normalized_stem_preserves_inner_boundaries():
    assert normalized_stem("  HVSC   2800 .STEP") == "HVSC 2800"


@pytest.mark.parametrize(('name','kind'), [
    ('BOLT_M4_10.step', PartType.BOLT), ('bolt_side_m4_12_s09.STEP', PartType.BOLT),
    ('NUT_M5.step', PartType.NUT), ('SCREW_M3_12.step', PartType.BOLT),
    ('BUS_N_IN.step', PartType.BUSBAR), ('HSG_DRUM_S08.step', PartType.BODY),
    ('CARRIER_ANNULAR_S08.step', PartType.PLATE), ('COVER_HALF_S08.step', PartType.COVER),
    ('GASKET_RING_S08.step', PartType.SEAL), ('HV_CASE_2P_S08.step', PartType.HV_CONNECTOR),
    ('HV_SOCKET_CONTACT.step', PartType.HV_CONNECTOR), ('HV_PIN_S10.step', PartType.HV_CONNECTOR),
    ('LV_REAR_SOCKET_S03.step', PartType.LV_CONNECTOR), ('LV_SOCKET.step', PartType.LV_CONNECTOR),
    ('CONTACTOR_BODY.step', PartType.RELAY), ('CONTACTOR_S10.step', PartType.RELAY),
    ('PRE_RELAY_S08.step', PartType.RELAY), ('PRECHARGE_RELAY_BODY.step', PartType.RELAY),
    ('CONTACTOR_TERMINAL.step', PartType.UNKNOWN), ('FUSE_CERAMIC.step', PartType.UNKNOWN),
    ('CONTROL_PCB.step', PartType.UNKNOWN), ('RESISTOR_CERAMIC.step', PartType.UNKNOWN),
    ('XBUS_N_IN.step', PartType.UNKNOWN), ('BOLTED_BRACKET.step', PartType.UNKNOWN),
    ('MY_BOLT_M4.step', PartType.UNKNOWN), ('HV_CABLE.step', PartType.UNKNOWN),
])
def test_bounded_aliases_preserve_general_parts(name, kind):
    assert classify_part(name) == kind

