"""Simulated robot state + request handling (behaves per Inspection Protocol V1.0.3-0)."""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..protocol import catalog as CAT
from ..protocol.codes import (
    GENERAL_ERRORS,
    HEARTBEAT_COMMAND,
    HEARTBEAT_TYPE,
    REPORT_COMMAND,
    MsgType,
)

OK = 0
E_FORMAT, E_PARSE, E_PROTO, E_MISSING, E_TYPE, E_CLIENT, E_PERM, E_NOT_ALLOWED, E_FAIL, E_UNSUPPORTED, E_INTERNAL = (
    0xE001, 0xE002, 0xE003, 0xE004, 0xE005, 0xE006, 0xE007, 0xE008, 0xE009, 0xE00A, 0xE00B)

NAV_DONE, NAV_CANCELLED, NAV_NOT_NAV_MODE, NAV_BUSY, NAV_BAD_MOTION = 0x2300, 0x2302, 0xA328, 0xA341, 0xA301


def general(code: int, msg: str | None = None) -> dict:
    return {"ErrorCode": code, "ErrorMessage": msg or GENERAL_ERRORS.get(code, ("Error", ""))[0]}


@dataclass
class Reply:
    type: int
    command: int
    items: dict


Responder = Callable[[Reply], None]


class RobotSim:
    def __init__(self, version: str = "PRO", sdk_unlocked: bool = False, faults: bool = False,
                 model: str = "S10") -> None:
        self.version = version.upper()
        self.model = model
        self.sdk_unlocked = sdk_unlocked
        self.inject_faults = faults
        self.usage_mode = 0
        self.motion_state = 4  # sitting
        self.gait = 0x1001
        self.hes = 0
        self.sleep_state = 0
        self.auto_sleep, self.sleep_time = True, 5
        self.charge_state = 0
        self.lights = {"CustomMode": False, "Led": []}
        self.sdk_enable, self.sdk_hz = False, 100
        self.pose = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # x y z roll pitch yaw (map)
        self.cmd = (0.0, 0.0, 0.0)  # vx vy wz
        self.cmd_ts = 0.0
        self.vel = [0.0, 0.0, 0.0]
        self.height = 0.12
        self.battery = 86.0
        self.location, self.relocation, self.confidence, self.obs_state = 0, 1, 0.97, 0
        self.nav = {"Value": 0, "Status": 0, "ErrorCode": 0, "LoopCnt": 0, "RemainingCnt": 0, "Name": ""}
        self._nav_task: asyncio.Task | None = None
        self._nav_responder: tuple[Responder, int] | None = None
        self.faults: list[dict] = []
        self.faults_changed = False
        self.t0 = time.time()
        self._fault_cycle = 0.0
        self._joint_phase = 0.0

    # ----------------------------------------------------------- simulation
    def step(self, dt: float) -> None:
        now = time.time()
        if now - self.cmd_ts > 0.5:  # command watchdog
            self.cmd = (0.0, 0.0, 0.0)
        moving_ok = self.motion_state == 1 and self.sleep_state == 0
        target = self.cmd if moving_ok else (0.0, 0.0, 0.0)
        for i in range(3):
            self.vel[i] += (target[i] - self.vel[i]) * min(1.0, dt * 4.0)
        yaw = self.pose[5]
        self.pose[0] += (self.vel[0] * math.cos(yaw) - self.vel[1] * math.sin(yaw)) * dt
        self.pose[1] += (self.vel[0] * math.sin(yaw) + self.vel[1] * math.cos(yaw)) * dt
        self.pose[5] = (self.pose[5] + self.vel[2] * dt + math.pi) % (2 * math.pi) - math.pi
        self.height += ((0.42 if self.motion_state == 1 else 0.12) - self.height) * min(1.0, dt * 2.0)
        if self.charge_state == 2:
            self.battery = min(100.0, self.battery + dt * 0.2)
        else:
            self.battery = max(0.0, self.battery - dt * (0.004 + 0.02 * abs(self.vel[0])))
        self._joint_phase += dt * (2.0 + 6.0 * math.hypot(self.vel[0], self.vel[1]))
        if self.inject_faults:
            self._fault_cycle += dt
            if self._fault_cycle > 15.0:
                self._fault_cycle = 0.0
                if self.faults:
                    self.faults = []
                else:
                    j = random.randint(0, 15)
                    self.faults = [{
                        "Code": 0x8001, "Details": '{"temp": 81.5}', "Grouped": False,
                        "Name": "motor_over_temp", "Resources": [str(j)], "Severities": [3],
                        "Source": ["motion_master#0"], "SourceIds": [j],
                        "Timestamp": {"Nanosec": int((now % 1) * 1e9), "Sec": int(now)}, "Type": 1,
                    }]
                self.faults_changed = True

    # -------------------------------------------------------------- reports
    def basic_status(self) -> dict:
        return {"BasicStatus": {
            "MotionState": self.motion_state, "Gait": self.gait, "HES": self.hes,
            "ControlUsageMode": self.usage_mode, "PowerManagement": 0, "Sleep": self.sleep_state != 0,
            "Model": self.model, "Version": self.version, "Charge": self.charge_state,
        }}

    def motion_status(self) -> dict:
        ph = self._joint_phase
        joints = []
        for leg in range(4):
            off = leg * math.pi / 2
            stance = 1.0 if self.motion_state == 1 else 0.3
            joints += [round(0.05 * math.sin(ph + off), 4), round(stance * (0.7 + 0.15 * math.sin(ph + off)), 4),
                       round(-stance * (1.4 + 0.2 * math.cos(ph + off)), 4), round((ph * 2 + off) % (2 * math.pi), 4)]
        noise = lambda s: round(random.gauss(0, s), 4)  # noqa: E731
        return {
            "MotionStatus": {
                "AccX": noise(0.05), "AccY": noise(0.05), "AccZ": round(9.81 + random.gauss(0, 0.05), 4),
                "AngularZ": round(self.vel[2], 4), "Gait": self.gait, "Height": round(self.height, 3),
                "LinearX": round(self.vel[0], 4), "LinearY": round(self.vel[1], 4),
                "MotionState": self.motion_state, "OmegaX": noise(0.01), "OmegaY": noise(0.01),
                "OmegaZ": round(self.vel[2] + random.gauss(0, 0.005), 4), "Payload": 0.0,
                "Pitch": noise(0.01), "RemainMile": round(self.battery / 100 * 8.0, 2), "Roll": noise(0.01),
                "Yaw": round(self.pose[5], 4),
            },
            "MotorStatus": {"Joint": joints},
        }

    def device_state(self) -> dict:
        now = time.time()
        temps = [round(38 + 6 * abs(math.sin(self._joint_phase / 7 + i)), 1) for i in range(16)]

        def cpu(soc: str, base: int) -> dict:
            util = [max(1, min(99, base + random.randint(-15, 15))) for _ in range(8)]
            return {
                "AvgUtil": sum(util) // 8,
                "CurFreqKhz": [1800000] * 4 + [2352000] * 4,
                "GovPolicy": ["performance"] * 8,
                "HwMaxFreqKhz": [1800000] * 4 + [2352000] * 4,
                "HwMinFreqKhz": [408000] * 8,
                "PackageTemp": 40 + random.randint(0, 6),
                "SocId": soc,
                "Temps": [43 + random.randint(0, 4) for _ in range(8)],
                "Timestamp": {"Nanosec": int((now % 1) * 1e9), "Sec": int(now)},
                "Util": util,
            }

        return {
            "BatteryList": [{"Voltage": round(46.0 + self.battery * 0.08, 2), "BatteryLevel": int(self.battery),
                             "battery_temperature": 31.5, "charge": self.charge_state == 2,
                             "serial": "MOCK-BAT-0001"}],
            "DeviceTemperature": {"Motor": temps, "Driver": [round(t - 4, 1) for t in temps]},
            "GPS": {"Latitude": -7.2819, "Longitude": 112.7948, "Speed": round(abs(self.vel[0]) * 3.6, 2),
                    "Course": round(math.degrees(self.pose[5]) % 360, 1), "FixQuality": 1.0, "NumSatellites": 11,
                    "Altitude": 7.0, "HDOP": 0.9, "VDOP": 1.2, "PDOP": 1.5, "VisibleSatellites": 17,
                    "TotalMessages": 1, "CurrentMessage": 1},
            "DevEnable": {"Lidar": 1, "Video": 1},
            "CPU": {"AOS": cpu("CPU_103", 28), "NOS": cpu("CPU_106", 45)},
        }

    def abnormal(self) -> dict:
        return {"ErrorList": list(self.faults)}

    def navigation(self) -> dict:
        x, y, z, r, p, yaw = self.pose
        return {
            "NavStatus": dict(self.nav),
            "LocationStatus": {"Location": self.location, "PosX": round(x, 3), "PosY": round(y, 3),
                               "PosZ": round(z, 3), "Roll": round(r, 4), "Pitch": round(p, 4), "Yaw": round(yaw, 4),
                               "Confidence": self.confidence, "Relocation": self.relocation},
        }

    def reports(self, tick: int) -> list[Reply]:
        """tick = 10 Hz counter. Motion 10 Hz, basic/device/abnormal 2 Hz, navigation 1 Hz."""
        out = [Reply(MsgType.MOTION, REPORT_COMMAND, self.motion_status())]
        if tick % 5 == 0 or self.faults_changed:
            out.append(Reply(MsgType.ABNORMAL, REPORT_COMMAND, self.abnormal()))
            self.faults_changed = False
        if tick % 5 == 0:
            out.append(Reply(MsgType.STATUS, REPORT_COMMAND, self.basic_status()))
            out.append(Reply(MsgType.DEVICE, REPORT_COMMAND, self.device_state()))
        if tick % 10 == 0:
            out.append(Reply(MsgType.NAVIGATION, REPORT_COMMAND, self.navigation()))
        return out

    # ------------------------------------------------------------- requests
    def handle(self, payload: Any, respond: Responder) -> str:
        """Process one decoded PatrolDevice payload; returns a short log string."""
        if not isinstance(payload, dict) or not all(k in payload for k in ("Type", "Command", "Items")):
            t = payload.get("Type", 0) if isinstance(payload, dict) else 0
            c = payload.get("Command", 0) if isinstance(payload, dict) else 0
            respond(Reply(_int(t), _int(c), general(E_PARSE)))
            return "E002 missing PatrolDevice/Type/Command/Items"
        typ, cmd, items = _int(payload["Type"]), _int(payload["Command"]), payload["Items"]
        if items == "" or items is None:
            items = {}
        if (typ, cmd) == (HEARTBEAT_TYPE, HEARTBEAT_COMMAND):
            respond(Reply(typ, cmd, general(OK)))
            return "heartbeat"
        cdef = CAT.find_command(typ, cmd)
        if cdef is None:
            respond(Reply(typ, cmd, general(E_PROTO)))
            return f"E003 unknown Type/Command {typ}/{cmd}"
        if not isinstance(items, dict):
            respond(Reply(typ, cmd, general(E_TYPE, "Items must be an object")))
            return "E005 Items not an object"
        err = _validate(cdef.fields, items)
        if err:
            code, why = err
            if cdef.response != "none":
                respond(Reply(typ, cmd, general(code, f"{GENERAL_ERRORS[code][0]}: {why}")))
            return f"{GENERAL_ERRORS[code][0]}: {why}"
        if cdef.group == "Navigation" and self.version != "PRO":
            respond(Reply(typ, cmd, general(E_UNSUPPORTED)))
            return "E00A navigation needs PRO"
        handler = getattr(self, f"_h_{cdef.id}")
        return handler(cdef, items, respond) or cdef.name

    # each handler returns an optional log line
    def _ok(self, cdef, respond: Responder, code: int = OK, msg: str | None = None) -> None:
        respond(Reply(cdef.type, cdef.command, general(code, msg)))

    def _h_usage_mode(self, cdef, items, respond):
        self.usage_mode = int(items["Mode"])
        self.gait = {0: 0x1001, 1: 0x3002, 2: 0x1001}[self.usage_mode]
        self._ok(cdef, respond)
        return f"usage mode -> {self.usage_mode}"

    def _h_motion_state(self, cdef, items, respond):
        v = int(items["MotionParam"])
        if v == 1 and self.hes:
            self._ok(cdef, respond, E_NOT_ALLOWED, "Not allowed operation: hard e-stop active")
            return "stand refused (HES)"
        self.motion_state = v
        if v == 1:
            self.sleep_state = 0
        self._ok(cdef, respond)
        return f"motion state -> {v}"

    def _h_gait(self, cdef, items, respond):
        g = int(items["GaitParam"])
        self.gait = g
        self.usage_mode = 1 if g in (0x3002, 0x3003) else 0
        self._ok(cdef, respond)
        return f"gait -> 0x{g:04X} (mode {self.usage_mode})"

    def _h_axis(self, cdef, items, respond):
        if self.usage_mode not in (0, 2):
            return "axis ignored (not Regular/Assist)"
        clip = lambda v: max(-1.0, min(1.0, float(v)))  # noqa: E731
        self.cmd = (clip(items["X"]) * 1.67, clip(items["Y"]) * 0.4, clip(items["Yaw"]) * 1.0)
        self.cmd_ts = time.time()
        return None if self.cmd == (0.0, 0.0, 0.0) else f"axis {self.cmd}"

    def _h_velocity(self, cdef, items, respond):
        if self.usage_mode != 1:
            return "velocity ignored (not Navigation mode)"
        self.cmd = (max(-1.67, min(1.67, float(items["X"]))), max(-0.4, min(0.4, float(items["Y"]))),
                    max(-1.0, min(1.0, float(items["Yaw"]))))
        self.cmd_ts = time.time()
        return None if self.cmd == (0.0, 0.0, 0.0) else f"velocity {self.cmd}"

    def _h_vel_pos(self, cdef, items, respond):
        self._ok(cdef, respond)

    def _h_lights(self, cdef, items, respond):
        led = items["Led"] if isinstance(items["Led"], list) else [items["Led"]]
        if len(led) != 2:
            self._ok(cdef, respond, E_NOT_ALLOWED, "Led must have 2 entries (front, rear)")
            return "lights: bad Led count"
        self.lights = {"CustomMode": bool(items["CustomMode"]), "Led": led}
        self._ok(cdef, respond)

    def _h_charging(self, cdef, items, respond):
        v = int(items["Charge"])
        self.charge_state = {0: 0, 1: 1, 2: 0}[v]
        if v == 1:
            asyncio.get_running_loop().call_later(3.0, self._charge_arrived)
        if v == 2:
            self.faults, self.faults_changed = [], True
        self._ok(cdef, respond)

    def _charge_arrived(self) -> None:
        if self.charge_state == 1:
            self.charge_state = 2

    def _h_sdk_mode(self, cdef, items, respond):
        if not self.sdk_unlocked:
            self._ok(cdef, respond, E_PERM, "No operation permission: SDK mode locked (contact after-sales)")
            return "SDK locked"
        hz = int(items["Frequency"])
        if not (1 <= hz <= 200 and 1000 % hz == 0):
            self._ok(cdef, respond, E_NOT_ALLOWED, "Frequency must be in [1,200] and divide 1000")
            return "SDK bad frequency"
        self.sdk_enable, self.sdk_hz = bool(items["SDKEnable"]), hz
        self._ok(cdef, respond)

    def _h_sleep(self, cdef, items, respond):
        self.auto_sleep, self.sleep_time = bool(items["Auto"]), int(items["Time"])
        if bool(items["Sleep"]):
            self.sleep_state = 2
            asyncio.get_running_loop().call_later(1.0, self._enter_sleep)
        else:
            self.sleep_state = 0
        self._ok(cdef, respond)

    def _enter_sleep(self) -> None:
        if self.sleep_state == 2:
            self.sleep_state = 1

    def _h_location_init(self, cdef, items, respond):
        self.pose[0], self.pose[1], self.pose[2] = float(items["PosX"]), float(items["PosY"]), float(items["PosZ"])
        self.pose[5] = float(items["Yaw"])
        self.relocation = 0
        asyncio.get_running_loop().call_later(1.0, self._reloc_done)
        self._ok(cdef, respond)

    def _reloc_done(self) -> None:
        self.relocation, self.location, self.confidence = 2, 0, 0.99

    def _h_location_get(self, cdef, items, respond):
        respond(Reply(cdef.type, cdef.command, self.navigation()["LocationStatus"]))

    def _h_nav_perception(self, cdef, items, respond):
        respond(Reply(cdef.type, cdef.command, {"Location": self.location, "ObsState": self.obs_state}))

    def _h_nav_state(self, cdef, items, respond):
        respond(Reply(cdef.type, cdef.command, {k: self.nav[k] for k in ("Value", "Status", "ErrorCode")}))

    def _h_nav_cancel(self, cdef, items, respond):
        if self._nav_task and not self._nav_task.done():
            self._nav_task.cancel()
            respond(Reply(cdef.type, cdef.command, {"ErrorCode": 0}))
            return "navigation cancelled"
        respond(Reply(cdef.type, cdef.command, {"ErrorCode": 1}))
        return "cancel: no task running"

    def _h_nav_task(self, cdef, items, respond):
        points = items["Item"] if isinstance(items["Item"], list) else [items["Item"]]
        self._ok(cdef, respond)  # general call-status response right away
        final = lambda value, status, code: respond(  # noqa: E731
            Reply(cdef.type, cdef.command, {"Value": value, "Status": status, "ErrorCode": code}))
        if self._nav_task and not self._nav_task.done():
            final(int(points[0].get("Value", 0)), self.nav["Status"], NAV_BUSY)
            return "nav rejected: task in progress"
        if self.usage_mode != 1:
            final(int(points[0].get("Value", 0)), 0, NAV_NOT_NAV_MODE)
            return "nav rejected: not in Navigation mode"
        if self.motion_state != 1:
            final(int(points[0].get("Value", 0)), 0, NAV_BAD_MOTION)
            return "nav rejected: robot not standing"
        self._nav_task = asyncio.get_running_loop().create_task(self._run_nav(points, final))
        return f"navigation started: {len(points)} point(s)"

    async def _run_nav(self, points: list[dict], final) -> None:
        value = int(points[0].get("Value", 0))
        try:
            self.nav.update(Status=2, ErrorCode=0, Name="mock_task", RemainingCnt=len(points))
            await asyncio.sleep(0.5)
            for i, pt in enumerate(points):
                value = int(pt.get("Value", i))
                self.nav.update(Value=value, Status=3, RemainingCnt=len(points) - i)
                tx, ty = float(pt.get("PosX", 0.0)), float(pt.get("PosY", 0.0))
                speed = {0: 0.5, 1: 0.25, 2: 0.9}.get(int(pt.get("Speed", 0)), 0.5)
                while True:
                    dx, dy = tx - self.pose[0], ty - self.pose[1]
                    dist = math.hypot(dx, dy)
                    if dist < 0.05:
                        break
                    step = min(dist, speed * 0.1)
                    self.pose[0] += dx / dist * step
                    self.pose[1] += dy / dist * step
                    self.pose[5] = math.atan2(dy, dx)
                    self.vel[0] = speed
                    await asyncio.sleep(0.1)
                self.pose[5] = float(pt.get("AngleYaw", self.pose[5]))
            self.vel[0] = 0.0
            self.nav.update(Status=4, ErrorCode=NAV_DONE, RemainingCnt=0, LoopCnt=self.nav["LoopCnt"] + 1)
            final(value, 4, NAV_DONE)
        except asyncio.CancelledError:
            self.vel[0] = 0.0
            self.nav.update(Status=0, ErrorCode=NAV_CANCELLED, RemainingCnt=0)
            final(value, 0, NAV_CANCELLED)


def _int(v: Any) -> int:
    try:
        if isinstance(v, str) and v.lower().startswith("0x"):
            return int(v[2:].replace(" ", ""), 16)
        return int(v)
    except (TypeError, ValueError):
        return 0


def _validate(fields: list, items: dict) -> tuple[int, str] | None:
    """Returns (error_code, reason) — E004 missing, E005 wrong type, E008 bad enum."""
    for f in fields:
        if f.name not in items:
            return E_MISSING, f"'{f.name}' missing"
        err = _check(f, items[f.name])
        if err:
            return err
    return None


def _check(f, v) -> tuple[int, str] | None:
    k = f.kind
    if k in ("int", "enum"):
        if isinstance(v, bool) or not isinstance(v, int):
            if k == "enum" and isinstance(v, float) and v.is_integer():
                v = int(v)
            else:
                return E_TYPE, f"'{f.name}' must be int, got {type(v).__name__}"
        if k == "enum" and f.enum and v not in f.enum:
            return E_NOT_ALLOWED, f"'{f.name}'={v} not in {sorted(f.enum)}"
    elif k == "float":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return E_TYPE, f"'{f.name}' must be a number, got {type(v).__name__}"
    elif k == "bool":
        if not isinstance(v, bool) and v not in (0, 1):
            return E_TYPE, f"'{f.name}' must be bool, got {type(v).__name__}"
    elif k == "object":
        if not isinstance(v, dict):
            return E_TYPE, f"'{f.name}' must be an object"
        return _validate(f.fields or [], v)
    elif k == "array":
        seq = v if isinstance(v, list) else [v]
        if f.fields:
            for it in seq:
                if not isinstance(it, dict):
                    return E_TYPE, f"'{f.name}' items must be objects"
                e = _validate(f.fields, it)
                if e:
                    return e
        elif f.item_kind:
            for it in seq:
                if isinstance(it, bool) or not isinstance(it, int):
                    return E_TYPE, f"'{f.name}' items must be int"
    return None
