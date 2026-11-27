import json

import pytest

from drds_udp.protocol import (
    HEADER_SIZE,
    SYNC,
    ApduHeader,
    AsduFormat,
    HeaderError,
    HeaderOverrides,
    StreamFramer,
    build_apdu,
    build_asdu,
    catalog_dict,
    decode_asdu,
    describe_error,
    encode_asdu,
    get_command,
    hex32,
    parse_datagram,
    parse_hex,
    split_apdus,
)


def test_header_layout_matches_spec():
    raw = build_apdu(b"{}", msg_id=0x1234, asdu_format=AsduFormat.JSON, seq=3)
    assert len(raw) == HEADER_SIZE + 2
    assert raw[:4] == bytes.fromhex("EB91EB90")
    assert raw[4:6] == b"\x02\x00"  # length LE
    assert raw[6:8] == b"\x34\x12"  # msg id LE
    assert raw[8] == 0x01  # JSON
    assert raw[9] == 3  # packet seq
    assert raw[10] == 1  # protocol version
    assert raw[11:16] == b"\x00" * 5


def test_header_roundtrip_and_warnings():
    h = ApduHeader(length=10, msg_id=65535, asdu_format=0, seq=255)
    h2 = ApduHeader.unpack(h.pack())
    assert h2 == h
    assert h2.warnings() == []
    bad = ApduHeader(length=1200, msg_id=1, asdu_format=7, version=2, reserved=b"\x01\x00\x00\x00\x00")
    w = " | ".join(bad.warnings())
    assert "unknown ASDU format" in w and "version" in w and "reserved" in w and "1000" in w


def test_bad_sync_raises():
    with pytest.raises(HeaderError):
        ApduHeader.unpack(b"\x00" * 16)


def test_overrides():
    raw = build_apdu(b"x", 1, overrides=HeaderOverrides(msg_id=9, version=7, length=99, reserved_hex="01 02 03 04 05"))
    h = ApduHeader.unpack(raw)
    assert (h.msg_id, h.version, h.length, h.reserved) == (9, 7, 99, b"\x01\x02\x03\x04\x05")


def test_parse_datagram_multi_and_junk():
    a = build_apdu(b'{"a":1}', 1)
    b = build_apdu(b'{"b":2}', 2)
    frames, errors = parse_datagram(b"\xff\xff" + a + b)
    assert [f.header.msg_id for f in frames] == [1, 2]
    assert errors and "junk" in errors[0]


def test_parse_datagram_short_length_warns():
    raw = build_apdu(b"abc", 5, overrides=HeaderOverrides(length=50))
    frames, _ = parse_datagram(raw)
    assert frames[0].body == b"abc"
    assert any("length field says 50" in w for w in frames[0].warnings)


def test_stream_framer_split_and_resync():
    a = build_apdu(b"hello", 1)
    b = build_apdu(b"world!", 2)
    fr = StreamFramer()
    stream = b"\x00\x01" + a + b
    got = []
    for i in range(0, len(stream), 5):  # dribble 5 bytes at a time
        got += fr.feed(stream[i : i + 5])
    assert [g.body for g in got] == [b"hello", b"world!"]
    assert fr.junk_bytes == 2


def test_split_apdus_seq():
    body = b"x" * 2500
    frames = split_apdus(body, msg_id=7)
    hdrs = [ApduHeader.unpack(f) for f in frames]
    assert [h.seq for h in hdrs] == [0, 1, 2]
    assert [h.length for h in hdrs] == [1000, 1000, 500]
    assert all(h.msg_id == 7 for h in hdrs)


def test_json_asdu_roundtrip():
    asdu = build_asdu(1048577, 2097154, {"MotionParam": 1}, time_str="2026-01-01 00:00:00.000")
    body = encode_asdu(asdu, AsduFormat.JSON)
    assert json.loads(body) == asdu
    d = decode_asdu(body, AsduFormat.JSON)
    assert d.ok and d.type == 1048577 and d.command == 2097154 and d.items == {"MotionParam": 1}


def test_xml_asdu_matches_pdf_shape():
    items = {"CustomMode": True, "Led": [{"Type": 0, "Color": [1], "Cycle": 1}, {"Type": 0, "Color": [2], "Cycle": 1}]}
    asdu = build_asdu(1048581, 2097154, items, time_str="2026-01-01 00:00:00.000")
    xml = encode_asdu(asdu, AsduFormat.XML).decode()
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?><PatrolDevice>')
    assert "<CustomMode>true</CustomMode>" in xml
    assert xml.count("<Led>") == 2 and "<Color>1</Color>" in xml
    d = decode_asdu(xml.encode(), AsduFormat.XML)
    assert d.ok and d.type == 1048581
    assert d.items["Led"][1]["Color"] == 2  # single repeated tag -> scalar in XML


def test_xml_empty_items_and_hex_type():
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><PatrolDevice><Type>0x0010 0002</Type>'
           b"<Command>0x00f0 0000</Command><Time>2026-01-01 00:00:00</Time><Items/></PatrolDevice>")
    d = decode_asdu(xml, AsduFormat.XML)
    assert d.ok and d.type == 0x00100002 and d.command == 0x00F00000 and d.items == {}


def test_decode_detects_format_mismatch_and_errors():
    d = decode_asdu(b'{"PatrolDevice":{"Type":1,"Command":2,"Items":{}}}', AsduFormat.XML)
    assert d.ok and d.fmt == "JSON" and d.warnings
    assert not decode_asdu(b'{"PatrolDevice":', AsduFormat.JSON).ok
    assert decode_asdu(b"hello", None).error == "body is neither JSON nor XML"
    assert decode_asdu(b'{"Foo":1}', AsduFormat.JSON).error == "missing root 'PatrolDevice'"


def test_parse_hex_variants():
    assert parse_hex("0xEB 0x91 eb:90") == bytes.fromhex("EB91EB90")
    dump = "0000   eb 91 eb 90 02 00 01 00 01 00 01 00 00 00 00 00   ................\n0010   7b 7d   {}"
    assert parse_hex(dump) == bytes.fromhex("EB91EB90020001000100010000000000") + b"{}"


def test_catalog_codes_match_pdf():
    assert hex32(1048676) == "0x0010 0064"
    assert get_command("heartbeat").type == 1048676 and get_command("heartbeat").command == 5
    assert get_command("usage_mode").command == 5242882
    assert get_command("motion_state").command == 2097154
    assert get_command("gait").command == 3145730
    assert get_command("axis").command == 1048578 and get_command("axis").response == "none"
    assert get_command("velocity").command == 1114114
    assert get_command("vel_pos").command == 1179650
    assert (get_command("lights").type, get_command("lights").command) == (1048581, 2097154)
    assert (get_command("charging").type, get_command("charging").command) == (1048580, 1048578)
    assert get_command("sdk_mode").command == 3145730
    assert get_command("sleep").command == 4194306
    assert get_command("location_init").command == 2097154
    assert get_command("location_get").command == 2097153
    assert get_command("nav_perception").command == 1114113
    assert get_command("nav_task").command == 1048578
    assert get_command("nav_cancel").command == 1048580
    assert get_command("nav_state").command == 1048577
    cat = catalog_dict()
    assert len(cat["commands"]) == 17 and len(cat["reports"]) == 5
    json.dumps(cat)  # serializable


def test_describe_error():
    assert describe_error(0)["ok"] is True
    assert describe_error(57347)["label"] == "Unsupported protocol type"
    assert describe_error(0xA328)["table"] == "navigation"
    assert describe_error(12345)["label"] == "Unknown code"


def test_sync_constant():
    assert SYNC == b"\xeb\x91\xeb\x90"
