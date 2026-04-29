#!/usr/bin/env bash
# xr_teleoperate clone + 서브모듈 + editable install
# Usage:
#   conda env에서:  conda activate tv && bash setup/install.sh
#   Docker에서:     bash setup/install.sh   (system pip 사용)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "[install] working dir: $REPO_ROOT"
echo "[install] python: $(which python3)  $(python3 --version)"

# 0. 핵심 pip 의존성 (conda env에선 environment.yml이 처리하지만 system pip 호환을 위해 여기서도 보장)
echo "[install] ensuring core pip deps: casadi, meshcat, vuer[all], params-proto<3"
pip install 'vuer[all]==0.0.60' 'params-proto<3' casadi 'meshcat==0.3.2' \
            matplotlib==3.7.5 'rerun-sdk==0.20.1' sshkeyboard==2.3.1

# 1. xr_teleoperate clone (이미 있으면 skip)
if [ ! -d "xr_teleoperate" ]; then
  echo "[install] cloning xr_teleoperate..."
  git clone https://github.com/unitreerobotics/xr_teleoperate.git
else
  echo "[install] xr_teleoperate already exists — skipping clone"
fi

cd xr_teleoperate
echo "[install] initializing submodules..."
git submodule update --init --depth 1

# 2. 서브모듈 editable install
echo "[install] pip install -e teleop/televuer"
pip install -e teleop/televuer

# dex-retargeting은 Week 5에서 본격적으로 사용. 현재 Docker처럼 torch/pinocchio가
# 다른 버전으로 이미 깔린 환경에선 충돌(pin 2.7.0 vs system 3.9.0, torch 2.3 강제 다운)이
# 발생하므로 INSTALL_DEX_RETARGETING=1 인 경우에만 설치한다. 깨끗한 conda env(환경 tv)는
# 충돌이 없으므로 README Step E 이후 별도 안내로 설치.
if [ "${INSTALL_DEX_RETARGETING:-0}" = "1" ] && [ -d "teleop/robot_control/dex-retargeting" ]; then
  echo "[install] pip install -e teleop/robot_control/dex-retargeting (opt-in)"
  pip install -e teleop/robot_control/dex-retargeting
else
  echo "[install] dex-retargeting skip (INSTALL_DEX_RETARGETING=1 로 수동 설치, Week 5)"
fi

# 2b. teleimager (멀티카메라 스트리밍, Week 9에서 사용)
if [ -d "teleop/teleimager" ]; then
  echo "[install] pip install -e teleop/teleimager"
  pip install -e teleop/teleimager || \
    echo "[install] WARN: teleimager install failed — Week 9에서 다시 시도"
fi

# 3. unitree_sdk2_python (PyPI 우선, 실패 시 GitHub fallback)
if ! python3 -c "import unitree_sdk2py" >/dev/null 2>&1; then
  echo "[install] installing unitree_sdk2_python..."
  pip install unitree_sdk2_python || {
    TMP="$(mktemp -d)"
    git clone https://github.com/unitreerobotics/unitree_sdk2_python.git "$TMP"
    pip install -e "$TMP"
  }
else
  echo "[install] unitree_sdk2_python already importable — skipping"
fi

# 4. numpy 가드: pip 의존성이 numpy 2.x로 끌어올렸으면 강제 다운그레이드
NUMPY_MAJOR=$(python3 -c "import numpy; print(numpy.__version__.split('.')[0])")
if [ "$NUMPY_MAJOR" != "1" ]; then
  echo "[install] numpy $NUMPY_MAJOR.x detected — forcing <2 (pinocchio compatibility)"
  pip install 'numpy<2' --force-reinstall --no-deps
fi

echo ""
echo "[OK] install complete. Next:"
echo "     python3 setup/verify.py"
