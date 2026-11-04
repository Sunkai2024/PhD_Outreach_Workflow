# -*- coding: utf-8 -*-
"""
统一配置加载器 + 工作目录自动切换 + CV 自动定位。

所有 step 脚本第一件事就是 `from load_config import ...`。这一行会:
1. 自动把 CWD 切到本脚本所在目录, 所以无论从哪里执行 step 脚本,
   相对路径 (WOS Excel / CV PDF / 中间产物) 都能正确读取/写入。
2. 加载环境变量或本地 config.json 中的 API key 和 QS 阈值。

config.json 字段:
- deepseek_api_key: DeepSeek API key, 所有脚本共用 (流水线串行运行, 不需要多 key)
- qs_threshold:    Step 2 / 3 用的最低 QS 排名标准

辅助函数:
- find_cv_pdf(): 自动定位本目录下的学生 CV PDF
"""
import os
import sys
import time
import json
from pathlib import Path

# 把 CWD 切到本脚本所在目录, 让所有 step 脚本里的相对路径都能 work
WORK_DIR = Path(__file__).resolve().parent
CONFIG_PATH = WORK_DIR / "config.json"


def load_settings(config_path=CONFIG_PATH, environ=None):
    """环境变量优先; 本地配置可选。错误信息不包含配置值。"""
    environ = os.environ if environ is None else environ
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ValueError("config.json 不是有效的 JSON。") from None
        if not isinstance(config, dict):
            raise ValueError("config.json 必须是 JSON 对象。")

    key = environ.get("DEEPSEEK_API_KEY", config.get("deepseek_api_key", ""))
    if not isinstance(key, str) or not key.strip():
        raise ValueError("请设置 DEEPSEEK_API_KEY 或本地 config.json 的 deepseek_api_key。")
    key = key.strip()
    if any(marker in key.lower() for marker in ("fill", "your", "replace", "example", "你的")):
        raise ValueError("请将 API key 占位符替换为有效密钥。")

    raw_threshold = environ.get("QS_THRESHOLD", config.get("qs_threshold", 350))
    if isinstance(raw_threshold, bool) or not str(raw_threshold).strip().isdigit():
        raise ValueError("qs_threshold / QS_THRESHOLD 必须是正整数。")
    threshold = int(raw_threshold)
    if threshold < 1:
        raise ValueError("qs_threshold / QS_THRESHOLD 必须是正整数。")
    return key, threshold


os.chdir(WORK_DIR)
DEEPSEEK_API_KEY, QS_THRESHOLD = load_settings()


def find_cv_pdf() -> str:
    """自动定位本目录下的学生 CV PDF。规则:
    1. 优先取文件名包含 'cv' (不区分大小写) 的 PDF
    2. 若不存在 'cv' 命名: 目录里唯一一个 PDF 也算 CV
    3. 找不到或不唯一时报错, 提示用户调整命名

    返回相对文件名 (CWD 已切到本目录, 直接可用)。
    """
    # 用大小写不敏感的扩展名匹配。Linux 文件系统区分大小写, glob("*.pdf")
    # 匹配不到 Resume.PDF / 张三CV.PDF 这类大写后缀 (Windows 上却能匹配)。
    pdfs = sorted(p.name for p in WORK_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        raise FileNotFoundError("找不到 CV PDF。请把学生 CV (PDF 格式) 放到本目录。")
    cv_named = [p for p in pdfs if "cv" in p.lower()]
    if len(cv_named) == 1:
        return cv_named[0]
    if len(cv_named) > 1:
        raise ValueError(
            f"目录里有多个名字带 'cv' 的 PDF: {cv_named}。"
            f"请只保留学生 CV 一份。"
        )
    if len(pdfs) == 1:
        return pdfs[0]
    raise ValueError(
        f"目录里有多个 PDF 但无一带 'cv': {pdfs}。"
        f"请把学生 CV 重命名为含 'CV' 字样, 或移走多余的 PDF。"
    )


# ─── DeepSeek API 调用: 带指数退避的重试封装 ──────────────────────────────────
# 临时错误(限流/超时/断连/5xx)退避后自动重试; 致命错误(Key失效/无权限/模型不存在)
# 立即终止整条流水线, 避免静默跑出一堆空结果。所有 step 共用这一个函数。
_RETRIABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}   # 临时错误: 退避后重试
_FATAL_STATUS     = {401, 403, 404}                        # 致命: 整条流水线没救, 直接退出


def call_with_retry(client, *, max_retries=5, base_delay=5.0, label="", **create_kwargs):
    """对 client.chat.completions.create(...) 做带指数退避的重试封装。

    用法: 把
        resp = client.chat.completions.create(model=..., messages=...)
    换成
        resp = call_with_retry(client, model=..., messages=...)
    其余参数原样传入即可 (model / messages / stream / temperature / extra_body ...)。

    行为:
    - 临时错误(限流 429 / 超时 / 断连 / 5xx): 退避后自动重试, 最多 max_retries 次。
      第 n 次重试前等待 base_delay * 2**n 秒 (默认 5,10,20,40,80s)。
    - 致命错误(鉴权 401 / 无权限 403 / 模型不存在 404): 立即打印原因并 sys.exit(1),
      让整条流水线停下来 —— 这类错误每条调用都会失败, 继续跑只会产出一堆空结果。
      (SystemExit 不会被各 step 的 except Exception 吞掉, 会一路退出, 触发 run_pipeline.sh 的 set -e)
    - 重试用尽仍是临时错误, 或遇到 400 之类不可重试错误: 抛出异常, 交给调用方的 except 处理(跳过该条)。
    """
    tag = f"[{label}] " if label else ""
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**create_kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            name = type(e).__name__

            # 致命错误: 立即终止整条流水线
            if status in _FATAL_STATUS:
                print(f"\n[!] {tag}API 致命错误 ({name}, status={status}): {e}")
                if status == 401:
                    print("    请检查环境变量或本地 config.json 中的 API key。")
                elif status == 404:
                    print("    多半是 model 名称不存在 (检查脚本里的 model=...)。")
                elif status == 403:
                    print("    API Key 无权限 / 账户欠费 / 被风控拒绝。")
                print("    流水线已停止, 修好后重跑 bash start.sh。")
                sys.exit(1)

            # 连接类错误没有 status_code, 按临时错误处理
            is_conn = status is None and any(
                k in name for k in ("Connection", "Timeout", "APIConnection", "APITimeout")
            )
            retriable = is_conn or (status in _RETRIABLE_STATUS)

            # 不可重试(如 400) 或 重试已用尽 → 抛出, 交给调用方 except
            if not retriable or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)
            print(f"  {tag}API 临时错误 ({name}, status={status}), "
                  f"{delay:.0f}s 后重试 ({attempt + 1}/{max_retries}) ...", flush=True)
            time.sleep(delay)
