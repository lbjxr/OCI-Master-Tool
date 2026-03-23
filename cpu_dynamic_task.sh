#!/bin/bash

# ========================================================
# 功能：模拟 15%-30% CPU 占用，随机运行 1-2h，随机间隔 2-3h
# 特点：启动即运行，无缝循环，防误杀设计
# ========================================================

# --- 核心负载生成器 ---
# 使用这种方式可以避开对 bc 命令的依赖，增强通用性
generate_load() {
    local target=$1
    # 标记字符串，用于精准停止
    local MARKER="WORKER_ID_$(date +%s%N)"
    
    # 这里的逻辑：在 100ms 的周期内，计算 $target 毫秒，休息剩余毫秒
    echo "while true; do 
            start=\$(date +%s%N); 
            while [ \$((\$(date +%s%N) - \$start)) -lt $((target * 1000000)) ]; do :; done; 
            sleep 0.$((100 - target)) 2>/dev/null || sleep 0.05; 
          done" | /bin/bash &
}

# --- 停止所有相关占用进程 ---
release() {
    # 这里的 grep 逻辑非常精准，只杀掉循环体，不杀掉 auto 控制主进程
    ps -ef | grep "while \[ \$((\$(date +%s%N)" | grep -v grep | awk '{print $2}' | xargs -r kill -9
}

# --- 自动化主逻辑 ---
start_auto_mode() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 自动化模式已启动。"
    
    while true; do
        # 1. 随机确定本次占用比例 (15-30%)
        local current_target=$(( (RANDOM % 16) + 15 ))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 正在启动占用: ${current_target}%"
        
        # 2. 立即开始执行
        generate_load $current_target
        
        # 3. 随机运行时长 1-2 小时 (3600-7200秒)
        local run_time=$(( (RANDOM % 3601) + 3600 ))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 本次将运行 $((run_time / 60)) 分钟..."
        sleep $run_time
        
        # 4. 停止占用
        release
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 任务已暂停，释放资源。"
        
        # 5. 随机等待时长 2-3 小时 (7200-10800秒)
        local wait_time=$(( (RANDOM % 3601) + 7200 ))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 进入静默期，等待 $((wait_time / 60)) 分钟后再次启动..."
        sleep $wait_time
    done
}

# --- 脚本入口 ---
case "$1" in
    auto)
        start_auto_mode
        ;;
    release)
        release
        echo "已手动清理所有占用进程。"
        ;;
    *)
        echo "用法: $0 {auto|release}"
        echo "提示: 建议使用 nohup bash $0 auto > /dev/null 2>&1 & 后台运行"
        ;;
esac