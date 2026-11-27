"""Constants, enums and code tables from Inspection Communication Protocol V1.0.3-0.

Values marked "assumed" were truncated in the source PDF (table cells clipped)
and are inferred from the visible ordering — verify against the robot.
"""

from __future__ import annotations

from enum import IntEnum


class MsgType(IntEnum):
    MOTION = 0x0010_0001  # 1048577 — motion state / gait / axis / velocity
    DEVICE = 0x0010_0002  # 1048578 — usage mode / sleep / device state
    NAVIGATION = 0x0010_0003  # 1048579 — location / navigation
    CHARGING = 0x0010_0004  # 1048580 — autonomous charging
    PERIPHERAL = 0x0010_0005  # 1048581 — lights / locomotion SDK
    STATUS = 0x0010_0064  # 1048676 — heartbeat / basic status
    ABNORMAL = 0x0010_007F  # 1048703 — abnormal status report


REPORT_COMMAND = 0x00F0_0000  # 15728640 — every active status report
HEARTBEAT_TYPE = int(MsgType.STATUS)
HEARTBEAT_COMMAND = 5

DEFAULT_ROBOT_HOST = "10.21.33.103"
PORT_DTLS = 30004  # UDP + encrypted (default on robot)
PORT_TLS = 30003  # TCP + encrypted (default on robot)
# Plain ports after disabling encryption in the robotserver config.
# Not stated in V1.0.3 — older DR inspection docs use 30000 (UDP) / 30001 (TCP).
PORT_UDP_PLAIN = 30000
PORT_TCP_PLAIN = 30001


def hex32(v: int) -> str:
    """1048676 -> '0x0010 0064' (same notation as the PDF)."""
    v &= 0xFFFF_FFFF
    return f"0x{v >> 16:04X} {v & 0xFFFF:04X}"


# ---------------------------------------------------------------- §1.5 general
GENERAL_ERRORS: dict[int, tuple[str, str]] = {
    0: ("Success", ""),
    0xE001: ("Unsupported data format", "Data format not supported (non-XML or JSON)."),
    0xE002: ("Data parsing failed", "Protocol format error, missing PatrolDevice, Items, Type, or Command."),
    0xE003: ("Unsupported protocol type", "No protocol found for the given Type and Command."),
    0xE004: ("Missing necessary fields", "Missing protocol field."),
    0xE005: ("Mismatched data type", ""),
    0xE006: ("Mismatched request client", "e.g. axis commands within 2 s must come from the same client."),
    0xE007: ("No operation permission", ""),
    0xE008: ("Not allowed operation", ""),
    0xE009: ("Operation failure", ""),
    0xE00A: ("Unsupported function", "e.g. navigation is supported only in the Pro version."),
    0xE00B: ("Internal error", "e.g. internal file opening / parsing failure."),
}

# ------------------------------------------------- Appendix 1 navigation errors
NAV_ERRORS: dict[int, str] = {
    0x0000: "Navigation task normal status",
    0x2300: "Navigation task completed normally",
    0x2302: "Navigation task cancelled by user",
    0x8605: "Move to point timeout",
    0xA301: "Abnormal motion state",
    0xA302: "Low battery",
    0xA303: "Motor status abnormal",
    0xA305: "LiDAR error (not started or no point cloud data)",
    0xA312: "Planner not idle or global navigation state abnormal",
    0xA313: "Localization error",
    0xA314: "Terrain map error",
    0xA327: "Gait abnormal, failed to switch to target gait",
    0xA328: "Control mode error, not in Navigation Mode",
    0xA341: "Navigation task in progress, task dispatch failed",
    0xA343: "Timeout waiting to exit auto-charging",
    0xA344: "Abnormality during auto-charging",
    0xA345: "Auto-charging execution failed",
    0xA349: "Map switch failed",
    0xA34B: "Local navigation: continuous obstacle avoidance",
    0xA34C: "Navigation local planning failure",
    0xA34D: "Continuous navigation velocity not updated",
    0xA34E: "Auto-charging in progress, task dispatch failed",
    0xA400: "Failed to send target point to local navigation",
    0xA401: "Failed to send target point to global navigation",
    0xA402: "Failed to cancel local navigation",
    0xA403: "Failed to cancel global navigation",
    0xA404: "Navigation parameter setting failed",
    0xA405: "Local navigation module abnormal, restarted",
    0xA406: "Local navigation module abnormal: no real-time obstacle map",
    0xA407: "Local navigation module abnormal: no localization data",
    0xA408: "Global navigation module abnormal, restarted",
    0xA409: "Global navigation module abnormal: no grid map",
    0xA40A: "Global navigation module abnormal: no localization data",
    0xA40B: "Global navigation module abnormal: global planning failed",
    0xA40C: "Global navigation module abnormal: target point in obstacle",
    0xA40D: "Localization module abnormal, restarted",
    0xA40E: "Localization module abnormal: sensor error",
    0xA40F: "Odometry module abnormal: odometry result publish time error",
}

# --------------------------------------- §1.3.1.4 / §2.5 fault (abnormal) codes
FAULT_CODES: dict[int, str] = {
    0x8001: "Motor overtemperature",
    0x8002: "Driver overtemperature",
    0x8003: "Driver overvoltage",
    0x8004: "Driver undervoltage",
    0x8005: "Driver overcurrent",
    0x8006: "Driver communication error",
    0x8007: "Driver status error",
    0x8008: "Driver operation anomaly",
    0x800A: "Joint sustained high-speed operation",
    0x8012: "Temp sensor wire disconnected",
    0x8014: "Joint position limit exceeded",
    0x8016: "Joint data invalid",
    0x8017: "Joint data update error",
    0x8101: "Low battery",
    0x8102: "Battery undervoltage",
    0x8104: "Cell undervoltage",
    0x8105: "Cell overvoltage",
    0x8106: "Pack overvoltage",
    0x8107: "Pack undervoltage",
    0x8108: "Battery overtemperature",
    0x8109: "Battery undertemperature",
    0x810A: "Discharge overcurrent",
    0x810D: "Charge overcurrent",
    0x810E: "Output short circuit",
    0x810F: "IC error",
    0x8110: "MOSFET locked",
    0x8111: "Data acquisition failure",
    0x8201: "IMU publish timeout / no update",
    0x8202: "IMU open failure",
    0x8203: "IMU data timeout (joint level)",
    0x8204: "IMU data invalid",
    0x8301: "CPU overtemperature",
    0x8302: "High CPU utilization",
    0x8303: "Low CPU frequency",
    0x8304: "Low available memory",
    0x8306: "High file system usage",
    0x8308: "High inode usage",
    0x9401: "Reflector positioning data fetch timeout",
    0x9402: "Failed to start reflector positioning algorithm",
    0x9403: "No reflector positioning data",
    0x9406: "No current detection",
    0x9408: "Obstacle encountered during undocking",
    0x9409: "Timeout reaching charging station",
}

SEVERITY = {3: "WARN", 4: "ERROR", 5: "FATAL"}
FAULT_EVENT_TYPE = {1: "START (triggered / severity changed)", 2: "STOP (cleared)"}

# ------------------------------------------------------------------ field enums
USAGE_MODE = {0: "Regular", 1: "Navigation", 2: "Assist"}
MOTION_STATE = {-2: "Soft Emergency Stop (damping)", 1: "Stand", 4: "Sit"}
GAIT = {
    0x1001: "Basic (Regular mode)",
    0x1003: "Stair (Regular mode)",
    0x3002: "Flat (Navigation mode)",
    0x3003: "Stair (Navigation mode)",
}
HES = {0: "Not triggered", 1: "Triggered"}
POWER_MANAGEMENT = {0: "Regular"}
SLEEP_STATE = {0: "Non-sleep", 1: "Sleep", 2: "Entering sleep"}
# §1.3.1.1 lists names only; numeric order is assumed.
CHARGE_STATE = {
    0: "idle",
    1: "goToPile",
    2: "charging",
    3: "exitPile",
    4: "error",
    5: "onPiling",
    6: "line_charging",
}
CHARGE_REQUEST = {0: "Stop charging", 1: "Start charging", 2: "Clear charging status (risky)"}
LIGHT_MODE = {
    0: "Solid",
    1: "Filling Sequential",
    2: "Moving Sequential",
    3: "Fading Sequential",
    4: "Breathing",
    5: "Single-Color Flashing",
}
LIGHT_COLOR = {0: "Black (off)", 1: "White", 2: "Green", 3: "Blue"}
LIDAR_ENABLE = {0: "Off", 1: "On", 2: "Initializing"}
VIDEO_ENABLE = {0: "Off", 1: "On"}
LOCATION = {0: "Normal", 1: "Lost"}
RELOCATION = {-1: "Default", 0: "Running", 1: "Idle", 2: "Succeeded", 3: "Failed"}
OBS_STATE = {0: "Not in obstacle avoidance", 1: "In obstacle avoidance"}
# value 5 truncated in the PDF — assumed
NAV_STATUS = {
    0: "Idle",
    1: "Exiting charging dock",
    2: "Navigation preprocessing",
    3: "Navigating",
    4: "Navigation completed",
    5: "Entering charging dock",
}
POINT_INFO = {0: "Transition point", 1: "Task point", 2: "Stand point", 3: "Charge point", 4: "Stair position point"}
NAV_GAIT = {0x3002: "Flat (Navigation mode)", 0x3003: "Stair (Navigation mode)"}
NAV_SPEED = {0: "Normal", 1: "Low", 2: "High"}
NAV_MANNER = {0: "Walk forward", 1: "Walk backward"}
OBS_MODE = {0: "Enable", 1: "Disable"}
NAV_MODE = {0: "Straight", 1: "Auto"}
CANCEL_RESULT = {0: "Success", 1: "Failure"}

JOINT_NAMES = [
    "LeftFrontHipX", "LeftFrontHipY", "LeftFrontKnee", "LeftFrontWheel",
    "RightFrontHipX", "RightFrontHipY", "RightFrontKnee", "RightFrontWheel",
    "LeftBackHipX", "LeftBackHipY", "LeftBackKnee", "LeftBackWheel",
    "RightBackHipX", "RightBackHipY", "RightBackKnee", "RightBackWheel",
]  # fmt: skip


def describe_error(code: int | None) -> dict:
    """Best-effort lookup across general / navigation tables."""
    if code is None:
        return {"code": None, "hex": None, "label": "n/a", "detail": "", "table": None, "ok": None}
    try:
        code = int(code)
    except (TypeError, ValueError):
        return {"code": code, "hex": None, "label": str(code), "detail": "", "table": None, "ok": None}
    if code in GENERAL_ERRORS:
        label, detail = GENERAL_ERRORS[code]
        return {"code": code, "hex": f"0x{code:04X}", "label": label, "detail": detail, "table": "general", "ok": code == 0}
    if code in NAV_ERRORS:
        ok = code in (0x0000, 0x2300)
        return {"code": code, "hex": f"0x{code:04X}", "label": NAV_ERRORS[code], "detail": "", "table": "navigation", "ok": ok}
    return {"code": code, "hex": f"0x{code:04X}", "label": "Unknown code", "detail": "", "table": None, "ok": False}


def enums_table() -> dict:
    """Everything the GUI needs to render labels."""
    def m(d: dict) -> dict:
        return {str(k): v for k, v in d.items()}

    return {
        "usage_mode": m(USAGE_MODE),
        "motion_state": m(MOTION_STATE),
        "gait": m(GAIT),
        "hes": m(HES),
        "power_management": m(POWER_MANAGEMENT),
        "sleep_state": m(SLEEP_STATE),
        "charge_state": m(CHARGE_STATE),
        "charge_request": m(CHARGE_REQUEST),
        "light_mode": m(LIGHT_MODE),
        "light_color": m(LIGHT_COLOR),
        "lidar_enable": m(LIDAR_ENABLE),
        "video_enable": m(VIDEO_ENABLE),
        "location": m(LOCATION),
        "relocation": m(RELOCATION),
        "obs_state": m(OBS_STATE),
        "nav_status": m(NAV_STATUS),
        "point_info": m(POINT_INFO),
        "nav_gait": m(NAV_GAIT),
        "nav_speed": m(NAV_SPEED),
        "nav_manner": m(NAV_MANNER),
        "obs_mode": m(OBS_MODE),
        "nav_mode": m(NAV_MODE),
        "severity": m(SEVERITY),
        "fault_event_type": m(FAULT_EVENT_TYPE),
        "joint_names": JOINT_NAMES,
        "general_errors": {str(k): {"hex": f"0x{k:04X}", "label": v[0], "detail": v[1]} for k, v in GENERAL_ERRORS.items()},
        "nav_errors": {str(k): {"hex": f"0x{k:04X}", "label": v} for k, v in NAV_ERRORS.items()},
        "fault_codes": {str(k): {"hex": f"0x{k:04X}", "label": v} for k, v in FAULT_CODES.items()},
    }
