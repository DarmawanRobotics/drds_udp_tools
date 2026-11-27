"""Machine-readable catalog of every message in Inspection Protocol V1.0.3-0.

The GUI renders request forms from `fields`, the test-suite uses `response`
to know what to expect, and `danger` gates anything that moves the robot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from . import codes as C
from .codes import MsgType, REPORT_COMMAND, hex32

Kind = Literal["int", "float", "bool", "enum", "object", "array", "string"]
Response = Literal["general", "data", "none", "deferred"]
Danger = Literal["safe", "caution", "motion"]


@dataclass
class Field:
    name: str
    kind: Kind
    label: str = ""
    unit: str = ""
    default: Any = None
    enum: dict | None = None  # value -> label
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str = ""
    fields: list["Field"] | None = None  # object members / array item schema
    item_kind: Kind | None = None  # scalar array item kind
    item_labels: list[str] | None = None  # e.g. ["Front light", "Rear light"]
    min_items: int | None = None
    max_items: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.enum is not None:
            d["enum"] = {str(k): v for k, v in self.enum.items()}
        return {k: v for k, v in d.items() if v not in (None, "", [])}


@dataclass
class CommandDef:
    id: str
    section: str
    group: str
    name: str
    type: int
    command: int
    response: Response
    summary: str
    fields: list[Field] = field(default_factory=list)
    example: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    danger: Danger = "safe"
    repeat_hz: float | None = None  # suggested continuous send rate
    response_fields: dict[str, str] = field(default_factory=dict)  # field -> enum key / description

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "section": self.section,
            "group": self.group,
            "name": self.name,
            "type": self.type,
            "command": self.command,
            "type_hex": hex32(self.type),
            "command_hex": hex32(self.command),
            "response": self.response,
            "summary": self.summary,
            "fields": [f.to_dict() for f in self.fields],
            "example": self.example,
            "notes": self.notes,
            "danger": self.danger,
            "repeat_hz": self.repeat_hz,
            "response_fields": self.response_fields,
        }


@dataclass
class ReportDef:
    id: str
    section: str
    name: str
    type: int
    command: int
    hz: float
    root: str  # key inside Items used by dashboards
    summary: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type_hex"] = hex32(self.type)
        d["command_hex"] = hex32(self.command)
        return d


def _axis_fields(normalized: bool, ranges: dict[str, tuple[float, float]] | None = None) -> list[Field]:
    names = [("X", "Forward / backward"), ("Y", "Left / right"), ("Z", "Vertical"),
             ("Roll", "Roll"), ("Pitch", "Pitch"), ("Yaw", "Yaw")]
    out = []
    for n, label in names:
        if normalized:
            lo, hi, unit = -1.0, 1.0, "ratio"
        else:
            lo, hi = (ranges or {}).get(n, (None, None))
            unit = "m/s" if n in ("X", "Y", "Z") else "rad/s"
        out.append(Field(n, "float", label, unit, default=0.0, min=lo, max=hi,
                         step=0.05 if normalized else 0.01))
    return out


_ZERO6 = {"X": 0.0, "Y": 0.0, "Z": 0.0, "Roll": 0.0, "Pitch": 0.0, "Yaw": 0.0}

COMMANDS: list[CommandDef] = [
    # ------------------------------------------------------------ §1.2 Control
    CommandDef(
        id="heartbeat", section="1.2.1", group="Control", name="Heartbeat",
        type=MsgType.STATUS, command=C.HEARTBEAT_COMMAND, response="general",
        summary="Keep-alive. Robot pushes status reports to the IP:port that keeps sending this.",
        example={},
        notes=["Send at >= 1 Hz. After 2 s without heartbeat, active reporting stops and must be re-established.",
               "The debugger runs this automatically when 'Heartbeat' is enabled."],
    ),
    CommandDef(
        id="usage_mode", section="1.2.2", group="Control", name="Usage Mode Switching",
        type=MsgType.DEVICE, command=0x0050_0002, response="general", danger="caution",
        summary="Switch Regular / Navigation / Assist mode.",
        fields=[Field("Mode", "enum", "Usage mode", enum=C.USAGE_MODE, default=0)],
        example={"Mode": 0},
        notes=["Regular mode: axis commands (§1.2.5). Navigation mode: navigation tasks + velocity command (§1.2.6)."],
    ),
    CommandDef(
        id="motion_state", section="1.2.3", group="Control", name="Motion State Switching",
        type=MsgType.MOTION, command=0x0020_0002, response="general", danger="motion",
        summary="Stand / Sit / Soft emergency stop.",
        fields=[Field("MotionParam", "enum", "Motion state", enum=C.MOTION_STATE, default=1)],
        example={"MotionParam": 1},
        notes=["After Stand via ASDU the robot enters RL control automatically (velocity/gait commands allowed)."],
    ),
    CommandDef(
        id="gait", section="1.2.4", group="Control", name="Gait Switching",
        type=MsgType.MOTION, command=0x0030_0002, response="general", danger="caution",
        summary="Switch gait; motion mode follows the gait automatically.",
        fields=[Field("GaitParam", "enum", "Gait", enum=C.GAIT, default=0x1001)],
        example={"GaitParam": 4097},
        notes=["Send only when the robot has fully stopped — otherwise it is buffered until it stops.",
               "Navigation: flat 0x3002; switch to stair 0x3003 BEFORE entering stairs, never on the stairs."],
    ),
    CommandDef(
        id="axis", section="1.2.5", group="Control", name="Motion Control (Axis Command)",
        type=MsgType.MOTION, command=0x0010_0002, response="none", danger="motion", repeat_hz=10,
        summary="Normalized six-axis command [-1, 1] (ratio of max speed).",
        fields=_axis_fields(normalized=True),
        example=dict(_ZERO6),
        notes=["Only in Regular and Assist mode. No response frame.",
               "Basic gait uses X, Y, Yaw only; special gaits use Z/Roll/Pitch/Yaw too.",
               "Commands within 2 s must come from the same client (else E006 on other calls)."],
    ),
    CommandDef(
        id="velocity", section="1.2.6", group="Control", name="Motion Control (Velocity Command)",
        type=MsgType.MOTION, command=0x0011_0002, response="none", danger="motion", repeat_hz=10,
        summary="Real velocity command passed as-is to the executor.",
        fields=_axis_fields(normalized=False, ranges={"X": (-1.67, 1.67), "Y": (-0.4, 0.4), "Yaw": (-1.0, 1.0)}),
        example=dict(_ZERO6),
        notes=["Only in Navigation mode. No response frame.", "X ±1.67 m/s, Y ±0.4 m/s, Yaw ±1.0 rad/s."],
    ),
    CommandDef(
        id="vel_pos", section="1.2.7", group="Control", name="Motion Control (Velocity + Position)",
        type=MsgType.MOTION, command=0x0012_0002, response="general", danger="motion",
        summary="Velocity and position targets in one message (six-axis locomotion gait only).",
        fields=[
            Field("Velocity", "object", "Velocity", fields=[
                Field(n, "float", n, "rad/s" if n in ("Roll", "Pitch", "Yaw") else "m/s", default=0.0, step=0.01)
                for n in ("X", "Y", "Z", "Roll", "Pitch", "Yaw")]),
            Field("Position", "object", "Position", fields=[
                Field(n, "float", n, "rad" if n in ("Roll", "Pitch", "Yaw") else "m", default=0.0, step=0.01)
                for n in ("X", "Y", "Z", "Roll", "Pitch", "Yaw")]),
            Field("Normalized", "bool", "Normalized", default=True,
                  help="true = normalized speed/position, false = real speed/position"),
        ],
        example={"Velocity": {k: 0 for k in _ZERO6}, "Position": {k: 0 for k in _ZERO6}, "Normalized": True},
        notes=["Currently only accepted in the six-axis locomotion gait."],
    ),
    CommandDef(
        id="lights", section="1.2.8", group="Control", name="Custom Light Effects",
        type=MsgType.PERIPHERAL, command=0x0020_0002, response="general",
        summary="Front/rear light mode, color and cycle.",
        fields=[
            Field("CustomMode", "bool", "Custom light effect", default=True),
            Field("Led", "array", "Lights", item_labels=["Front light", "Rear light"], min_items=2, max_items=2,
                  fields=[
                      Field("Type", "enum", "Mode", enum=C.LIGHT_MODE, default=0),
                      Field("Color", "array", "Color", item_kind="enum", enum=C.LIGHT_COLOR, default=[1],
                            min_items=1),
                      Field("Cycle", "int", "Cycle", "s", default=1, min=0,
                            help="Only for Breathing and Flashing modes"),
                  ]),
        ],
        example={"CustomMode": True, "Led": [{"Type": 0, "Color": [1], "Cycle": 1},
                                             {"Type": 0, "Color": [2], "Cycle": 1}]},
        notes=["Led[0] = front light, Led[1] = rear light."],
    ),
    CommandDef(
        id="charging", section="1.2.9", group="Control", name="Autonomous Charging",
        type=MsgType.CHARGING, command=0x0010_0002, response="general", danger="motion",
        summary="Start / stop autonomous charging, or clear charging state.",
        fields=[Field("Charge", "enum", "Charge", enum=C.CHARGE_REQUEST, default=1)],
        example={"Charge": 1},
        notes=["Charge=2 force-cuts current, resets state and clears error records — only after the fault is cleared."],
    ),
    CommandDef(
        id="sdk_mode", section="1.2.10", group="Control", name="Locomotion SDK Mode",
        type=MsgType.PERIPHERAL, command=0x0030_0002, response="general", danger="caution",
        summary="Enter/leave Locomotion SDK control mode.",
        fields=[
            Field("SDKEnable", "bool", "SDK enable", default=True),
            Field("Frequency", "int", "Joint topic frequency", "Hz", default=100, min=1, max=200,
                  help="Must divide 1000 (1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200)"),
        ],
        example={"SDKEnable": True, "Frequency": 100},
        notes=["SDK mode must be unlocked by after-sales first (expect E007 otherwise)."],
    ),
    CommandDef(
        id="sleep", section="1.2.11", group="Control", name="Set Sleep Mode Settings",
        type=MsgType.DEVICE, command=0x0040_0002, response="general", danger="caution",
        summary="Enter/exit sleep and configure auto-sleep.",
        fields=[
            Field("Sleep", "bool", "Enter sleep", default=False, help="true = sleep, false = wake up"),
            Field("Auto", "bool", "Auto sleep", default=True),
            Field("Time", "int", "Wait after heartbeat loss", "min", default=5, min=0),
        ],
        example={"Sleep": False, "Auto": True, "Time": 5},
    ),
    # --------------------------------------------------------- §1.4 Inspection
    CommandDef(
        id="location_init", section="1.4.1", group="Navigation", name="Location Initialization / Reset",
        type=MsgType.NAVIGATION, command=0x0020_0002, response="general", danger="caution",
        summary="Relocalize at a pose in the map frame.",
        fields=[Field("PosX", "float", "X", "m", 0.0, step=0.01), Field("PosY", "float", "Y", "m", 0.0, step=0.01),
                Field("PosZ", "float", "Z", "m", 0.0, step=0.01), Field("Yaw", "float", "Yaw", "rad", 0.0, step=0.01)],
        example={"PosX": 0.0, "PosY": 0.0, "PosZ": 0.0, "Yaw": 0.0},
    ),
    CommandDef(
        id="location_get", section="1.4.2", group="Navigation", name="Get Location (map frame)",
        type=MsgType.NAVIGATION, command=0x0020_0001, response="data",
        summary="Robot pose + localization confidence in the map frame.",
        example={},
        response_fields={"Location": "location", "Relocation": "relocation"},
        notes=["Confidence 0..1, reference only."],
    ),
    CommandDef(
        id="nav_perception", section="1.4.3", group="Navigation", name="Get Navigation (Perception) Status",
        type=MsgType.NAVIGATION, command=0x0011_0001, response="data",
        summary="Localization state + obstacle-avoidance state.",
        example={},
        response_fields={"Location": "location", "ObsState": "obs_state"},
    ),
    CommandDef(
        id="nav_task", section="1.4.4", group="Navigation", name="Issue Navigation Task",
        type=MsgType.NAVIGATION, command=0x0010_0002, response="deferred", danger="motion",
        summary="Go to target point(s). Result frame arrives AFTER the task finishes.",
        fields=[Field("Item", "array", "Target points", min_items=1, fields=[
            Field("Value", "int", "Point No.", default=0),
            Field("MapID", "int", "Map ID", default=0),
            Field("PosX", "float", "X", "m", 0.0, step=0.01),
            Field("PosY", "float", "Y", "m", 0.0, step=0.01),
            Field("PosZ", "float", "Z", "m", 0.0, step=0.01),
            Field("AngleYaw", "float", "Yaw", "rad", 0.0, step=0.01),
            Field("PointInfo", "enum", "Point type", enum=C.POINT_INFO, default=0),
            Field("Gait", "enum", "Gait", enum=C.NAV_GAIT, default=0x3002),
            Field("Speed", "enum", "Speed", enum=C.NAV_SPEED, default=0),
            Field("Manner", "enum", "Manner", enum=C.NAV_MANNER, default=0),
            Field("ObsMode", "enum", "Obstacle avoidance", enum=C.OBS_MODE, default=0),
            Field("NavMode", "enum", "Nav mode", enum=C.NAV_MODE, default=0),
        ])],
        example={"Item": [{"Value": 0, "MapID": 0, "PosX": 0.0, "PosY": 0.0, "PosZ": 0.0, "AngleYaw": 0.0,
                           "PointInfo": 0, "Gait": 12290, "Speed": 0, "Manner": 0, "ObsMode": 0, "NavMode": 0}]},
        response_fields={"Status": "nav_status", "ErrorCode": "nav_errors"},
        notes=["Requires Navigation mode (else 0xA328).",
               "Stairs with Straight NavMode: target >= 45 cm past the last step, ObsMode disabled.",
               "Prefer multi-segment Straight over Auto navigation."],
    ),
    CommandDef(
        id="nav_cancel", section="1.4.5", group="Navigation", name="Cancel Navigation Task",
        type=MsgType.NAVIGATION, command=0x0010_0004, response="data", danger="caution",
        summary="Cancel the running navigation task.",
        example={},
        response_fields={"ErrorCode": "cancel_result"},
    ),
    CommandDef(
        id="nav_state", section="1.4.6", group="Navigation", name="Query Navigation Task State",
        type=MsgType.NAVIGATION, command=0x0010_0001, response="data",
        summary="Current navigation task execution state.",
        example={},
        response_fields={"Status": "nav_status", "ErrorCode": "nav_errors"},
    ),
]

REPORTS: list[ReportDef] = [
    ReportDef("basic", "1.3.1.1", "Basic Status", MsgType.STATUS, REPORT_COMMAND, 2.0, "BasicStatus",
              "Motion state, gait, HES, usage mode, sleep, model/version, charge."),
    ReportDef("motion", "1.3.1.2", "Motion Control Status", MsgType.MOTION, REPORT_COMMAND, 10.0, "MotionStatus",
              "IMU, velocities, height, payload, 16 joint angles."),
    ReportDef("device", "1.3.1.3", "Device State", MsgType.DEVICE, REPORT_COMMAND, 2.0, "BatteryList",
              "Battery, motor/driver temps, GPS, lidar/video enable, CPU (AOS/NOS).",
              notes=["Large payload — may arrive as multi-packet (Packet Sequence Number)."]),
    ReportDef("abnormal", "1.3.1.4", "Abnormal Status", MsgType.ABNORMAL, REPORT_COMMAND, 2.0, "ErrorList",
              "Active fault list. Extra report on every change."),
    ReportDef("navigation", "1.3.1.5", "Navigation Status", MsgType.NAVIGATION, REPORT_COMMAND, 1.0, "NavStatus",
              "Navigation task status + location status."),
]

_BY_ID = {c.id: c for c in COMMANDS}
_BY_CODE = {(int(c.type), int(c.command)): c for c in COMMANDS}
_REPORT_BY_CODE = {(int(r.type), int(r.command)): r for r in REPORTS}


def get_command(cid: str) -> CommandDef:
    try:
        return _BY_ID[cid]
    except KeyError:
        raise KeyError(f"unknown command id '{cid}'. Known: {', '.join(_BY_ID)}") from None


def find_command(type_: int | None, command: int | None) -> CommandDef | None:
    if type_ is None or command is None:
        return None
    return _BY_CODE.get((int(type_), int(command)))


def find_report(type_: int | None, command: int | None) -> ReportDef | None:
    if type_ is None or command is None:
        return None
    return _REPORT_BY_CODE.get((int(type_), int(command)))


def message_name(type_: int | None, command: int | None) -> str:
    r = find_report(type_, command)
    if r:
        return f"{r.name} (report)"
    c = find_command(type_, command)
    if c:
        return c.name
    if type_ is None or command is None:
        return "?"
    return f"Unknown {hex32(type_)} / {hex32(command)}"


def catalog_dict() -> dict:
    from .header import MAX_FRAME_ASDU, PROTOCOL_VERSION, SYNC

    return {
        "protocol": {
            "name": "Inspection Communication Protocol",
            "doc_version": "V1.0.3-0 (2026-11-21)",
            "sync": SYNC.hex(" ").upper(),
            "header_size": 16,
            "max_frame_asdu": MAX_FRAME_ASDU,
            "version": PROTOCOL_VERSION,
            "report_command": REPORT_COMMAND,
        },
        "commands": [c.to_dict() for c in COMMANDS],
        "reports": [r.to_dict() for r in REPORTS],
        "enums": C.enums_table(),
        "presets": transport_presets(),
    }


def transport_presets() -> list[dict]:
    h = C.DEFAULT_ROBOT_HOST
    return [
        {"id": "robot-dtls", "label": f"Robot · DTLS {C.PORT_DTLS}", "transport": "dtls", "host": h, "port": C.PORT_DTLS,
         "note": "Default on robot (UDP + encrypted)."},
        {"id": "robot-tls", "label": f"Robot · TLS {C.PORT_TLS}", "transport": "tls", "host": h, "port": C.PORT_TLS,
         "note": "Default on robot (TCP + encrypted)."},
        {"id": "robot-udp", "label": f"Robot · UDP plain {C.PORT_UDP_PLAIN}", "transport": "udp", "host": h,
         "port": C.PORT_UDP_PLAIN, "note": "Only after encryption is disabled in robotserver config — port assumed, verify."},
        {"id": "robot-tcp", "label": f"Robot · TCP plain {C.PORT_TCP_PLAIN}", "transport": "tcp", "host": h,
         "port": C.PORT_TCP_PLAIN, "note": "Only after encryption is disabled — port assumed, verify."},
        {"id": "mock-udp", "label": "Mock · UDP 127.0.0.1:30000", "transport": "udp", "host": "127.0.0.1",
         "port": C.PORT_UDP_PLAIN, "note": "Run `ezra-udp mock` first."},
        {"id": "mock-dtls", "label": "Mock · DTLS 127.0.0.1:30004", "transport": "dtls", "host": "127.0.0.1",
         "port": C.PORT_DTLS, "note": "Run `ezra-udp mock` first (self-signed cert, verify off)."},
        {"id": "mock-tcp", "label": "Mock · TCP 127.0.0.1:30001", "transport": "tcp", "host": "127.0.0.1",
         "port": C.PORT_TCP_PLAIN, "note": "Run `ezra-udp mock` first."},
        {"id": "mock-tls", "label": "Mock · TLS 127.0.0.1:30003", "transport": "tls", "host": "127.0.0.1",
         "port": C.PORT_TLS, "note": "Run `ezra-udp mock` first (self-signed cert, verify off)."},
    ]
