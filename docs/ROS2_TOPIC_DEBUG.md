# Debug ROS 2 topic di robot (step by step)

Panduan ini buat semua yang **bukan** UDP command — yaitu ROS 2 topic yang ada di robot
(Inspection Communication Protocol V1.0.3, §2 *ROS2 Topics*). UDP/DTLS command & status report
di-test pakai **EZRA UDP Debugger** (GUI / `ezra-udp`), sedangkan topic ROS 2 di-debug langsung di robot
pakai `ros2` CLI.

> Docs V1.0.3 nyebut topic ini untuk **Lynx S10** dengan **ROS 2 Jazzy**. Kalau robotnya beda
> (mis. M20 dengan Foxy), langkahnya sama — ganti `jazzy` dengan distro di robot (`ls /opt/ros`).

## Daftar topic dari docs

| Topic | Arah | Message type | Rate | Catatan |
|---|---|---|---|---|
| `/IMU` | robot → kita | `sensor_msgs/msg/Imu` | 200 Hz | aktif sejak power-up |
| `/LIDAR/POINTS` | robot → kita | `sensor_msgs/msg/PointCloud2` | 10 Hz | **hanya bisa diakses dari host robot** (akses eksternal → tech support) |
| `/MOTION_INFO` | robot → kita | `drdds/msg/MotionInfo` | 20 Hz | vel x/y/yaw, height, state, gait |
| `/CHARGE_STATUS` | robot → kita | `drdds/msg/StdStatus` | — | state + error_code auto-charging |
| `/fault_aggregator` | robot → kita | `drdds/msg/FaultEventArray` | ~1 Hz | snapshot semua fault aktif |
| `/NAV_CMD` | dua arah | `drdds/msg/NavCmd` | 10 Hz (kalau publish) | velocity navigasi, **hanya Navigation Mode** |
| `/MOTION_STATE` | kita → robot | `drdds/msg/MotionState` | on demand | stand / sit / damping, butuh `motion_master` |
| `/GAIT` | kita → robot | `drdds/msg/Gait` | on demand | 0x3002 flat / 0x3003 stair (Navigation mode) |

`drdds/msg/*` itu **custom message** Deep Robotics — tanpa definisi message-nya, `ros2 topic echo` bakal error.

---

## 0. Safety dulu

- Topic `/MOTION_STATE`, `/GAIT`, `/NAV_CMD` bisa **menggerakkan robot**. Step 1–5 di bawah cuma **baca** (aman).
- Sebelum step 6 (publish): area kosong, remote / E-STOP fisik di tangan, dan siapin E-STOP di GUI.
- Robot boleh dalam keadaan duduk / damping waktu cuma echo topic.

## 1. Masuk ke jaringan & SSH ke robot

```bash
# dari Mac, pastikan satu jaringan dengan robot
ping -c 3 10.21.33.103

# SSH ke host robot (user/password dari Deep Robotics / after-sales)
ssh <user>@10.21.33.103
```

Robot punya 2 komputer (lihat `CPU` di Device State, §1.3.1.3):

| Host | SocId | Isi |
|---|---|---|
| AOS — locomotion host | `CPU_103` | motion (`motion_master`), IMU; `10.21.33.103` juga alamat protocol server UDP/TCP |
| NOS — navigation host | `CPU_106` | navigasi, LiDAR, mapping — kemungkinan `10.21.33.106`, cek dengan `ip neigh` / `arp -a` dari AOS |

Kalau topic yang dicari nggak muncul di satu host, coba host satunya.

## 2. Siapin environment (tanpa sudo!)

> Docs: *user privileges are sufficient. Do not use `su`/`sudo` — the system will deny access and output no data.*

```bash
whoami                     # harus user biasa, bukan root
source /opt/ros/jazzy/setup.bash      # docs pakai setup.sh; dua-duanya oke
printenv | grep -E 'ROS_|RMW_|FASTRTPS|FASTDDS|CYCLONE'
```

Catat `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, dan profile DDS (`FASTRTPS_DEFAULT_PROFILES_FILE` dll).
Kalau nanti mau echo dari komputer lain, nilai-nilai ini harus **sama persis**.

## 3. Pastikan custom message `drdds` kebaca

```bash
ros2 interface list | grep drdds
```

Kalau kosong, cari workspace yang punya `drdds` lalu source:

```bash
find / -name 'MotionInfo.msg' -path '*drdds*' 2>/dev/null
find / -name 'local_setup.bash' -path '*install*' 2>/dev/null | head
# contoh: source /path/ke/workspace/install/setup.bash
```

Lalu cek definisi aslinya (sumber kebenaran untuk nama field — docs cuma kasih gambaran struktur):

```bash
ros2 interface show drdds/msg/MotionState
ros2 interface show drdds/msg/Gait
ros2 interface show drdds/msg/MotionInfo
ros2 interface show drdds/msg/NavCmd
ros2 interface show drdds/msg/StdStatus
ros2 interface show drdds/msg/FaultEventArray
```

## 4. Lihat topic & node yang hidup

```bash
ros2 daemon stop; ros2 daemon start      # reset cache discovery kalau hasilnya aneh
ros2 topic list -t                       # topic + type
ros2 node list
ros2 topic info -v /IMU                  # publisher/subscriber + QoS (reliability, durability)
```

`ros2 topic info -v` penting: kalau publisher `BEST_EFFORT`, echo juga harus best effort (lihat troubleshooting).

## 5. Echo topic satu per satu

Selalu mulai dari `hz` (ada data atau nggak, rate-nya sesuai docs atau nggak), baru `echo`.

### `/IMU` — 200 Hz
```bash
ros2 topic hz /IMU
ros2 topic echo /IMU --once
ros2 topic echo /IMU --field angular_velocity
```
Cek: `orientation` berubah waktu robot dimiringkan, `linear_acceleration.z ≈ 9.8` waktu diam.

### `/LIDAR/POINTS` — 10 Hz (jalankan di host robot)
```bash
ros2 topic hz /LIDAR/POINTS
ros2 topic bw /LIDAR/POINTS
ros2 topic echo /LIDAR/POINTS --once --no-arr     # --no-arr biar terminal nggak banjir byte array
ros2 topic echo /LIDAR/POINTS --once --field header
```
Cek: `width × height` > 0, `fields` ada x/y/z(/intensity), `header.frame_id` masuk akal.

### `/MOTION_INFO` — 20 Hz
```bash
ros2 topic hz /MOTION_INFO
ros2 topic echo /MOTION_INFO
```
Bandingin sama GUI tab **Monitor** (Motion Control Status §1.3.1.2): `vel_x / vel_y / vel_yaw / height`,
`state` (1 stand, -2 damping/soft e-stop, 4 sit) dan `gait` (4097 basic, 12290 flat nav, 12291 stair nav)
harus konsisten dengan report UDP. Field `payload` di topic ini menurut docs *invalid parameter*.

### `/CHARGE_STATUS`
```bash
ros2 topic echo /CHARGE_STATUS
```

| `state` | Arti | | `error_code` | Arti |
|---|---|---|---|---|
| 0 | Idle | | 0 | reset / init |
| 1 | Navigating to dock | | 1 | operation successful |
| 2 | Charging | | 4098 (0x1002) | timeout cari docking target (reflector ketutup) |
| 3 | Exiting dock | | 4099 (0x1003) | gagal start reflector positioning |
| 4 | Robot error | | 4100 (0x1004) | gagal cari docking target (nggak ada reflector) |
| 5 | On dock tapi nggak ada arus | | 4101 (0x1005) | docking timeout |
| | | | 4102 (0x1006) | undocking timeout |
| | | | 4103 (0x1007) | nggak ada arus dari charging dock |
| | | | 4104 (0x1008) | soft emergency stop ke-trigger |

### `/fault_aggregator` — ~1 Hz
```bash
ros2 topic hz /fault_aggregator
ros2 topic echo /fault_aggregator --once
```
Tiap `FaultEvent`: `code` (mis. 32769 = 0x8001 motor overtemperature), `type` (1 START, 2 STOP),
`severities` (3 WARN, 4 ERROR, 5 FATAL), `resources` (mis. `joint_0`), `source` (mis. `motion_master#0`).
Isinya harus sama dengan **Abnormal Status** (§1.3.1.4) di GUI tab Monitor → panel *Faults*.
Tabel kode lengkap ada di `fault_rules.toml` / enum `FaultCode` di `common.hpp` di robot.

### `/NAV_CMD`, `/MOTION_STATE`, `/GAIT` (topic perintah)
```bash
ros2 topic info -v /MOTION_STATE    # subscriber count harus >= 1 (motion_master)
ros2 topic info -v /GAIT
ros2 topic echo /NAV_CMD            # isi cuma muncul kalau navigasi robot sendiri lagi jalan
```
Topic perintah nggak publish apa-apa sendiri — yang dicek adalah **ada subscriber-nya** (artinya service
`motion_master` / navigasi hidup).

## 6. (Opsional) Publish test — ROBOT BISA GERAK

Nama field di bawah ngikutin struktur di docs (`header{frame_id, timestamp{sec,nsec}}` + `data{...}`).
**Cocokin dulu** sama hasil `ros2 interface show` di step 3 — kalau beda, ikutin yang di robot.

```bash
# switch gait ke flat navigation (robot harus diam & standing)
ros2 topic pub --once /GAIT drdds/msg/Gait \
  "{header: {frame_id: 0, timestamp: {sec: 0, nsec: 0}}, data: {gait: 12290}}"

# velocity navigasi 0.1 m/s maju — HANYA Navigation Mode, publish fix 10 Hz
ros2 topic pub -r 10 /NAV_CMD drdds/msg/NavCmd \
  "{header: {frame_id: 0, timestamp: {sec: 0, nsec: 0}}, data: {x_vel: 0.1, y_vel: 0.0, yaw_vel: 0.0}}"
# Ctrl+C untuk berhenti, lalu kirim nol:
ros2 topic pub --once /NAV_CMD drdds/msg/NavCmd \
  "{header: {frame_id: 0, timestamp: {sec: 0, nsec: 0}}, data: {x_vel: 0.0, y_vel: 0.0, yaw_vel: 0.0}}"
```

Catatan dari docs soal `/MOTION_STATE`:
- Stand lewat **ASDU (UDP)** → robot otomatis masuk RL control, langsung bisa dikasih velocity/gait.
- Stand lewat **topic** → robot **tidak** otomatis masuk RL control; perintah RL control harus dikirim manual
  lewat topic lagi (diagram state-nya nggak ikut ke-render di PDF V1.0.3 — tanya after-sales nilainya).
- Jadi buat test stand/sit, lebih gampang pakai GUI (Requests → *Motion State Switching*, arm motion dulu).

```bash
# kalau tetap mau via topic: damping / soft e-stop
ros2 topic pub --once /MOTION_STATE drdds/msg/MotionState \
  "{header: {frame_id: 0, timestamp: {sec: 0, nsec: 0}}, data: {state: -2}}"
```

## 7. Health check sekali jalan (copy–paste di robot)

Script ini ngecek semua topic di docs: ada/nggak, rate vs spec, dan subscriber untuk topic perintah.
Jalankan sebagai user biasa, **tanpa sudo**.

```bash
cat > ~/ros2_topic_check.sh <<'EOF'
#!/usr/bin/env bash
# EZRA — cek topic ROS 2 sesuai Inspection Protocol V1.0.3 §2
set -u
DISTRO=${DISTRO:-jazzy}
source /opt/ros/$DISTRO/setup.bash
[ -n "${DRDDS_WS:-}" ] && source "$DRDDS_WS/install/setup.bash"
export PYTHONUNBUFFERED=1
ros2 daemon stop >/dev/null 2>&1; ros2 daemon start >/dev/null 2>&1

TOPICS=$(ros2 topic list 2>/dev/null)
ros2 interface list 2>/dev/null | grep -q '^ *drdds/' || echo "!! drdds messages belum ke-source — set DRDDS_WS=/path/ke/workspace"

rate() {  # topic expected_hz
  local t=$1 exp=$2
  if ! grep -qx "$t" <<<"$TOPICS"; then printf "%-20s %-10s expected %s Hz\n" "$t" "MISSING" "$exp"; return; fi
  local hz
  hz=$(timeout -s INT 6 ros2 topic hz "$t" 2>/dev/null | awk '/average rate/ {r=$3} END {print r}')
  if [ -z "$hz" ]; then printf "%-20s %-10s expected %s Hz\n" "$t" "NO DATA" "$exp"
  else printf "%-20s %-10s %8.1f Hz (expected %s)\n" "$t" "OK" "$hz" "$exp"; fi
}

subs() {  # command topic -> needs a subscriber
  local t=$1
  if ! grep -qx "$t" <<<"$TOPICS"; then printf "%-20s %-10s\n" "$t" "MISSING"; return; fi
  local n
  n=$(ros2 topic info "$t" 2>/dev/null | awk -F': ' '/Subscription count/ {print $2}')
  printf "%-20s %-10s subscribers=%s\n" "$t" "$([ "${n:-0}" -gt 0 ] && echo OK || echo NO-SUB)" "${n:-0}"
}

echo "== sensor & status topics"
rate /IMU 200
rate /LIDAR/POINTS 10
rate /MOTION_INFO 20
rate /fault_aggregator 1
rate /CHARGE_STATUS "?"
echo "== command topics"
subs /MOTION_STATE
subs /GAIT
subs /NAV_CMD
EOF
chmod +x ~/ros2_topic_check.sh
~/ros2_topic_check.sh
```

Contoh output sehat:

```
== sensor & status topics
/IMU                 OK            199.8 Hz (expected 200)
/LIDAR/POINTS        OK             10.0 Hz (expected 10)
/MOTION_INFO         OK             20.0 Hz (expected 20)
/fault_aggregator    OK              1.0 Hz (expected 1)
/CHARGE_STATUS       NO DATA       expected ? Hz
== command topics
/MOTION_STATE        OK         subscribers=1
/GAIT                OK         subscribers=1
/NAV_CMD             OK         subscribers=1
```

`/CHARGE_STATUS` bisa *NO DATA* kalau statusnya cuma dipublish saat berubah — echo manual buat mastiin.

## 8. Troubleshooting

| Gejala | Penyebab umum | Cara cek / fix |
|---|---|---|
| `ros2 topic list` cuma `/parameter_events` `/rosout` | env belum di-source, `ROS_DOMAIN_ID` beda, atau pakai `sudo` | ulangi step 2 sebagai user biasa; `ros2 daemon stop && ros2 daemon start` |
| `The message type 'drdds/msg/…' is invalid` | definisi `drdds` belum di-source | step 3 |
| `echo` diam padahal `hz` ada | QoS mismatch | `ros2 topic echo /IMU --qos-reliability best_effort --qos-durability volatile` |
| `hz` jauh di bawah spec | CPU penuh / throttling / jaringan | GUI → Monitor → *Power & compute* (util & suhu per core); jalankan `hz` di host robot, bukan dari laptop |
| `/LIDAR/POINTS` kosong dari komputer lain | memang dibatasi ke host robot | echo di host robot; akses eksternal minta ke tech support |
| `/MOTION_STATE` dkk nggak punya subscriber | `motion_master` belum jalan | `ros2 node list`, `ps aux | grep -i motion_master`; topic §2.2 bergantung pada service ini |
| `/NAV_CMD` dipublish tapi robot diam | robot bukan di Navigation Mode / nggak standing | cek *Basic Status* di GUI: Usage mode = Navigation, Motion state = Stand |
| Data topic beda dengan report UDP | lihat host yang salah / beda timestamp | bandingin `header.timestamp` vs field `Time` di GUI Traffic |

## 9. Echo dari Mac / laptop (opsional)

ROS 2 native di macOS ribet, dan Docker Desktop di Mac nggak nerusin multicast DDS dengan baik.
Opsi yang realistis:

1. **SSH ke robot** dan jalankan semua di atas di sana (paling stabil — ini yang disarankan).
2. Mesin **Linux** di jaringan robot dengan distro ROS 2 yang sama, `RMW_IMPLEMENTATION` + `ROS_DOMAIN_ID` +
   profile DDS yang sama, dan package `drdds` ikut di-build (copy definisi dari `ros2 interface show`).
3. Dev container ROS 2 **Jazzy** (distro sama dengan robot) di Linux host dengan `--network host`.

Sementara itu semua yang lewat UDP/DTLS (command, 5 status report, error code) cukup dari Mac pakai
**EZRA UDP Debugger** — lihat README.
