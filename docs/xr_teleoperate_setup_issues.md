# xr_teleoperate 공식 가이드 그대로 따랐을 때 발생한 문제와 변경점

**작성일**: 2026-05-01
**대상**: Galaxy XR(SM-I610, Android 14) + Ubuntu 22.04 + USB `adb reverse` 환경
**목적**: 공식 [xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate) README §1 그대로 따라하면 우리 환경에서 어디서 막히는지, 어떻게 우회했는지를 한 페이지로 정리

본 문서는 [setup/](../setup/) 폴더에 들어 있는 자동화 스크립트(install.sh, gen_certs.sh, test_pose_only.py, diagnose.sh)가 **왜 필요한가**를 설명하는 reference입니다. 각 항목 끝에 관련 커밋 해시를 표시.

---

## 0. 우리 환경의 특수성 (배경)

공식 가이드는 다음을 가정:
- WiFi 환경 + 헤드셋과 PC가 같은 LAN에 있음
- 자체 SSL 인증서 만들어 모든 디바이스가 신뢰
- Apple Vision Pro / PICO 4 / Meta Quest 3가 공식 지원 디바이스
- `host="192.168.123.164"`(Unitree 기본 로봇 IP)에 teleimager 영상 서버가 떠 있음

우리 환경:
- **WiFi 없음** — Galaxy XR ↔ PC는 USB-C `adb reverse`(UsbFfs 채널)로만 통신
- Galaxy XR은 Android XR Chrome 기반 — 공식 지원 디바이스 목록에 없음
- teleimager 영상 서버는 Week 9까지 안 띄움 (Gate 2는 pose-only 검증)
- PC는 ROS Humble + cuMotion + 기존 torch 2.9 / pinocchio 3.9 stack — 다운그레이드 금지

이 차이가 아래 모든 충돌의 뿌리.

---

## 1. 발견된 문제와 변경점 (시간순)

### 1.1 Ubuntu 패키지 ADB가 glibc 2.35와 충돌 (Week 1)

**증상**:
```
ADB server didn't ACK
free(): invalid pointer
* failed to start daemon
```

**원인**: `apt install android-tools-adb`가 깔아주는 ADB 28.0.2-debian이 Ubuntu 22.04 glibc 2.35와 ABI 호환성 문제. 공식 README는 "ADB가 깔려있다고 가정"하고 별 언급 없음.

**변경 위치**: [setup/README.md](../setup/README.md) Step A

**변경 내용**: Ubuntu 패키지 제거 + Google 공식 platform-tools(35.x.x) 직접 설치 절차 명시. udev rules + plugdev 그룹까지 한 번에.

**커밋**: 초기 커밋(`69cb3c6`) Week 1 보고서에 이미 반영

---

### 1.2 conda env에 패키지 핀 시도 → `PackagesNotFoundError`

**증상**: 다른 PC에서 환경 구축 시 `PackagesNotFoundError: matplotlib=3.7.5*`.

**원인**: 초기 environment.yml에 `matplotlib=3.7.5`, `casadi`, `opencv`를 conda dependencies로 적어 둠. conda-forge에 그 정확한 patch 버전이 없거나 transitive dep와 충돌.

**중간 시도**: `casadi`만 conda에 두고 matplotlib/opencv는 pip로 — 하지만 다음 문제(§1.3) 유발.

**최종 변경 위치**: [setup/environment.yml](../setup/environment.yml)

**최종 변경 내용**: 공식 README와 **동일한 3개**(`python=3.10` / `pinocchio=3.1.0` / `numpy=1.26.4`)만 conda. 나머지는 모두 pip 또는 서브모듈 setup.py로 위임.

**커밋**: `3162273`

---

### 1.3 conda env 안에서 pip casadi → `uninstall-no-record-file`

**증상**:
```
error: uninstall-no-record-file
× Cannot uninstall casadi 3.6.7
The package's contents are unknown: no RECORD file was found for casadi
```

**원인**: conda-forge `pinocchio=3.1.0`이 transitive dep로 `casadi`를 conda 패키지로 미리 설치(RECORD 파일 없음). 이후 pip 섹션이 `casadi`를 다시 깔려고 uninstall 시도하다 실패.

**변경 위치**: [setup/install.sh](../setup/install.sh) §0

**변경 내용**: pip 섹션에서 `casadi`/`matplotlib`/`opencv` 제거. install.sh가 import 체크 후 분기:
```bash
python3 -c "import casadi" 2>/dev/null     || pip install casadi
python3 -c "import matplotlib" 2>/dev/null || pip install matplotlib==3.7.5
python3 -c "import cv2" 2>/dev/null        || pip install opencv-python
```

**커밋**: `513667e`, `3162273`

---

### 1.4 dex-retargeting이 system torch / pinocchio 다운그레이드

**증상**: 공식 README의 `pip install -e teleop/robot_control/dex-retargeting`을 그대로 실행하면:
- `pin 3.9.0 → 2.7.0` (cuMotion 깨짐)
- `torch 2.9.0 → 2.3.0` (torchvision/torchaudio 의존성 깨짐)
- `eigenpy`/`hpp-fcl`/`cmeel-*` 줄줄이 다운그레이드

**원인**: dex-retargeting이 `pin==2.7.0`, `torch==2.3.0`을 강제 핀. Unitree는 깨끗한 conda env를 가정하지만 우리는 ROS Humble + cuMotion stack이 이미 깔린 상태.

**변경 위치**: [setup/install.sh](../setup/install.sh) §5

**변경 내용**: `INSTALL_DEX_RETARGETING=1` opt-in 플래그. 기본값은 skip. Week 5(DG-5F retargeting 작업) 진입 시에만:
```bash
INSTALL_DEX_RETARGETING=1 bash setup/install.sh
```
깨끗한 conda env에서는 충돌 없으므로 이 플래그를 켜고 돌리면 됨.

**커밋**: `7b33cbb`

---

### 1.5 vuer 0.0.60 + params-proto 3.x 비호환

**증상**:
```
from vuer.server import Vuer
ImportError: cannot import name 'Flag' from 'params_proto'
```
vuer가 친절하게 "aiohttp 부족" 메시지를 띄우지만, 실제 원인은 다름.

**원인**: televuer가 transitive로 끌어오는 `params-proto` 최신 버전(3.x)에서 `Flag/PrefixProto/Proto` 심볼이 빠짐. vuer 0.0.60은 2.x 시리즈 가정.

**변경 위치**: [setup/install.sh](../setup/install.sh) §4

**변경 내용**:
```bash
pip install 'params-proto<3'
```

**커밋**: `7b33cbb`

---

### 1.6 vuer는 기본 설치로는 `Vuer` 심볼 노출 안 함

**증상**:
```python
>>> from vuer import Vuer
ImportError: cannot import name 'Vuer' from 'vuer'
```
vuer는 PyScript 환경 호환을 위해 aiohttp를 옵셔널로 둠.

**원인**: 공식 가이드는 `pip install vuer`만 적혀 있고 extras 언급 없음. 실제로는 `vuer[all]` 필요.

**변경 위치**: [setup/install.sh](../setup/install.sh) §0

**변경 내용**: `pip install 'vuer[all]==0.0.60'` 명시.

**커밋**: `7b33cbb`

---

### 1.7 vuer/televuer가 SSL cert를 강제 (cert 파일 부재 시 부팅 실패)

**증상**:
```
Vuer encountered an error: [Errno 2] No such file or directory
```

**원인**: televuer `televuer.py:91`에서 `Vuer(host='0.0.0.0', cert=cert_file, key=key_file, ...)`를 무조건 호출. 우리는 cert 파일을 안 만들었음. 공식 README §2.2~2.3에 cert 생성 절차가 있는데 우리 setup/README에는 누락.

**변경 위치**: [setup/gen_certs.sh](../setup/gen_certs.sh) (신규), [setup/install.sh](../setup/install.sh) §8

**변경 내용**: self-signed cert 자동 생성 스크립트. `~/.config/xr_teleoperate/cert.pem|key.pem`에 배치 (televuer가 자동 검색하는 경로). install.sh 마지막 단계에서 자동 호출. idempotent — 이미 있으면 skip, `--force`로 재생성.

**커밋**: `7b33cbb`

---

### 1.8 업스트림 example/test_televuer.py가 teleimager 영상 서버를 강제

**증상**:
```
WARNING Request to 192.168.123.164:60000 timed out or no response, using local config
INFO Loaded camera config from local cam_config_server.yaml
Visit: https://vuer.ai?grid=False
Vuer encountered an error: [Errno 2] No such file or directory
```
(cert 문제를 고쳐도) `img_client.get_head_frame()`에서 또 막힘.

**원인**: `example/test_televuer.py`/`test_tv_wrapper.py` 둘 다 `host="192.168.123.164"`(Unitree 기본 로봇 IP)의 teleimager 영상 서버에서 카메라 프레임을 받아 `tv.render_to_xr(img)`로 vuer에 그림. Week 2 Gate 2는 pose-only 검증이라 영상 서버 미가동.

**변경 위치**: [setup/test_pose_only.py](../setup/test_pose_only.py) (신규)

**변경 내용**: TeleVuer를 다음 파라미터로 부팅해 영상 의존성 완전 제거:
```python
TeleVuer(
    use_hand_tracking=True,
    binocular=False,
    img_shape=(480, 640),       # dummy
    display_fps=30.0,
    display_mode="pass-through",  # ← zmq/webrtc 없이 pose만
    zmq=False,
    webrtc=False,
)
```
추가로 두 가지 모드:
- **smoke** (기본): 1Hz 로그로 Hz/NaN/좌표 모니터링
- **measure** (`--measure 30 --report ...`): 30초 자동 측정 → markdown 보고서 append (mean Hz / recovery latency / wrist jitter / NaN/lost 통계)

**커밋**: `7b33cbb`

---

### 1.9 vuer params_proto가 우리 argparse를 가로챔

**증상**: `python3 setup/test_pose_only.py --help` 출력에 우리가 추가한 `--measure`, `--report` 옵션이 안 보이고 vuer 내부 옵션만 나옴.

**원인**: televuer 임포트 시 vuer가 자동으로 params_proto로 sys.argv를 처리. 우리 argparse가 동작할 때는 이미 argv가 가공됨.

**변경 위치**: [setup/test_pose_only.py](../setup/test_pose_only.py) 상단

**변경 내용**: argparse를 televuer 임포트 **이전**에 수행, 그 다음 `sys.argv = sys.argv[:1]`로 비워 vuer가 추가 옵션을 못 보게 함.

**커밋**: `7b33cbb`

---

### 1.10 Galaxy XR Chrome이 self-signed cert를 SAN 추가해도 거부

**증상**: PC Chrome에서는 `https://localhost:8012` 정상 동작(첫 접속 시 cert cache). **Galaxy XR Chrome에서는 "이 페이지가 작동하지 않습니다"** — cert 경고 화면조차 안 뜨고 ERR_EMPTY_RESPONSE.

**원인 1차 가설 (부분 해결)**: cert에 SubjectAltName 누락 — Chrome 58+은 CN-only cert를 invalid로 즉시 거부.

**1차 변경 위치**: [setup/gen_certs.sh](../setup/gen_certs.sh)

**1차 변경 내용**: SAN + serverAuth EKU 추가:
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ... -out ... -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1" \
  -addext "basicConstraints=CA:FALSE" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"
```

추가로 [setup/diagnose.sh](../setup/diagnose.sh) 신규 — connectivity 5단계 자동 점검(cert SAN / 8012 LISTEN / curl HTTP/HTTPS / adb).

**커밋**: `c4a8081`

---

### 1.11 SAN cert도 Galaxy XR이 거부 → plain HTTP로 우회 (최종 해결)

**증상**: §1.10의 SAN cert로도 여전히 ERR_EMPTY_RESPONSE.

**핵심 발견**: Week 1에 webxr-samples를 `python3 -m http.server 8080`으로 띄웠을 때는 문제없이 동작 — Galaxy XR Chrome이 `http://localhost`는 W3C secure context 예외로 인정해 평문 HTTP에서도 WebXR API가 그대로 노출됨. 즉 self-signed HTTPS는 Android XR Chrome이 매우 strict하지만, plain HTTP localhost는 통과.

**vuer 소스 분석**: [vuer/base.py:119-120](file:///usr/local/lib/python3.10/dist-packages/vuer/base.py)
```python
if not self.cert:
    site = web.TCPSite(runner, self.host, self.port)
```
cert가 None이면 자동으로 plain HTTP로 떨어짐. 즉 우회 가능.

다만 televuer의 `__init__`(line 71-89)이 cert를 항상 non-None 경로로 채워서 vuer를 호출. 이를 monkey-patch로 우회.

**변경 위치**: [setup/test_pose_only.py](../setup/test_pose_only.py) `--http` 옵션

**변경 내용**:
```python
def _force_plain_http() -> None:
    _OrigVuer = _tv_mod.Vuer
    class _PlainHTTPVuer(_OrigVuer):
        def __init__(self, *args, **kwargs):
            kwargs["cert"] = None
            kwargs["key"] = None
            super().__init__(*args, **kwargs)
    _tv_mod.Vuer = _PlainHTTPVuer
```
`--http` 플래그가 있으면 TeleVuer 임포트 후 첫 호출 전에 위 monkey-patch 적용 → vuer가 평문 HTTP로 부팅.

[setup/diagnose.sh](../setup/diagnose.sh) §3도 HTTP/HTTPS 둘 다 시도해 서버 모드를 자동 감지하도록 수정.

[setup/README.md](../setup/README.md) Step G default도 `--http` 권장으로 표기.

**커밋**: `ba4641a`

---

## 2. 변경 결과: setup/ 폴더 구조

```
src/xr_teleop/setup/
├── README.md          # 다른 PC 재현 가이드 (Step A~G)
├── environment.yml    # 공식과 동일 3개 패키지만 (python/pinocchio/numpy)
├── install.sh         # clone + 서브모듈 + pip + cert 생성 + numpy 가드
├── verify.py          # 8개 모듈 import 점검
├── gen_certs.sh       # self-signed cert (SAN + EKU 포함, idempotent)
├── test_pose_only.py  # teleimager 의존성 제거, --http 모드, --measure 모드
└── diagnose.sh        # connectivity 5단계 자동 점검
```

다른 PC에서 워크플로우:
```bash
git clone <our_repo>/xr_teleop && cd xr_teleop
conda env create -f setup/environment.yml
conda activate tv
bash setup/install.sh                       # clone + deps + cert
adb reverse tcp:8012 tcp:8012
python3 setup/test_pose_only.py --http      # ← --http 권장
# 다른 터미널: bash setup/diagnose.sh        # 4/4 OK 확인
```

---

## 3. 향후 upstream 머지 시 주의사항

xr_teleoperate가 업데이트되면 위 11개 우회 중 **일부는 upstream에서 해결될 수도 있음**. 머지 전 체크리스트:

| 항목 | upstream 해결 가능성 | 우리 코드 영향 |
|---|---|---|
| ADB 호환성(§1.1) | 전혀 없음 (OS-level) | setup/README Step A 영구 유지 |
| environment.yml 단순화(§1.2) | upstream도 단순함 — 우리만 잘못 풀었던 케이스 | 이미 일치, 변경 불필요 |
| pip casadi RECORD(§1.3) | conda+pip 구조 한계 — 영구 | install.sh §0 유지 |
| dex-retargeting 다운그레이드(§1.4) | dex-retargeting 측이 핀 풀어주면 해결 | 풀리면 INSTALL_DEX_RETARGETING 기본 1로 |
| params-proto<3(§1.5) | vuer 신버전 채택 시 해결 | install.sh §4 신중히 풀기 |
| vuer[all](§1.6) | 영구 (vuer 설계상) | install.sh §0 유지 |
| cert 자동 생성(§1.7) | upstream README §2.2와 동일 — 우리는 자동화만 추가 | gen_certs.sh 유지 |
| pose-only 테스트(§1.8) | upstream은 영상 서버 가정 — 우리만의 변형 | test_pose_only.py 유지 |
| argparse 가로챔(§1.9) | vuer 측 수정 시 해결 | test_pose_only.py 상단 유지 |
| SAN cert(§1.10) | self-signed 본질 — 영구 | gen_certs.sh 유지 |
| **plain HTTP 모드(§1.11)** | **Android XR Chrome 정책 영구** | **--http 모드 영구 유지, default로 두는 게 안전** |

특히 §1.11은 본질적으로 "Galaxy XR Chrome이 self-signed HTTPS를 강하게 거부한다"는 정책 문제라, upstream이 cert 절차를 아무리 다듬어도 우리 환경에선 plain HTTP가 정답입니다. Native Android XR app으로 이행하기 전(Phase 3+)까지는 `--http`가 default.

---

## 4. 관련 문서

- [setup/README.md](../setup/README.md) — 다른 PC 재현 step-by-step 가이드
- [docs/CLAUDE.md](CLAUDE.md) — 프로젝트 전체 컨텍스트
- [docs/week1_report.md](week1_report.md) — Week 1 (ADB/WebXR Gate 1) 보고서
- [docs/xr_teleoperate_weekly_plan.md](xr_teleoperate_weekly_plan.md) — 12주 상세 계획
- [docs/xr_teleoperate_tech_analysis.md](xr_teleoperate_tech_analysis.md) — 기술 스택 분석 + 한계
- 공식 [xr_teleoperate README §1](../xr_teleoperate/README.md) — 비교 대상

---

*끝.*
