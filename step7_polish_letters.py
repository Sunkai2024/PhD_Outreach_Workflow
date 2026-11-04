# -*- coding: utf-8 -*-
"""
批量润色申博套磁信 —— 只做"语言润色 + 结构调整 + 去同质化 + 去 AI 味"，不改关键事实。

定位（重要）：
  这是一个"润色器"，不是"重写器"。你的现有流程照常批量产信；本脚本只对产出的信做
  编辑级润色。关键内容——奖学金来源/金额/期限/状态、个人课题与方法、对导师工作的引用、
  姓名邮箱数字——一律原样保留，模型不许增删改、不许发挥、不许新增诉求或吹捧。

去同质化怎么做：
  - 5 个"编辑档位"prompt 硬编码在 STYLE_PROMPTS 里（只调结构/语气/句式，不动事实）。
  - 第 1 封用 #1，第 2 封用 #2 …… 第 6 封回到 #1，一轮一轮循环（index % 5）。
  - 每个 prompt = 共同硬约束(SHARED_RULES，含"严格保真"+禁用 AI 套话) + 一个独特档位。
  同一批信因此在结构、语气、句式上彼此不同，但事实全部忠于各自草稿。

────────────────────────────────────────────────────────────
用法：
  1. 装依赖：       pip install openai
  2. 配置 API key： export DEEPSEEK_API_KEY="your-api-key"
  3. 先空跑验证：   python step7_polish_letters.py --dry-run
     （不调用 API、不花钱，只打印每封信分到哪个 prompt，并把 5 个完整 prompt
       导出到【输出文件夹内】的 _prompts_preview.txt 供你审阅/修改）
  4. 小样测试：     python step7_polish_letters.py --limit 3
  5. 全量润色：     python step7_polish_letters.py
  所有输出都保存在【同一个新文件夹】里（默认：原文件夹旁边的 <原名>_polished，与原信
  分开）：润色后的信文件名与原信一致；--dry-run 的 prompt 预览也放在这个文件夹内。
  已存在的信会跳过（除非加 --overwrite）。

读取路径（重要）：
  所有套磁信放在【同一个文件夹】里。脚本默认读“与本脚本同级的 Generated_Emails_PDF 文件夹”下的
  所有 .txt。换成你自己的文件夹，两种方式任选：
    · 改脚本顶部的 INPUT_DIR_NAME；或
    · 运行时加参数： python step7_polish_letters.py --input-dir "/path/to/letters"
  路径含中文/空格都没关系，但带空格时整个路径要用引号括起来。

可用环境变量覆盖：
  DEEPSEEK_API_KEY          （也可从本地 config.json 读取）
  DEEPSEEK_MODEL            默认 deepseek-v4-pro
  DEEPSEEK_BASE_URL         默认 https://api.deepseek.com
  DEEPSEEK_REASONING_EFFORT 默认 high（可 low / medium / high；调低更快更省）

API 调用方式：按 DeepSeek V4 Pro 开启思考模式
  reasoning_effort=high + extra_body={"thinking": {"type": "enabled"}}，stream=False，
  不传 temperature / max_tokens；只取最终回答 message.content（不含思维链）。
  去同质化靠 5 个 prompt 轮换，不再依赖 temperature。
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

# ────────────────────────── 基本配置 ──────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent

# ── DeepSeek API 配置 ──
# API key 在 build_client 中从统一配置加载, 使 --dry-run 无需凭据。
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")  # DeepSeek V4 Pro
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")  # 推理强度：low / medium / high
ENABLE_THINKING = True                                 # 开启 V4 Pro 思考模式
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "1.0"))  # 每封之间稍歇，避免限流
MAX_RETRIES = 3

# ── 读取路径配置 ──
# 所有套磁信统一放在【同一个文件夹】里。默认读“与本脚本同级”的这个子文件夹；
# 想读别的文件夹：改 INPUT_DIR_NAME，或运行时加 --input-dir "路径"。
INPUT_DIR_NAME = "Generated_Emails_PDF"
DEFAULT_INPUT = SCRIPT_DIR / INPUT_DIR_NAME
# 读取该文件夹内匹配此通配的文件（不递归子文件夹）。默认读所有 .txt。
FILE_GLOB = "*.txt"

# 输出文件夹：所有润色结果统一存到【一个新文件夹】里（建在原文件夹旁边，与原信分开）。
# 留空 = 自动用 “<原文件夹名>_polished”；想固定一个新文件夹名就填这里，如 "润色结果"。
OUTPUT_DIR_NAME = ""

# ──────────── 所有 prompt 共享的硬约束（保真 + 去 AI 味 + 输出格式）────────────
# 注意：这里【不】告诉模型"事实是什么"——那会诱导它按注入内容改写关键信息。
# 模型只能从每封草稿自身取事实，因此不会篡改奖学金来源、课题介绍等关键内容。
SHARED_RULES = """You are a meticulous copy-editor for PhD cold-emails ("套磁信") sent to principal
investigators (PIs) in biomedical research. You will receive ONE draft email produced by an automated
pipeline. Your job is to POLISH THE LANGUAGE and ADJUST THE STRUCTURE so it reads like a real, specific
human wrote it, and so that a batch of such emails does not look mass-produced. You are an EDITOR, not a
co-author.

WHAT YOU MUST NOT CHANGE — this is the most important rule; do NOT "improve" the facts:
Preserve every factual claim in the draft, unchanged in meaning. Never add, drop, alter, soften or embellish
any of:
  - the scholarship / funding: its SOURCE or funder, amount, duration, and status (e.g. whether it is
    already secured versus still being applied for) — reproduce exactly what the draft states;
  - the applicant's own research: topics, techniques, models, datasets, and any results or numbers;
  - the references to THIS professor's own research and lab;
  - all names, email addresses, institutions, dates and figures.
Do NOT invent new facts, new claims, new praise, or a new "ask"/request that is not already in the draft.
If the draft does not say something, you may not add it. If you are unsure whether a phrase is factual, keep
it. Your output must contain exactly the same facts as the input — no more, no less.

WHAT YOU SHOULD DO — language and structure only:
- Rewrite the wording so it is natural, concise and human; cut filler, hedging and empty flattery.
- Reorganise sentences and paragraphs for logical flow and readability; you may reorder existing points and
  merge redundant sentences, as long as no fact is added or lost.
- Kill the "AI smell". Do NOT use these phrases or close variants: "I hope this message/email finds you
  well", "I am writing to express my (strong) interest", "With a solid background in", "I am confident that
  my skills can contribute", "contribute meaningfully", "aligns (closely/well) with", "esteemed", "impactful
  work", "groundbreaking", "I would be grateful for the opportunity", "Thank you for considering my
  application", "I look forward to the possibility of contributing", "at your convenience".
- Vary sentence length and openings so the letter has a human rhythm, not a template cadence.
- If trimming would force you to drop a real fact, keep the fact and cut filler elsewhere instead.

OUTPUT FORMAT:
- Do NOT output a "To:" line (it is re-attached automatically).
- First line must be `Subject: <a specific subject that reflects the letter's real content>`; you may improve
  its wording but it must not claim anything not in the letter. Then a blank line, then `Dear Professor
  <Name>,` and the body, ending with a sign-off line and the applicant's name exactly as written in the draft.
- Output the email ONLY — no markdown, no code fences, no preamble, no commentary."""

# ──────────────── 5 个"编辑档位"（只调结构/语气/句式，不动事实）────────────────
# 轮换使用：第 i 封 -> STYLE_PROMPTS[i % 5]
STYLE_PROMPTS = [
    # 档位 1：精简压缩型
    """EDITING PROFILE — LEAN & COMPRESSED:
Edit for maximum concision. Aim for about three tight paragraphs, and the shortest length that still keeps
every fact from the draft. Cut all filler; turn long, winding AI sentences into short declaratives. Move the
single most concrete point (and the request, if the draft has one) toward the top. Keep no adjective that
carries no information.""",

    # 档位 2：内容前置型（把最具体的细节提到最前）
    """EDITING PROFILE — SUBSTANCE-FORWARD:
Reorganise so the most specific, concrete detail ALREADY in the draft (a method, a result, or the professor's
particular research problem) leads the email instead of a generic opener. Merge vague or redundant sentences
into fewer, denser ones. Keep every technical specific; remove only the padding around them.""",

    # 档位 3：自然真人型
    """EDITING PROFILE — WARM & HUMAN:
Re-voice the draft in a natural, first-person human register: varied sentence lengths, ordinary connectives,
no stiff formality, no buzzwords. Same facts, same points — just make it sound like a person wrote it, not a
template. Avoid two consecutive sentences with the same shape or the same opening word.""",

    # 档位 4：清晰逻辑结构型
    """EDITING PROFILE — CLEAN LOGICAL STRUCTURE:
Restructure into a clear, scannable flow where each paragraph does exactly one job (for example: who he is +
why this lab -> relevant background / fit -> funding -> the request). Tighten the transitions between them.
Reorder existing content only; add nothing and drop no fact.""",

    # 档位 5：克制正式学术型
    """EDITING PROFILE — RESTRAINED FORMAL:
Edit to a precise, economical, European-academic register with every cliche removed. Measured and courteous
without servility; no exclamation marks, no hype. Preserve all content exactly; elevate only the phrasing and
the paragraphing.""",
]

# 最终 5 个完整 prompt = 共同硬约束 + 各自档位
PROMPTS = [SHARED_RULES.strip() + "\n\n" + s.strip() for s in STYLE_PROMPTS]


# ────────────────────────── 工具函数 ──────────────────────────
def extract_to_line(text: str):
    """原样取出 'To: xxx' 那一行，收件邮箱绝不能被模型改动。"""
    for line in text.splitlines():
        if line.strip().lower().startswith("to:"):
            return line.strip()
    return None


def clean_output(text: str) -> str:
    """清掉模型可能多加的代码围栏 / 前言，确保从 'Subject:' 开始。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    idx = t.lower().find("subject:")
    if idx > 0:
        t = t[idx:].strip()
    return t


def build_client():
    """惰性导入 openai，这样 --dry-run 不装 openai 也能跑。"""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("缺少依赖：请先执行  pip install openai")
    from load_config import DEEPSEEK_API_KEY
    key = DEEPSEEK_API_KEY
    return OpenAI(api_key=key, base_url=BASE_URL)


def polish_one(client, system_prompt: str, letter_text: str) -> str:
    """调用一次 DeepSeek，带简单重试。"""
    user_msg = ("Here is the draft email. Polish its language and adjust its structure only — "
                "do NOT change any facts, and do not add or remove any factual content:\n\n" + letter_text)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                stream=False,
                reasoning_effort=REASONING_EFFORT,
                extra_body={"thinking": {"type": "enabled"}} if ENABLE_THINKING else None,
            )
            # 只取最终回答（message.content），不含思维链 reasoning_content
            return clean_output(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001  网络/限流等，重试
            last_err = e
            wait = 2 ** attempt
            print(f"    [warn] API 出错 (第 {attempt}/{MAX_RETRIES} 次)：{e}；{wait}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"重试 {MAX_RETRIES} 次仍失败：{last_err}")


# ────────────────────────── 主流程 ──────────────────────────
def main():
    try:  # 让中文进度/报错在 Windows 控制台也不乱码
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="用 DeepSeek 批量润色套磁信（5 编辑档位轮换，保真）")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT,
                        help=f"套磁信所在文件夹（默认：与脚本同级的 {INPUT_DIR_NAME}）")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="输出文件夹（默认：原文件夹旁边的 <原名>_polished）")
    parser.add_argument("--pattern", default=FILE_GLOB,
                        help=f"读取哪些文件（默认 {FILE_GLOB}，仅当前文件夹、不递归）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 封（0=全部），用于小样测试")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出（默认跳过）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调用 API：只打印轮换分配，并把 5 个完整 prompt 导出到 _prompts_preview.txt")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        sys.exit(f"读取路径不存在或不是文件夹：\n  {input_dir}\n"
                 f"请用 --input-dir 指定套磁信所在的文件夹。")
    # 输出统一放到【一个新文件夹】里（与原文件夹分开，绝不写回原目录）
    if args.output_dir:
        output_dir = args.output_dir.resolve()
    elif OUTPUT_DIR_NAME:
        output_dir = input_dir.parent / OUTPUT_DIR_NAME
    else:
        output_dir = input_dir.parent / (input_dir.name + "_polished")
    if output_dir == input_dir:
        sys.exit("输出文件夹不能和原文件夹相同（会覆盖原信）。请用 --output-dir 换一个新文件夹。")

    # 收集文件：仅当前文件夹内匹配 pattern；排除下划线开头的辅助文件、以及输出目录里的文件
    letters = sorted(
        p for p in input_dir.glob(args.pattern)
        if p.is_file() and not p.name.startswith("_") and output_dir not in p.parents
    )
    if not letters:
        sys.exit(f"在这个文件夹里没找到匹配 {args.pattern} 的文件：\n  {input_dir}")
    if args.limit > 0:
        letters = letters[:args.limit]

    print(f"读取文件夹：{input_dir}")
    print(f"输出文件夹：{output_dir}")
    print(f"匹配到 {len(letters)} 个文件（pattern = {args.pattern}）")
    print(f"用 {len(PROMPTS)} 个 prompt 轮换（第 1 封->#1, 第 2 封->#2 …… 第 6 封->#1，循环）")
    print(f"模型 = {MODEL} | reasoning_effort = {REASONING_EFFORT} | thinking = {'on' if ENABLE_THINKING else 'off'}\n")

    # dry-run：导出 prompt 预览 + 打印分配，然后退出
    if args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        preview_path = output_dir / "_prompts_preview.txt"
        with open(preview_path, "w", encoding="utf-8") as f:
            for i, p in enumerate(PROMPTS, 1):
                f.write(f"{'='*70}\nPROMPT #{i}\n{'='*70}\n{p}\n\n\n")
        for i, path in enumerate(letters):
            print(f"  [{i+1:>2}] {path.name:<45} -> prompt #{(i % len(PROMPTS)) + 1}")
        print(f"\n[dry-run] 未调用 API。5 个完整 prompt 已导出到新文件夹内：\n  {preview_path}")
        print("确认没问题后，去掉 --dry-run 即可真正润色（先用 --limit 3 小样试跑）。")
        return

    client = build_client()
    output_dir.mkdir(parents=True, exist_ok=True)

    done = skipped = failed = 0
    for i, path in enumerate(letters):
        prompt_idx = i % len(PROMPTS)
        out_path = output_dir / path.name
        tag = f"[{i+1}/{len(letters)}] {path.name} (prompt #{prompt_idx + 1})"

        if out_path.exists() and not args.overwrite:
            print(f"  跳过（已存在）：{tag}")
            skipped += 1
            continue

        original = path.read_text(encoding="utf-8")
        to_line = extract_to_line(original)

        print(f"  润色中：{tag}")
        try:
            body = polish_one(client, PROMPTS[prompt_idx], original)
        except Exception as e:  # noqa: BLE001
            print(f"    [error] 失败，跳过：{e}")
            failed += 1
            continue

        final = f"{to_line}\n\n{body}\n" if to_line else body + "\n"
        out_path.write_text(final, encoding="utf-8")
        done += 1
        time.sleep(SLEEP_BETWEEN)

    print(f"\n完成：成功 {done}，跳过 {skipped}，失败 {failed}。输出目录：{output_dir}")


if __name__ == "__main__":
    main()
