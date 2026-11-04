#!/bin/bash
# 后台启动整套流水线 (nohup + log), 断开 ssh 也不会中断。
#
# Usage:
#   bash start.sh
#
# 启动后:
#   - 实时看进度: tail -f pipeline_*.log  (具体文件名见启动时打印)
#   - 检查存活:   ps -p $(cat pipeline.pid) >/dev/null && echo running || echo stopped
#   - 停止任务:   kill $(cat pipeline.pid)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 拒绝重复启动: 仅当本目录确实有自己的流水线在运行时才拒绝。
# 通过 /proc/<pid>/cwd 看进程的实际工作目录, 区分"本目录的进程"vs"其他文件夹的进程"。
if [ -f pipeline.pid ]; then
    OLD_PID=$(cat pipeline.pid)
    if ps -p "$OLD_PID" >/dev/null 2>&1; then
        OLD_CWD=$(readlink "/proc/$OLD_PID/cwd" 2>/dev/null)
        if [ "$OLD_CWD" = "$SCRIPT_DIR" ]; then
            echo "[!] 本目录已有流水线在运行, PID=$OLD_PID"
            echo "    要先停: kill $OLD_PID"
            exit 1
        else
            echo "[i] pipeline.pid (PID=$OLD_PID) 指向其他目录的进程, 清理伪锁继续"
            rm -f pipeline.pid
        fi
    else
        echo "[i] pipeline.pid (PID=$OLD_PID) 已死, 清理后继续"
        rm -f pipeline.pid
    fi
fi

LOG_FILE="pipeline_$(date +%Y%m%d_%H%M%S).log"

nohup bash run_pipeline.sh > "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > pipeline.pid

# 等一秒, 确认进程没有立即崩掉
sleep 1
if ! ps -p "$PID" >/dev/null 2>&1; then
    echo "[!] 进程启动后立即退出, 请查看日志: $LOG_FILE"
    rm -f pipeline.pid
    exit 1
fi

echo "[OK] 流水线已在后台启动"
echo "     PID:  $PID  (已写入 pipeline.pid)"
echo "     日志: $LOG_FILE"
echo ""
echo "实时查看进度:"
echo "     tail -f $LOG_FILE"
echo ""
echo "停止任务:"
echo "     kill \$(cat pipeline.pid)"
