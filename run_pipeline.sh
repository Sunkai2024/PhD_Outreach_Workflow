#!/bin/bash
# 顺序执行 7 个 step 脚本, 任一失败立即停止。
#
# 直接调用 (前台运行, 调试用):
#   bash run_pipeline.sh
#
# 推荐用 start.sh 后台启动 + 落日志:
#   bash start.sh

set -e                       # 任一命令失败立即退出
export PYTHONUNBUFFERED=1    # print 实时刷到 log, 不被 Python 缓冲拦住
export PYTHONUTF8=1          # 强制 Python 用 UTF-8 I/O, 防 C/POSIX locale 下 print 中文/emoji 崩 (UnicodeEncodeError)
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── 激活 conda 环境 ──────────────────────────────────────────────────────────
# 默认环境名 'agent', 可通过 CONDA_ENV 环境变量覆盖
CONDA_ENV=${CONDA_ENV:-agent}

# 找 conda.sh: 优先用 PATH 里的 conda, 否则尝试常见安装位置
# (nohup 启动时 PATH 可能没继承 conda, 所以需要 fallback)
if command -v conda >/dev/null 2>&1; then
    CONDA_SH="$(conda info --base)/etc/profile.d/conda.sh"
else
    for candidate in "$HOME/miniconda3" "$HOME/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
        if [ -f "$candidate/etc/profile.d/conda.sh" ]; then
            CONDA_SH="$candidate/etc/profile.d/conda.sh"
            break
        fi
    done
fi

if [ -z "$CONDA_SH" ] || [ ! -f "$CONDA_SH" ]; then
    echo "[!] 找不到 conda。请确认 conda 已安装, 或设置环境变量 CONDA_SH 指向 conda.sh"
    exit 1
fi

# shellcheck source=/dev/null
source "$CONDA_SH"
conda activate "$CONDA_ENV" || {
    echo "[!] 激活 conda 环境 '$CONDA_ENV' 失败"
    echo "    创建命令: conda create -n $CONDA_ENV python=3.12 -y"
    echo "    装依赖:   conda activate $CONDA_ENV && pip install pandas numpy openai tqdm pdfplumber pypdf openpyxl 'xlrd>=2.0.1'"
    exit 1
}

PYTHON_BIN=${PYTHON_BIN:-python}    # 激活后默认用环境里的 python

# ─── 防呆: 确认 python 真的是 Python 3 ────────────────────────────────────────
# 经典坑: conda 环境没装 python (或没装成功), python 退回系统 /usr/bin/python (2.7),
# 整套 Python 3 代码 (f-string 等) 会在第一个 step 满屏 SyntaxError。这里先拦下。
PY_MAJOR=$($PYTHON_BIN -c 'import sys; print(sys.version_info[0])' 2>/dev/null)
if [ "$PY_MAJOR" != "3" ]; then
    echo "[!] 当前 '$PYTHON_BIN' 不是 Python 3"
    echo "    实测版本: $($PYTHON_BIN --version 2>&1)"
    echo "    实测路径: $(command -v $PYTHON_BIN 2>/dev/null)"
    echo ""
    echo "    本套脚本是 Python 3 代码, 用 Python 2 跑必然 SyntaxError。修复:"
    echo "      conda create -n $CONDA_ENV python=3.12 -y && conda activate $CONDA_ENV"
    echo "      pip install pandas numpy openai tqdm pdfplumber pypdf openpyxl 'xlrd>=2.0.1'"
    echo "    或临时指定: PYTHON_BIN=python3 bash start.sh"
    exit 1
fi

# 数组元素可以带命令行参数 (如 step7 指定输入文件夹), 所以下面执行时不加引号
steps=(
    "step1_clean_wos.py"
    "step2_detect_university.py"
    "step3_filter_top_tiers.py"
    "step4_evaluate_phd_fit.py"
    "step5_generate_research_topics.py"
    "step6_generate_emails.py"
    "step7_polish_letters.py --input-dir Generated_Emails_PDF"
)

echo "===== Pipeline started at $(date '+%Y-%m-%d %H:%M:%S') ====="
echo "Working dir: $(pwd)"
echo "Conda env:   $CONDA_ENV  ($(which python))"
echo "Python:      $($PYTHON_BIN --version 2>&1)"
echo ""

for script in "${steps[@]}"; do
    echo ""
    echo "===== [$(date '+%Y-%m-%d %H:%M:%S')] Running $script ====="
    # 不加引号: 让带参数的条目按空格拆开 (脚本名和参数都不含空格, 安全)
    if ! $PYTHON_BIN $script; then
        echo ""
        echo "===== [$(date '+%Y-%m-%d %H:%M:%S')] FAILED: $script ====="
        echo "===== Pipeline aborted. Fix the error above and restart. ====="
        exit 1
    fi
    echo "===== [$(date '+%Y-%m-%d %H:%M:%S')] DONE: $script ====="
done

echo ""
echo "===== Pipeline finished at $(date '+%Y-%m-%d %H:%M:%S') ====="
echo "Output emails (raw):      $(pwd)/Generated_Emails_PDF/"
echo "Output emails (polished): $(pwd)/Generated_Emails_PDF_polished/"
