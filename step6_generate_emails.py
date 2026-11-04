# -*- coding: utf-8 -*-
"""
Step 6: 智能套磁信生成 (DeepSeek + PDF 简历自动读取版, Python 实现)
"""

import os
import re
import time
import pandas as pd
from openai import OpenAI
from pypdf import PdfReader

from load_config import DEEPSEEK_API_KEY, find_cv_pdf, call_with_retry

# ================= 配置区域 =================
MODEL_NAME = "deepseek-v4-pro"
BASE_URL = "https://api.deepseek.com"

EXCEL_FILE  = "step5_checkpoint.xlsx"       # 输入 Excel (Step 5 输出的 checkpoint)
PROMPT_FILE = "套磁信prompt.txt"             # Prompt 指令文件
CV_PDF_FILE = find_cv_pdf()                 # 自动定位本目录下的 CV PDF
OUTPUT_DIR  = "Generated_Emails_PDF"        # 输出文件夹

SLEEP_SECONDS = 0.0  # 如需限速,可设为 1.0

# ================= 工具函数 =================

def extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def safe_filename(name: str) -> str:
    # 保留中英文/数字, 其余替换为下划线 (对应 R 中 [^a-zA-Z0-9一-龥])
    return re.sub(r"[^a-zA-Z0-9一-龥]", "_", str(name))


def na_or(value, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    s = str(value).strip()
    return s if s else default


# ================= API 调用 =================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=BASE_URL,
    timeout=60,        # 单次调用最多等 60s
    max_retries=0,     # 重试统一交给 call_with_retry, 关掉 SDK 自带重试避免叠加
)


def build_user_message(tutor_name, article_title, abstract, novel_direction,
                       cv_text, prompt_template) -> str:
    return (
        f"{prompt_template}\n\n"
        "**************************************************\n"
        "PART 1: MY RESUME / CV CONTENT (From PDF)\n"
        "**************************************************\n"
        f"{cv_text}\n\n"
        "**************************************************\n"
        "PART 2: TARGET TUTOR INFORMATION\n"
        "**************************************************\n"
        f"Tutor Name: {tutor_name}\n"
        f"Paper Title: {article_title}\n"
        f"Abstract: {abstract}\n"
        f"Novel_Direction (Future Research): {novel_direction}\n\n"
        "[System Instruction]: Based on the PROMPT, MY RESUME, and TUTOR INFO above, "
        "write the email now. Start with 'Subject:'."
    )


def generate_email(tutor_name, article_title, abstract, novel_direction,
                   cv_text, prompt_template):
    user_msg = build_user_message(
        tutor_name, article_title, abstract, novel_direction, cv_text, prompt_template
    )
    try:
        response = call_with_retry(
            client,
            label="step6",
            model=MODEL_NAME,
            messages=[
                {"role": "system",
                 "content": "You are a professional academic assistant helping a PhD applicant write customized emails."},
                {"role": "user", "content": user_msg},
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  [API Error] {e}")
        return None


# ================= 主流程 =================

def main():
    print("正在初始化...")

    if not os.path.exists(EXCEL_FILE):
        raise FileNotFoundError(f"找不到 Excel 文件: {EXCEL_FILE}")
    if not os.path.exists(PROMPT_FILE):
        raise FileNotFoundError(f"找不到 Prompt 模板文件: {PROMPT_FILE}")
    if not os.path.exists(CV_PDF_FILE):
        raise FileNotFoundError(f"找不到 PDF 简历文件: {CV_PDF_FILE}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = pd.read_excel(EXCEL_FILE)

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_base = f.read()

    print("正在解析 PDF 简历...")
    cv_content = extract_pdf_text(CV_PDF_FILE)
    if len(cv_content) < 50:
        print("警告: PDF 读取到的文字很少,请确认这是文字版 PDF 而不是扫描图片版。")
    print(f"简历读取成功,共 {len(cv_content)} 字符。")

    total = len(df)
    print(f"开始生成邮件,共 {total} 行...\n")

    for i in range(total):
        row = df.iloc[i]

        tutor_name = na_or(row.get("Prof_Full_Name"), "Professor")
        email_addr = na_or(row.get("Email Addresses"), "TBD")
        title      = na_or(row.get("Article Title"), "your recent work")
        abstract   = na_or(row.get("Abstract") if "Abstract" in df.columns else row.get("abstract"), "")
        direction  = na_or(row.get("Novel_Direction"), "future directions")

        safe_name = safe_filename(tutor_name)
        out_path = os.path.join(OUTPUT_DIR, f"{i + 1}_Email_to_{safe_name}.txt")

        # 断点续传: 已生成则跳过
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            print(f"[{i + 1}/{total}] 已存在,跳过: {os.path.basename(out_path)}")
            continue

        print(f"[{i + 1}/{total}] 正在生成: {tutor_name}", end=" ... ", flush=True)
        email_body = generate_email(
            tutor_name, title, abstract, direction, cv_content, prompt_base
        )

        if email_body:
            final_output = f"To: {email_addr}\n{email_body}"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(final_output)
            print("完成")
        else:
            print("失败,跳过")

        if SLEEP_SECONDS:
            time.sleep(SLEEP_SECONDS)

    print(f"\n任务完成! 请查看文件夹: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
