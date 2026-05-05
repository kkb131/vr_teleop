#!/usr/bin/env bash
# xr_teleoperate ↔ unitree_sim_isaaclab DDS 통신용 환경 변수.
#
# Usage:
#   source setup/dds_env.sh    # 현재 셸에 적용 (한 번 source만 하면 됨)
#
# Sim host 측 sim_main.py가 ChannelFactoryInitialize(1)로 도메인 1을 강제하므로
# xr_teleoperate 측도 같은 도메인을 써야 멀티캐스트 discovery가 매치됨.
# 자세한 명세: docs/INTEGRATION_FOR_XR_TELEOPERATE.md §2.

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=1

# 다른 호스트로 sim을 옮기거나 bridge 네트워크에서 멀티캐스트가 막히는 경우엔
# unicast peers를 명시한 cyclonedds.xml을 추가로 export하면 됨:
#   export CYCLONEDDS_URI="file://$(pwd)/cyclonedds.xml"
# 같은 host + --network=host에서는 아래만으로 충분.

echo "[dds_env] RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
echo "[dds_env] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
