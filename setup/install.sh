#!/usr/bin/env bash
# xr_teleoperate clone + 서브모듈 + editable install
#
# 공식 가이드(https://github.com/unitreerobotics/xr_teleoperate#11--basic)와 절차 동일하되,
# 우리 환경에서 발견한 호환성 함정 세 가지를 추가로 처리한다:
#  - vuer 0.0.60는 params-proto>=3에서 ImportError 발생 → params-proto<3 핀
#  - dex-retargeting은 pin==2.7 / torch==2.3 강제로 시스템 stack을 다운그레이드하므로
#    INSTALL_DEX_RETARGETING=1 일 때만 설치 (Week 5)
#  - ROS Humble system pinocchio는 casadi backend 없음 → conda env tv 안에서 실행 권장
#    (teleop_hand_and_arm.py가 'from pinocchio import casadi' 강제)
#
# Usage:
#   conda env에서:  conda activate tv && bash setup/install.sh    ← Week 3+ 권장
#   Docker에서:     bash setup/install.sh                          (system pip — Week 2까지만)
#   Week 5 진입:    INSTALL_DEX_RETARGETING=1 bash setup/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "[install] working dir: $REPO_ROOT"
echo "[install] python: $(which python3)  $(python3 --version)"

# pip 자체가 conda env에 없을 수 있음 (pip 패키지 미명시). 모든 pip 호출을
# 'python3 -m pip'로 강제해서 어떤 PATH 환경에서도 올바른 python의 pip를 쓰게 한다.
# (Week 3 시행착오: conda activate tv 후에도 'which pip' → /usr/bin/pip 였음)
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "[install] WARN: python3 -m pip 동작 안 함 — 'conda install -n tv pip -c conda-forge -y' 필요"
  exit 1
fi

# ── 1. xr_teleoperate clone ──
if [ ! -d "xr_teleoperate" ]; then
  echo "[install] cloning xr_teleoperate..."
  git clone https://github.com/unitreerobotics/xr_teleoperate.git
else
  echo "[install] xr_teleoperate already exists — skipping clone"
fi

cd xr_teleoperate
echo "[install] initializing submodules (shallow)..."
git submodule update --init --depth 1

# ── 1b. requirements.txt (matplotlib / rerun-sdk / meshcat / sshkeyboard) ──
echo "[install] installing requirements.txt"
python3 -m pip install -r requirements.txt

# ── 1c. vuer[all] — televuer가 transitive로 끌고 오긴 하나 [all] extras 명시 필요 ──
echo "[install] installing vuer[all]==0.0.60"
python3 -m pip install 'vuer[all]==0.0.60'

# ── 2. teleimager (--no-deps, 공식 권장 — Week 9에서 본격 사용) ──
if [ -d "teleop/teleimager" ]; then
  echo "[install] pip install -e teleop/teleimager --no-deps"
  python3 -m pip install -e teleop/teleimager --no-deps
fi

# ── 3. televuer (vuer/aiohttp/등 transitive deps 함께 설치) ──
echo "[install] pip install -e teleop/televuer"
python3 -m pip install -e teleop/televuer

# ── 4. 호환성 핀: vuer 0.0.60 + params-proto<3 ──
# televuer가 끌고 들어오는 params-proto가 3.x로 깔리면 vuer.server import 실패. 강제로 2.x로.
echo "[install] pinning params-proto<3 for vuer 0.0.60 compatibility"
python3 -m pip install 'params-proto<3'

# ── 5. dex-retargeting (opt-in, Week 5) ──
if [ "${INSTALL_DEX_RETARGETING:-0}" = "1" ] && [ -d "teleop/robot_control/dex-retargeting" ]; then
  echo "[install] pip install -e teleop/robot_control/dex-retargeting"
  python3 -m pip install -e teleop/robot_control/dex-retargeting
else
  echo "[install] dex-retargeting skip (Week 5에서 INSTALL_DEX_RETARGETING=1 로 재실행)"
fi

# ── 6. unitree_sdk2_python (PyPI에 없으면 GitHub fallback) ──
if ! python3 -c "import unitree_sdk2py" >/dev/null 2>&1; then
  echo "[install] installing unitree_sdk2_python..."
  python3 -m pip install unitree_sdk2_python || {
    TMP="$(mktemp -d)"
    git clone https://github.com/unitreerobotics/unitree_sdk2_python.git "$TMP"
    python3 -m pip install -e "$TMP"
  }
else
  echo "[install] unitree_sdk2_python already importable — skipping"
fi

# ── 7. numpy 가드 ──
# pip 의존성이 numpy 2.x로 끌어올렸으면 강제 다운그레이드 (pinocchio ABI 호환)
NUMPY_MAJOR=$(python3 -c "import numpy; print(numpy.__version__.split('.')[0])")
if [ "$NUMPY_MAJOR" != "1" ]; then
  echo "[install] numpy $NUMPY_MAJOR.x detected — forcing <2"
  python3 -m pip install 'numpy<2' --force-reinstall --no-deps
fi

# ── 8. SSL 인증서 ── (Galaxy XR Chrome → televuer 서버 HTTPS/WSS 연결용)
# televuer/vuer는 cert/key 없이 부팅 안 됨. idempotent하므로 매번 호출해도 안전.
if [ -x "$SCRIPT_DIR/gen_certs.sh" ]; then
  echo "[install] running gen_certs.sh..."
  bash "$SCRIPT_DIR/gen_certs.sh" || \
    echo "[install] WARN: gen_certs.sh failed — bash setup/gen_certs.sh 수동 실행 필요"
fi

echo ""
echo "[OK] install complete. Next:"
echo "     python3 setup/verify.py"
echo "     python3 setup/test_pose_only.py --http   # Galaxy XR 연결 후 (HTTP 권장)"
echo "     bash setup/diagnose.sh                   # connectivity 점검 (서버 실행 중일 때)"
