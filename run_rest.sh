#!/bin/bash
# 自动断点续跑: 逐个检查每个 step 的产物是否完整, 从第一个"没跑完"的 step 接着跑到最后。
# 不传参数就是全自动; 也可以手动指定起点。
#
#   bash run_rest.sh          # 自动检测断在哪, 从那里续跑
#   bash run_rest.sh 5        # 手动从 step5 开始 (可用: 1  2  3  4  5  6  7)
#   screen -dmS pipe bash -c 'cd "$(pwd)" && bash run_rest.sh > rest_$(date +%Y%m%d_%H%M%S).log 2>&1'   # 后台跑
#
# 各 step 的"跑完"判定规则:
#   step1 / step2 / step3     产物 xlsx 存在即算跑完 (这三步只在结束时一次性写文件)
#   step4                     产物存在还不够——它边跑边存, 中断时文件也在但不全, 且没有断点续传。
#                             需要进度戳 (.pipeline_progress) 或历史日志里有 "DONE: step4" 记录,
#                             且时间不早于产物修改时间, 才算跑完; 证明不了就保守地重跑。
#                             (你若确认 step4 跑完过, 用 `bash run_rest.sh 5` 强制从 step5 开始)
#   step5                     checkpoint 每一行都填上 Research_Gap 才算跑完;
#                             没跑完直接重跑即可, 它自带续传, 已完成的行不会重复花钱
#   step6                     邮件 txt 数量 >= checkpoint 行数; 缺多少补多少, 已有的自动跳过
#   step7                     润色 txt 数量 >= 邮件 txt 数量; 已润色的自动跳过
#
# 本脚本每跑完一步会在 .pipeline_progress 记一笔, 供下次断点检测使用。

set -e
export PYTHONUNBUFFERED=1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── 激活 conda (逻辑同 run_pipeline.sh) ──────────────────────────────────────
CONDA_ENV=${CONDA_ENV:-agent}
if command -v conda >/dev/null 2>&1; then
    CONDA_SH="$(conda info --base)/etc/profile.d/conda.sh"
else
    for c in "$HOME/miniconda3" "$HOME/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
        [ -f "$c/etc/profile.d/conda.sh" ] && CONDA_SH="$c/etc/profile.d/conda.sh" && break
    done
fi
if [ -z "$CONDA_SH" ] || [ ! -f "$CONDA_SH" ]; then
    echo "[!] 找不到 conda.sh, 请设置环境变量 CONDA_SH 指向它"; exit 1
fi
source "$CONDA_SH"
conda activate "$CONDA_ENV" || { echo "[!] 激活 conda 环境 '$CONDA_ENV' 失败"; exit 1; }

PYTHON_BIN=${PYTHON_BIN:-python}

# ─── Python3 防呆 ─────────────────────────────────────────────────────────────
PY_MAJOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info[0])' 2>/dev/null)
if [ "$PY_MAJOR" != "3" ]; then
    echo "[!] 当前 python 不是 Python 3 (实测 $($PYTHON_BIN --version 2>&1))"; exit 1
fi

# ─── 全部 step 与断点检测 ─────────────────────────────────────────────────────
# 数组元素可以带命令行参数 (如 step7), 执行时不加引号让它按空格拆开
steps=(
    "step1_clean_wos.py"
    "step2_detect_university.py"
    "step3_filter_top_tiers.py"
    "step4_evaluate_phd_fit.py"
    "step5_generate_research_topics.py"
    "step6_generate_emails.py"
    "step7_polish_letters.py --input-dir Generated_Emails_PDF"
)

EMAILS_DIR="Generated_Emails_PDF"
POLISH_DIR="${EMAILS_DIR}_polished"
PROGRESS_FILE=".pipeline_progress"

count_txt() {    # count_txt <目录>  统计目录下 .txt 数量 (不递归, 排除 dry-run 的 prompt 预览)
    find "$1" -maxdepth 1 -name '*.txt' ! -name '_prompts_preview.txt' 2>/dev/null | wc -l
}

# step4 是否有"跑完过"的证据: 进度戳或历史日志里的 DONE 记录, 且时间不早于产物 mtime。
# (产物比记录还新 = 记录是上一轮的, 那之后 step4 又写过文件 → 证据作废)
step4_has_evidence() {
    local art="phd_fit_recommended.xlsx" art_mtime ts line t lg
    art_mtime=$(stat -c %Y "$art" 2>/dev/null) || return 1
    # 1) 本脚本自己记的进度戳 (行首是 epoch 秒)
    if [ -f "$PROGRESS_FILE" ]; then
        ts=$(grep "DONE step4_evaluate_phd_fit.py" "$PROGRESS_FILE" | tail -1 | cut -d' ' -f1)
        [ -n "$ts" ] && [ "$ts" -ge $((art_mtime - 5)) ] && return 0
    fi
    # 2) start.sh / run_pipeline.sh 落下的日志
    for lg in $(ls -t pipeline_*.log rest_*.log 2>/dev/null); do
        line=$(grep "DONE: step4_evaluate_phd_fit.py" "$lg" | tail -1)
        [ -z "$line" ] && continue
        t=$(echo "$line" | sed -E 's/^===== \[([0-9 :-]+)\].*$/\1/')
        t=$(date -d "$t" +%s 2>/dev/null) || continue
        [ "$t" -ge $((art_mtime - 5)) ] && return 0
    done
    return 1
}

# step_done <序号>: 返回 0 = 该步已跑完 (序号对应 steps 数组下标)
step_done() {
    case "$1" in
        0) [ -f verified_data_selected.xlsx ] ;;
        1) [ -f verified_data_with_qs.xlsx ] ;;
        2) [ -f selected.xlsx ] ;;
        3) [ -f phd_fit_recommended.xlsx ] && step4_has_evidence ;;
        4) $PYTHON_BIN -c "import sys, pandas as pd; c = pd.read_excel('step5_checkpoint.xlsx')['Research_Gap']; sys.exit(1 if bool(c.isna().any() or (c.astype(str).str.strip() == '').any()) else 0)" 2>/dev/null ;;
        5) local rows txts
           rows=$($PYTHON_BIN -c "import pandas as pd; print(len(pd.read_excel('step5_checkpoint.xlsx')))" 2>/dev/null) || return 1
           txts=$(count_txt "$EMAILS_DIR")
           [ -n "$rows" ] && [ "$txts" -ge "$rows" ] ;;
        6) local raw pol
           raw=$(count_txt "$EMAILS_DIR"); pol=$(count_txt "$POLISH_DIR")
           [ "$raw" -gt 0 ] && [ "$pol" -ge "$raw" ] ;;
    esac
}

# ─── 确定起点: 手动指定 or 自动检测 ───────────────────────────────────────────
START_IDX=-1
if [ -n "$1" ]; then
    case "$1" in
        1|step1)                  START_IDX=0 ;;
        2|step2)                  START_IDX=1 ;;
        3|step3)                  START_IDX=2 ;;
        4|step4)                  START_IDX=3 ;;
        5|step5)                  START_IDX=4 ;;
        6|step6)                  START_IDX=5 ;;
        7|step7)                  START_IDX=6 ;;
        *) echo "[!] 无法识别的起点 '$1' (可用: 1  2  3  4  5  6  7)"; exit 1 ;;
    esac
    echo "===== 手动指定起点: ${steps[$START_IDX]%% *} ====="
else
    echo "===== 断点检测 ====="
    for i in "${!steps[@]}"; do
        name=${steps[$i]%% *}
        if [ "$START_IDX" -ge 0 ]; then
            echo "  [ 待跑 ] $name"
        elif step_done "$i"; then
            echo "  [已完成] $name"
        else
            START_IDX=$i
            echo "  [没跑完] $name   <-- 从这里续跑"
            if [ "$i" -eq 3 ] && [ -f phd_fit_recommended.xlsx ]; then
                echo "           (phd_fit_recommended.xlsx 虽然存在, 但找不到它跑完过的日志/进度戳;"
                echo "            step4 中断时会留下不完整的文件, 所以保守重跑。"
                echo "            如果你确认它当时跑完了: bash run_rest.sh 5)"
            fi
        fi
    done
    if [ "$START_IDX" -lt 0 ]; then
        echo ""
        echo "===== 所有 step 的产物都齐了, 无需续跑 ====="
        echo "邮件输出 (原始): $(pwd)/$EMAILS_DIR/"
        echo "邮件输出 (润色): $(pwd)/$POLISH_DIR/"
        exit 0
    fi
fi

# 从 step4 或更早重跑时, 下游旧产物是隐患: step5 会从旧存档错位续传, step6 会拿旧文件名跳过
if [ "$START_IDX" -le 3 ] && [ -f step5_checkpoint.xlsx ]; then
    echo ""
    echo "[!] 注意: 将从 ${steps[$START_IDX]%% *} 重跑, 但下游旧产物 step5_checkpoint.xlsx 还在。"
    echo "    如果这次重跑会改变教授名单, step5 会从旧存档错位续传, 邮件也可能张冠李戴。"
    echo "    换了新一轮数据的话, 建议先清理: rm step5_checkpoint.xlsx && rm -rf $EMAILS_DIR $POLISH_DIR"
fi

# ─── 开始续跑 ─────────────────────────────────────────────────────────────────
echo ""
echo "===== 续跑开始 (从 ${steps[$START_IDX]%% *}) $(date '+%F %T') ====="
echo "Conda env: $CONDA_ENV  ($(which python))"
echo "Python:    $($PYTHON_BIN --version 2>&1)"

total=${#steps[@]}
for (( i=START_IDX; i<total; i++ )); do
    s=${steps[$i]}
    name=${s%% *}
    echo ""
    echo "===== [$(date '+%F %T')] Running $name ====="
    # 不加引号: 让带参数的条目按空格拆开 (脚本名和参数都不含空格, 安全)
    if ! $PYTHON_BIN $s; then
        echo "===== [$(date '+%F %T')] FAILED: $name ====="
        echo "===== 修好后直接重跑 bash run_rest.sh, 会自动从这里继续 ====="
        exit 1
    fi
    echo "$(date +%s) DONE $name" >> "$PROGRESS_FILE"
    echo "===== [$(date '+%F %T')] DONE: $name ====="
done

echo ""
echo "===== 全部完成 $(date '+%F %T') ====="
echo "邮件输出 (原始): $(pwd)/$EMAILS_DIR/"
echo "邮件输出 (润色): $(pwd)/$POLISH_DIR/"
