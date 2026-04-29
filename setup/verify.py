#!/usr/bin/env python3
"""xr_teleoperate 환경 sanity check.

설치 완료 후 실행:
    python3 setup/verify.py

- 필수 모듈 import 확인
- numpy <2 보장 (pinocchio ABI 호환성)
- adb reverse 상태 표시 (옵션)
"""

from __future__ import annotations

import importlib
import subprocess
import sys

REQUIRED = [
    "numpy",
    "pinocchio",
    "casadi",
    "meshcat",
    "vuer",
    "televuer",
    "unitree_sdk2py",
]
# dex-retargeting은 Week 5(DG-5F config)에서 사용. 깨끗한 conda env에선
# install.sh를 INSTALL_DEX_RETARGETING=1 로 다시 돌리면 OK.
OPTIONAL = ["dex_retargeting"]


def check_import(mod: str) -> bool:
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        print(f"[FAIL] {mod:<22} {type(e).__name__}: {e}")
        return False
    version = getattr(m, "__version__", "?")
    print(f"[OK]   {mod:<22} {version}")
    return True


def check_optional(mod: str) -> None:
    try:
        m = importlib.import_module(mod)
    except Exception:
        print(f"[skip] {mod:<22} (optional, Week 5)")
        return
    version = getattr(m, "__version__", "?")
    print(f"[OK]   {mod:<22} {version}")


def main() -> int:
    print(f"python: {sys.executable}  {sys.version.split()[0]}")
    print()

    results = [check_import(m) for m in REQUIRED]
    for m in OPTIONAL:
        check_optional(m)
    all_ok = all(results)

    import numpy

    numpy_major = int(numpy.__version__.split(".")[0])
    if numpy_major != 1:
        print(f"\n[FAIL] numpy must be <2 (got {numpy.__version__})")
        all_ok = False

    print("\n[adb reverse]")
    try:
        out = subprocess.check_output(
            ["adb", "reverse", "--list"], stderr=subprocess.STDOUT
        ).decode()
        print(out.strip() or "(empty — run: adb reverse tcp:8012 tcp:8012)")
    except FileNotFoundError:
        print("[WARN] adb not in PATH — Step A(README)에서 platform-tools 설치 필요")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] adb error: {e.output.decode().strip()}")

    print()
    if all_ok:
        print("[PASS] all checks ok")
        return 0
    print("[FAIL] one or more checks failed — see above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
