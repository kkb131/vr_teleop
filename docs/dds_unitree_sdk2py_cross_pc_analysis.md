# unitree_sdk2py cross-PC DDS 통신 실패 — 레이어 분석 + 해결 전략

작성: 2026-05-13. 조종 PC (humble) ↔ 로봇 PC (jazzy, sim 컨테이너) 환경에서 `rt/lowstate` 등 unitree DDS 토픽이 cross-PC 로 전혀 도달하지 않는 문제의 근본 원인을 코드 레벨에서 분석.

---

## 1. 관찰된 증상 요약

| 테스트 | 결과 | 의미 |
|---|---|---|
| UDP socket pingpong (port 7700, 7660, 7661) 양방향 | **PASS** | network/firewall OK |
| ROS2 rclpy `std_msgs/String` cross-PC pub/sub (humble↔jazzy) | **PASS** | RMW + cyclonedds C library 는 cross-PC discovery 성공 |
| unitree_sdk2py `rt/lowstate` **local** (robot PC 내) | **PASS** (1339 msg / 15s) | sim publish OK, 로컬 cyclonedds 동작 |
| unitree_sdk2py `rt/lowstate` **cross-PC** (robot PC publish → control PC sub) | **FAIL** (0 msg / 15s) | cross-PC unitree DDS 단절 |
| 우리 cyclonedds.xml 에 `<Tracing>` 추가 | unitree.py 사용 시 trace log 비어있음 | **우리 xml 자체가 unitree path 에 적용되지 않음** |
| rclpy 사용 시 trace log 정상 | rclpy path 에서는 우리 xml 적용됨 | rclpy 와 unitree_sdk2py 의 cyclone 사용 경로가 다름 |

핵심 비대칭: 같은 환경, 같은 `CYCLONEDDS_URI`, 같은 도메인 (1) 인데 **rclpy 는 cross-PC OK / unitree_sdk2py 는 cross-PC FAIL**.

---

## 2. 두 통신 스택의 레이어 구조 비교

### 2.1 rclpy (ros2.py) 스택 — cross-PC PASS

```
┌─────────────────────────────────────────┐
│ Python: rclpy.create_publisher(...)     │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│ C++: rcl + rmw_cyclonedds_cpp           │
│   librmw_cyclonedds_cpp.so              │
│   /opt/ros/{humble,jazzy}/lib/          │
└──────────────────┬──────────────────────┘
                   │
                   │  CYCLONEDDS_URI env 읽음
                   │  → file:///.../cyclonedds.xml 적용
                   │  → <Peers>, <AllowMulticast>false</...> 적용
                   │
┌──────────────────▼──────────────────────┐
│ C: libddsc.so.0   (ROS 번들)             │
│   /opt/ros/.../libddsc.so.0             │
│   → DomainParticipant 생성              │
│   → RTPS 전송 (unicast peers)           │
└─────────────────────────────────────────┘
```

**핵심**: rmw_cyclonedds_cpp 가 표준 cyclonedds C API 를 호출하면서 cyclonedds 가 `CYCLONEDDS_URI` 환경변수를 읽어 xml 의 `<Peers>` 와 `<AllowMulticast>false</>` 를 적용. 따라서 unicast discovery 가 cross-PC 로 성공.

### 2.2 unitree_sdk2py (unitree.py, sim_main.py) 스택 — cross-PC FAIL

```
┌─────────────────────────────────────────────────┐
│ Python: ChannelPublisher / ChannelSubscriber    │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ Python: unitree_sdk2py.core.channel             │
│   ChannelFactory.Init(id, networkInterface)     │
│   ├─ channel_config.py 의 하드코드 XML 로드      │ ◀── ⚠️ HERE
│   ├─ networkInterface 없으면: autodetermine     │
│   └─ Domain(id, config=하드코드XML) 생성        │
└──────────────────┬──────────────────────────────┘
                   │
                   │  ⚠️ CYCLONEDDS_URI 무시!
                   │     (Domain 객체에 직접 config 주입)
                   │
┌──────────────────▼──────────────────────────────┐
│ Python: cyclonedds (PyPI wheel)                 │
│   Domain(id, config_xml) → DomainParticipant    │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ C: libddsc.so   (PyPI wheel 번들, ROS 와 별개) │
│   /usr/local/.../cyclonedds/.libs/libddsc.so    │
│   → 하드코드 XML 의 autodetermine + multicast   │
│   → SPDP via 멀티캐스트 (239.255.0.1)            │
│   → cross-PC 안 닿음                            │
└─────────────────────────────────────────────────┘
```

**핵심**: unitree_sdk2py 의 `ChannelFactory.Init()` 이 **자체 XML 문자열** 을 `Domain()` 생성자에 직접 주입. cyclonedds 의 일반 환경변수 경로 (`CYCLONEDDS_URI` 읽기) 가 **완전히 우회**됨.

---

## 3. 결정적 증거 코드

### 3.1 unitree_sdk2py 의 하드코드 XML — Peers 없음, 멀티캐스트 의존

[`unitree_sdk2py/core/channel_config.py`](`pip show unitree_sdk2py` 의 Location 안 의 `core/channel_config.py`)

**networkInterface 미지정 케이스 (sim_main.py 가 사용하는 경로)**:

```xml
<CycloneDDS>
    <Domain Id="any">
        <General>
            <Interfaces>
                <NetworkInterface autodetermine="true"
                                  priority="default"
                                  multicast="default" />
            </Interfaces>
        </General>
    </Domain>
</CycloneDDS>
```

**없는 것** (cross-PC 통신에 필수인데 빠진 항목):
- `<Discovery><Peers><Peer address="..."/></Peers></Discovery>` — unicast 상대 IP 명시
- `<General><AllowMulticast>false</AllowMulticast></General>` — 멀티캐스트 차단
- `<Discovery><MaxAutoParticipantIndex>N</...>` — 참여자 인덱스 prob 범위

→ 이 XML 만으로는 **같은 L2 (멀티캐스트 가능 네트워크) 안에서만** 통신 가능. 라우터/스위치/AP 가 멀티캐스트 차단하면 즉시 단절.

### 3.2 sim_main.py 의 DDS 초기화 — 두 번째 인자 없음

[`unitree_sim_isaaclab/dds/dds_master.py:60`](src/unitree_sim_isaaclab/dds/dds_master.py#L60):

```python
def _init_dds(self) -> bool:
    if self.dds_initialized:
        return True
    try:
        ChannelFactoryInitialize(1)   # ⚠️ 두 번째 인자 (networkInterface) 없음
        self.dds_initialized = True
```

→ sim 은 `autodetermine="true"` 경로로 들어감. multicast=default + Peers 없음.

[`unitree_sim_isaaclab/sim_main.py:446`](src/unitree_sim_isaaclab/sim_main.py#L446) 의 안내 문구도 **domain 만 맞추라고 함** (네트워크 interface / unicast peers 언급 없음):

> "Please ensure that other DDS instances use the same channel for message exchange by setting: ChannelFactoryInitialize(1)."

### 3.3 xr_teleop production 코드 — 같은 limitation

[`xr_teleop/scripts/ur10e_arm_controller.py:98-100`](src/xr_teleop/scripts/ur10e_arm_controller.py#L98-L100):

```python
self.lowcmd_publisher = ChannelPublisher(kTopicLowCommand_Debug, hg_LowCmd)
self.lowcmd_publisher.Init()
self.lowstate_subscriber = ChannelSubscriber(kTopicLowState, hg_LowState)
```

[`xr_teleop/xr_teleoperate/teleop/robot_control/robot_arm.py:88-103`](src/xr_teleop/xr_teleoperate/teleop/robot_control/robot_arm.py#L88-L103):

```python
self.lowstate_subscriber = ChannelSubscriber(kTopicLowState, hg_LowState)
self.lowstate_subscriber.Init()
# ...
# line 103
ChannelFactoryInitialize(1, networkInterface=args.network_interface)
```

→ production 코드는 `--network-interface` CLI flag 를 받아 두 번째 인자로 넘김. 즉 **사용자가 명시적으로 NIC 를 지정해야** unicast 가능한 환경에서 동작. **여전히 Peers 는 불가** (XML 에 박혀있지 않음).

### 3.4 libddsc.so 두 개 공존 — wire 호환되지만 config 경로가 다름

| 사용자 | libddsc 경로 | config 경로 |
|---|---|---|
| rclpy (ROS2) | `/opt/ros/{distro}/lib/...` | `CYCLONEDDS_URI` env |
| unitree_sdk2py | `cyclonedds` PyPI wheel 안의 `.libs/libddsc.so` | unitree_sdk2py 가 직접 주입한 XML |

같은 RTPS wire 프로토콜이라 두 stack 끼리도 통신 가능하지만, **config 가 다른 경로로 들어가서 우리 xml 이 한쪽에만 적용**됨.

---

## 4. 왜 이런 증상이 나오는지 — 메커니즘

### 4.1 로컬 (robot PC 내) 은 왜 PASS?

같은 머신 내에서는:
- sim 의 cyclonedds 가 자체 XML 로 멀티캐스트 → 로컬 loopback / 같은 NIC 에서 자기 자신이 받음
- 같은 머신의 test 스크립트도 같은 멀티캐스트 그룹 join 가능
- 라우터/스위치 안 거치므로 멀티캐스트 전달 OK

→ 1339 msg / 15s.

### 4.2 cross-PC 는 왜 FAIL?

- sim 은 `239.255.0.1` 멀티캐스트로만 SPDP/user-data 송신 (Peers 없음)
- 조종 PC ↔ 로봇 PC 사이 라우터/AP/회사 방화벽이 멀티캐스트 차단
- 멀티캐스트 패킷이 조종 PC 에 도달 안 함
- 조종 PC 의 unitree.py 도 멀티캐스트 모드라 sim 을 발견 못 함
- → 0 msg.

### 4.3 ros2.py 는 왜 PASS?

- rclpy 가 rmw_cyclonedds_cpp 통해 cyclonedds 호출
- cyclonedds 가 `CYCLONEDDS_URI` 읽음 → 우리 xml 의 `<Peers>` 적용
- ROS2 cross-PC discovery 가 unicast 로 진행 → PASS

### 4.4 우리 cyclonedds.xml 에 추가한 `<Tracing>` 이 비어있는 이유

unitree_sdk2py 는 자체 XML 만 쓰므로 우리 xml 의 `<Tracing>` 도 무시. 그래서 `/tmp/unitree_trace.log` 가 비어있음. (rclpy 로 테스트하면 채워짐 — 별도 검증 가능)

---

## 5. 해결 전략 (네 가지, 채택 추천 순)

### 전략 A — unitree_sdk2py 의 하드코드 XML 패치 ⭐ 가장 안정적

`channel_config.py` 의 XML 에 `<Peers>` 와 `<AllowMulticast>false</>` 를 추가. 양쪽 PC 의 unitree_sdk2py 설치본을 동일하게 패치.

**적용 위치**: `pip show unitree_sdk2py` 의 Location → `unitree_sdk2py/core/channel_config.py`

**원본 (예시, autodetermine 케이스)**:
```python
DDS_XML_TEMPLATE_AUTO = '''<CycloneDDS>
    <Domain Id="any">
        <General>
            <Interfaces>
                <NetworkInterface autodetermine="true" priority="default" multicast="default" />
            </Interfaces>
        </General>
    </Domain>
</CycloneDDS>'''
```

**패치 후**:
```python
DDS_XML_TEMPLATE_AUTO = '''<CycloneDDS>
    <Domain Id="any">
        <General>
            <Interfaces>
                <NetworkInterface autodetermine="true" priority="default" multicast="default" />
            </Interfaces>
            <AllowMulticast>false</AllowMulticast>
        </General>
        <Discovery>
            <ParticipantIndex>auto</ParticipantIndex>
            <MaxAutoParticipantIndex>32</MaxAutoParticipantIndex>
            <Peers>
                <Peer address="<로봇PC_IP>"/>
                <Peer address="<조종PC_IP>"/>
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>'''
```

장점: 코드 변경 최소. sim 과 teleop 둘 다 영향. 명확한 root-cause fix.  
단점: 양쪽 PC 의 unitree_sdk2py 설치본을 매번 패치해야 함 (upgrade 시 재패치). hard-coded IP.

**자동화 옵션**: install.sh 의 unitree_sdk2py 설치 직후 `sed` 로 자동 패치하는 단계 추가.

### 전략 B — 환경변수 기반 동적 패치 (모듈 import 시점 monkey-patch) ⭐ 권장

unitree_sdk2py 의 `ChannelFactoryInitialize` 를 사용 직전에 wrapping 해서 우리 xml 을 주입.

**구현 예** (`scripts/dds_test/unitree.py` 시작부에 추가):

```python
import os
def _patch_unitree_dds_config():
    """unitree_sdk2py 가 자체 XML 대신 우리 CYCLONEDDS_URI 를 쓰도록 변경.

    unitree_sdk2py.core.channel_config.DDS_XML_TEMPLATE_AUTO (또는 동등 변수) 를
    우리 cyclonedds.xml 내용으로 교체. CYCLONEDDS_URI 가 file:// 일 때만.
    """
    uri = os.environ.get("CYCLONEDDS_URI", "")
    if not uri.startswith("file://"):
        return
    path = uri[len("file://"):]
    if not os.path.isfile(path):
        return
    with open(path) as f:
        xml_content = f.read()

    from unitree_sdk2py.core import channel_config
    # 변수 이름은 실제 channel_config.py 확인 후 매핑
    for attr in dir(channel_config):
        if attr.startswith("DDS_XML") or "TEMPLATE" in attr:
            if isinstance(getattr(channel_config, attr), str):
                setattr(channel_config, attr, xml_content)

_patch_unitree_dds_config()

# 이제 ChannelFactoryInitialize 호출
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(1)
```

장점: 코드 수정 없이 런타임에 우리 xml 적용. CYCLONEDDS_URI 가 single source of truth 가 됨.  
단점: 변수 이름이 unitree_sdk2py 버전마다 다를 수 있음. monkey-patch 라 fragile.

### 전략 C — sim_main.py / xr_teleop production 코드 모두 동일 cyclonedds.xml 외부 mount

전략 A 의 변형. 양쪽 unitree_sdk2py 의 channel_config.py 가 **파일에서 XML 을 읽도록** 수정:

```python
import os
DDS_XML_PATH = os.environ.get("UNITREE_DDS_XML",
    "/etc/unitree/cyclonedds.xml")
if os.path.isfile(DDS_XML_PATH):
    with open(DDS_XML_PATH) as f:
        DDS_XML_TEMPLATE_AUTO = f.read()
else:
    DDS_XML_TEMPLATE_AUTO = '''<CycloneDDS>...(기존 하드코드)...</CycloneDDS>'''
```

장점: 외부 파일로 분리 → 환경별 다른 설정 가능. docker volume mount 친화.  
단점: 양쪽 PC 의 unitree_sdk2py 패치 + 외부 파일 배포 모두 필요.

### 전략 D — 같은 L2 (스위치/AP) 로 두 PC 묶기 — 코드 변경 없이

조종 PC 와 로봇 PC 를 같은 WiFi AP 또는 같은 유선 스위치에 두어 멀티캐스트가 전달되게 함. IGMP snooping 활성화 또는 비활성화 (환경에 따라).

장점: 코드 손 안 댐.  
단점: 무선 환경 / 회사 네트워크에서는 멀티캐스트 신뢰성 낮음. 운영 환경 (분리된 사이트) 에서는 사실상 불가.

---

## 6. 검증 계획

전략 A 또는 B 적용 후:

### 6.1 unitree_sdk2py 가 우리 xml 을 진짜로 읽는지

조종 PC 에서 (env 정상 source 후):

```bash
# 우리 cyclonedds.xml 에 <Tracing OutputFile=/tmp/unitree_trace.log> 가 들어있다고 가정
: > /tmp/unitree_trace.log

python3 - <<'PY'
# 전략 B 의 monkey-patch 또는 전략 A 의 패치된 unitree_sdk2py 사용 가정
import time
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(1)
time.sleep(2)
PY

# 비어있지 않으면 적용 성공
ls -la /tmp/unitree_trace.log
head -30 /tmp/unitree_trace.log
```

기대: cyclonedds tracing 라인 (`config: ...`, `Interface: ...`, `Discovery/Peers: ...`) 이 보임.

### 6.2 cross-PC rt/lowstate 도달

```bash
# 조종 PC
python3 - <<'PY'
import time
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
ChannelFactoryInitialize(1)
n=[0]
s=ChannelSubscriber("rt/lowstate", LowState_)
s.Init(lambda m: n.__setitem__(0,n[0]+1), 32)
time.sleep(10); s.Close()
print(f"cross-PC rt/lowstate: {n[0]} / 10s  (sim 정상이면 ~940)")
PY
```

기대: 수백 ~ 1000 개 (≈94Hz × 10s).

### 6.3 tcpdump 으로 sim 의 unicast 송신 확인

```bash
# 로봇 PC 호스트
sudo tcpdump -ni any 'dst host <조종PC_IP> and udp portrange 7400-7700' -c 10
```

기대: `→ <조종PC_IP>:7660`, `:7661` 등 unicast 송신 (이전엔 `→ 239.255.0.1` 만 나왔음).

### 6.4 production 시나리오 — teleop_hand_and_arm.py 동작

```bash
# 조종 PC
python3 scripts/run_teleop_ws.py --ee dex3 --sim
```

기대: `[robot_arm] subscribed rt/lowstate, first message OK` 같은 로그 정상 출력. 헤드셋에서 손 움직임이 sim 에 반영됨.

---

## 7. 권장 채택 순서

1. **단기 진단 확정** (오늘): 전략 B 의 monkey-patch 를 [scripts/dds_test/unitree.py](src/xr_teleop/scripts/dds_test/unitree.py) 에 추가 → cross-PC rt/lowstate 가 수신되는지 즉시 검증. **이게 PASS 면 가설 100% 확정**.
2. **운영 fix** (단기): 전략 A 로 양쪽 PC 의 unitree_sdk2py/channel_config.py 를 패치. install.sh 에 자동화 단계 추가.
3. **장기 개선** (옵션): 전략 C 로 외부 xml 파일 mount 방식으로 전환. fork repo / upstream PR 검토.

---

## 8. 참고 — 영향받는 토픽 / 코드

unitree_sdk2py 를 쓰는 모든 DDS 토픽이 동일 문제. 즉 cross-PC 단절은 다음 전부에 해당:

| 토픽 | 사용처 |
|---|---|
| `rt/lowstate` | sim → teleop (35 motor state, IMU) |
| `rt/lowcmd` | teleop → sim (PD targets) |
| `rt/dex3/{left,right}/{state,cmd}` | sim ↔ teleop (Dex3 hands) |
| `rt/sim_state`, `rt/reset_pose/cmd`, `rt/run_command/cmd` | meta-control |

전략 A/B 둘 다 한 번에 해결 (XML 은 토픽별이 아니라 participant 별 적용).

---

## 9. 미해결 / 추가 조사 필요

- channel_config.py 의 XML 변수 정확한 이름 (1.0.1 버전 기준): `pip show unitree_sdk2py` 의 Location 에서 직접 확인 필요. 위 monkey-patch 예시에서 attr 명을 `DDS_XML*` 로 wildcard 검색하는 이유.
- 만약 unitree_sdk2py 가 자체 cyclonedds wheel 의 ABI 와도 묶여있다면, libddsc.so 호환성 별도 검증 필요. 하지만 로컬 1339 msg/15s 가 나오므로 현재 wheel 자체는 정상 동작.
- 전략 A 패치를 upstream `unitree_sdk2_python` repo 에 PR 로 제출 가능 (cyclonedds 표준 환경변수 honor 하는 fallback 추가).

---

## 부록 — 관련 파일

- [scripts/cyclonedds.xml](src/xr_teleop/scripts/cyclonedds.xml) — 우리 xml. rclpy 에는 적용되지만 unitree_sdk2py 에는 무시됨.
- [scripts/dds_env.sh](src/xr_teleop/scripts/dds_env.sh) — env source script.
- [scripts/dds_test/unitree.py](src/xr_teleop/scripts/dds_test/unitree.py) — 진단 스크립트, 전략 B 의 monkey-patch 시도 위치.
- [scripts/dds_test/ros2.py](src/xr_teleop/scripts/dds_test/ros2.py) — 비교용 rclpy path (정상 동작).
- [scripts/ur10e_arm_controller.py](src/xr_teleop/scripts/ur10e_arm_controller.py) — production unitree_sdk2py 사용 예.
- 외부 (컨테이너 안): `unitree_sim_isaaclab/dds/dds_master.py`, `unitree_sim_isaaclab/sim_main.py`.
- 패치 대상 (컨테이너 안 + 조종 PC 둘 다): `<unitree_sdk2py_install_path>/core/channel_config.py`.
