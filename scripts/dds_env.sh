#!/usr/bin/env bash
# xr_teleoperate ↔ unitree_sim_isaaclab DDS 통신용 환경 변수.
#
# Usage:
#   source scripts/dds_env.sh    # 현재 셸에 적용 (한 번 source만 하면 됨)
#
# Sim host 측 sim_main.py가 ChannelFactoryInitialize(1)로 도메인 1을 강제하므로
# xr_teleoperate 측도 같은 도메인을 써야 멀티캐스트 discovery가 매치됨.
# 자세한 명세: docs/INTEGRATION_FOR_XR_TELEOPERATE.md §2.

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1

# 조종 PC ↔ 로봇 PC 분리 시 (WiFi/스위치 사이) 멀티캐스트 discovery 가
# 거의 항상 막혀서 토픽이 안 보임. 그 경우 XR_DDS_REMOTE=1 로 source 하면
# scripts/cyclonedds.xml (unicast peers) 를 CYCLONEDDS_URI 로 export.
#   XR_DDS_REMOTE=1 source scripts/dds_env.sh
# 같은 host + --network=host 에서는 XR_DDS_REMOTE 미설정 → 멀티캐스트 자동.
_dds_env_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${XR_DDS_REMOTE:-0}" = "1" ]; then
  _dds_xml="${_dds_env_dir}/cyclonedds.xml"
  if [ -f "${_dds_xml}" ]; then
    export CYCLONEDDS_URI="file://${_dds_xml}"
    echo "[dds_env] CYCLONEDDS_URI=${CYCLONEDDS_URI}"
    echo "[dds_env] remote 모드 — cyclonedds.xml 의 <Peers> IP 가 두 PC 와 일치해야 함"
  else
    echo "[dds_env] WARN: XR_DDS_REMOTE=1 인데 ${_dds_xml} 없음 → 멀티캐스트 fallback"
  fi
else
  unset CYCLONEDDS_URI
fi
unset _dds_env_dir _dds_xml

echo "[dds_env] RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
echo "[dds_env] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
