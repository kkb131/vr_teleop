# xr_teleoperate 환경 구축 가이드 (다른 PC 재현용)

이 폴더는 **Galaxy XR과 USB로 연결되는 조종 PC**에 xr_teleoperate 개발 환경을 그대로 재현하기 위한 자료입니다. Week 1 보고서의 ADB/USB 설정 + Week 2 conda 환경 + xr_teleoperate clone을 한 번에 끝낼 수 있도록 정리했습니다.

## 사전 요건

- **OS**: Ubuntu 22.04 (Week 1에서 검증된 조합)
- **하드웨어**: Galaxy XR (SM-I610) + USB-C 데이터 케이블
- **권장**: NVIDIA RTX GPU (추후 NVENC 인코딩에 사용)
- **계정**: sudo 가능한 일반 사용자

> 📝 Docker 컨테이너에서 작업하는 경우 Step A~C는 호스트에서 1회만 수행해도 되고, conda 대신 system pip로 설치해도 됩니다(자세한 내용은 본 폴더 외부의 `docs/CLAUDE.md` §6 참고).

---

## Step A — Google 공식 ADB(platform-tools) 설치

> ⚠️ Ubuntu 패키지(`android-tools-adb`)는 glibc 2.35 호환성 문제로 데몬 시작 시 `free(): invalid pointer` 에러가 납니다(Week 1에서 확인). **반드시 Google 공식 빌드를 사용하세요.**

```bash
# 기존 패키지 ADB 제거 (있을 경우)
sudo apt remove --purge android-tools-adb android-tools-fastboot 2>/dev/null || true
sudo apt autoremove -y

# Google 공식 platform-tools 설치
cd /tmp
wget -q https://dl.google.com/android/repository/platform-tools-latest-linux.zip
unzip -q platform-tools-latest-linux.zip
sudo mv platform-tools /opt/

# PATH 등록 (bashrc)
grep -q '/opt/platform-tools' ~/.bashrc || \
  echo 'export PATH=/opt/platform-tools:$PATH' >> ~/.bashrc
export PATH=/opt/platform-tools:$PATH

adb --version    # "Version 35.x.x" 표시되면 정상
```

## Step B — udev rules + plugdev 그룹 (Samsung VID 04e8)

```bash
sudo usermod -aG plugdev "$USER"
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/51-android.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
# 로그아웃 후 재로그인 (또는 재부팅)
```

연결 후 인식 확인:
```bash
adb devices
# 처음에는 "unauthorized" → Galaxy XR 헤드셋 안에서 RSA 키 지문 팝업 "이 컴퓨터에서 항상 허용" 체크
adb devices
# R3KYA01R62L device   ← 정상
```

## Step C — Miniconda 설치 (없을 경우)

```bash
cd /tmp
wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p "$HOME/miniconda3"
"$HOME/miniconda3/bin/conda" init bash
source ~/.bashrc
conda --version
```

## Step D — conda env 생성

```bash
cd <이 README가 있는 폴더의 상위 폴더, 즉 src/xr_teleop/>
conda env create -f setup/environment.yml
conda activate tv
```

생성되는 환경 `tv` — **공식 README와 동일하게 conda는 3개 패키지만**:
- Python 3.10
- pinocchio 3.1.0 (conda-forge)
- numpy 1.26.4 (pinocchio ABI 호환을 위해 <2 고정)

> 💡 **왜 3개만?** 공식 가이드도 동일. casadi/matplotlib/opencv를 conda로 핀하면 conda-forge에 정확한 patch 버전이 없거나(matplotlib=3.7.5*) transitive dep끼리 RECORD 파일 충돌(`uninstall-no-record-file`)이 납니다. 나머지는 모두 install.sh가 pip로 처리.

## Step E — xr_teleoperate clone + editable install

```bash
bash setup/install.sh
```

이 스크립트가 수행하는 작업 (공식 가이드 절차와 동일):
1. `src/xr_teleop/xr_teleoperate/`에 upstream clone (https://github.com/unitreerobotics/xr_teleoperate)
2. `git submodule update --init --depth 1` (televuer / dex-retargeting / teleimager)
3. `pip install -e teleop/teleimager --no-deps` (공식 권장)
4. `pip install -e teleop/televuer` — vuer / casadi / meshcat / matplotlib 등이 transitive로 함께 들어옴
5. **호환성 핀**: `pip install 'params-proto<3'` (vuer 0.0.60는 3.x에서 ImportError)
6. `unitree_sdk2_python` (PyPI 우선, 실패 시 GitHub fallback)
7. numpy 가드 — pip가 numpy 2.x로 끌어올렸으면 `<2`로 강제 다운그레이드

> ⚠️ **dex-retargeting는 기본적으로 설치 안 함**: Week 5에서 DG-5F 손 retargeting 작업 시 사용. 깨끗한 conda env(`tv`)에서 `INSTALL_DEX_RETARGETING=1 bash setup/install.sh`로 재실행하면 함께 설치됨. 시스템 torch/pinocchio가 이미 다른 버전으로 깔린 환경(예: 우리 Docker)에서는 충돌이 일어나므로 자동 설치를 막아둠.

## Step F — sanity check

```bash
python3 setup/verify.py
```

기대 결과:
```
[OK]   numpy                  1.26.4
[OK]   pinocchio              3.1.0
[OK]   casadi                 ...
[OK]   meshcat                ...
[OK]   vuer                   0.0.60
[OK]   televuer               ...
[OK]   dex_retargeting        ...
[OK]   unitree_sdk2py         ...
[adb reverse] ...
[PASS] all checks ok
```

## Step G — televuer 단독 검증 (Gate 2)

**터미널 1 (PC)**:
```bash
# Galaxy XR USB-C 연결 후
adb devices                      # R3KYA01R62L device 확인
adb reverse tcp:8012 tcp:8012    # televuer WebSocket 포트
adb reverse --list               # UsbFfs tcp:8012 tcp:8012 확인

cd src/xr_teleop/xr_teleoperate
python3 teleop/televuer/test/_test_televuer.py
# 또는 wrapper 후처리까지 포함:
# python3 teleop/televuer/test/_test_tv_wrapper.py
```

**Galaxy XR (Chrome)**:
- `http://localhost:8012` 접속 (adb reverse → localhost는 HTTPS 예외로 평문 OK)
- 인증서 강제 시 fallback: `https://localhost:8012/?ws=ws://localhost:8012` 후 self-signed 수동 신뢰

**Gate 2 통과 조건** (자세한 내용은 `docs/xr_teleoperate_weekly_plan.md` Week 2):

| 항목 | 통과 기준 |
|---|---|
| TeleData 필드 | head/wrist/hand_joints 모두 NaN 없이 채워짐 |
| 스트리밍 frequency | ≥ 30Hz (10초 평균) |
| Recovery latency | 시야 이탈 후 < 1초 복귀 |
| Jitter | 보고 (~1cm 예상) |
| 좌표계 | wrist xyz 부호/순서 sanity OK |

결과는 `docs/week2_report.md`에 기록.

---

## 트러블슈팅

### televuer가 SSL을 강제할 때

```bash
cd src/xr_teleop/xr_teleoperate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout key.pem -out cert.pem -subj "/CN=localhost"
```
인증서 경로는 televuer 코드 또는 환경변수가 가리키는 위치에 둡니다. Galaxy XR Chrome에서 첫 접속 시 "안전하지 않음" 경고를 수동 허용.

### `conda env create` 도중 `cannot uninstall casadi 3.6.7` (uninstall-no-record-file)

원인: conda-forge `pinocchio=3.1.0`이 `casadi`를 **conda 패키지**로 미리 설치하는데, 그 다음 pip 단계에서 같은 패키지를 다시 설치/uninstall하려다 RECORD 파일이 없어 실패.

해결: `casadi`/`matplotlib`/`opencv`는 pip 섹션이 아닌 **conda dependencies**에 두어야 함. 본 폴더의 `environment.yml`이 이미 그렇게 되어 있으니, 만약 옛 environment.yml로 만들었던 env가 있으면 한 번 지우고 다시 생성:

```bash
conda env remove -n tv
conda env create -f setup/environment.yml
```

부분 복구만 하고 싶으면:
```bash
conda activate tv
pip install --ignore-installed casadi   # 또는 conda install -c conda-forge casadi
```

### numpy가 2.x로 올라간 경우

```bash
pip install 'numpy<2' --force-reinstall --no-deps
python3 -c "import pinocchio"   # ImportError 안 나면 OK
```

### adb 디바이스가 unauthorized로 굳어버린 경우

```bash
adb kill-server && adb start-server
adb devices       # 다시 헤드셋 안의 RSA 지문 팝업 확인
```

### 매 작업 시작 절차 (요약)

```bash
adb devices                       # device 확인
adb reverse tcp:8012 tcp:8012     # televuer 포트
conda activate tv                 # (conda 환경)
cd src/xr_teleop/xr_teleoperate
python3 teleop/televuer/test/_test_televuer.py
# Galaxy XR Chrome → http://localhost:8012
```

---

## 관련 문서

- `../docs/CLAUDE.md` — 프로젝트 전체 컨텍스트 (한 페이지 요약)
- `../docs/xr_teleoperate_weekly_plan.md` — 12주 상세 계획
- `../docs/week1_report.md` — Week 1 (ADB/WebXR/Gate 1) 보고서
- `../docs/xr_teleoperate_tech_analysis.md` — 기술 스택 분석 + 한계
