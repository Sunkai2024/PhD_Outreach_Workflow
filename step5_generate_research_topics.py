import os
import time
import json
import re
import pandas as pd
from openai import OpenAI
from pypdf import PdfReader

from load_config import DEEPSEEK_API_KEY, find_cv_pdf, call_with_retry

# ================= 配置区域 =================
MODEL_NAME = "deepseek-v4-pro"

INPUT_FILE = "phd_fit_recommended.xlsx"
CV_FILE = find_cv_pdf()   # 自动定位本目录下的 CV PDF
CHECKPOINT_FILE = "step5_checkpoint.xlsx"

SAVE_INTERVAL = 5
SLEEP_SECONDS = 0.1

# ================= 读取 CV =================

def extract_cv_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

# ================= API 调用 =================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=60,        # 单次调用最多等 60s
    max_retries=0,     # 重试统一交给 call_with_retry, 关掉 SDK 自带重试避免叠加
)

def build_system_prompt(cv_text: str) -> str:
    return f"""Act as a Senior Biology Professor and PhD Thesis Advisor.
You are helping a PhD applicant identify suitable research projects based on a professor's published work.

The applicant's academic background is as follows:
---
{cv_text}
---

For each abstract provided, perform the following tasks:
1. Identify a key research gap or limitation in the work.
2. Formulate a profound academic question the applicant could investigate.
3. Propose exactly one novel research direction that aligns with both the abstract and the applicant's background.

IMPORTANT: Output strictly valid JSON with exactly these three keys: "gap", "question", "direction".
Do not include markdown code blocks or any extra text outside the JSON."""

def call_api(abstract_text: str, system_prompt: str) -> dict:
    if not abstract_text or pd.isna(abstract_text):
        return {"gap": None, "question": None, "direction": None}

    try:
        response = call_with_retry(
            client,
            label="step5",
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(abstract_text)},
            ],
            stream=False,
            temperature=0.2,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        raw_text = response.choices[0].message.content or ""
        clean_json = re.sub(r"```json|```", "", raw_text).strip()
        parsed = json.loads(clean_json)
        return {
            "gap": parsed.get("gap"),
            "question": parsed.get("question"),
            "direction": parsed.get("direction"),
        }
    except Exception as e:
        print(f"  API 错误: {e}")
        return {"gap": None, "question": None, "direction": None}

# ================= 主逻辑：断点续传 =================

def main():
    # 1. 加载数据
    if os.path.exists(CHECKPOINT_FILE):
        print(f"检测到存档文件 {CHECKPOINT_FILE}，正在恢复进度...")
        df = pd.read_excel(CHECKPOINT_FILE)
    else:
        print("未检测到存档，读取原始文件并初始化...")
        if not os.path.exists(INPUT_FILE):
            raise FileNotFoundError(f"找不到输入文件：{INPUT_FILE}")
        df = pd.read_excel(INPUT_FILE)
        df["Research_Gap"] = None
        df["Academic_Question"] = None
        df["Novel_Direction"] = None

    # 2. 读取 CV
    print(f"读取申请人简历：{CV_FILE}")
    cv_text = extract_cv_text(CV_FILE)
    system_prompt = build_system_prompt(cv_text)

    total = len(df)
    print(f"总行数：{total}，每 {SAVE_INTERVAL} 行自动保存一次\n")

    # 3. 循环处理
    for i in range(total):
        # 断点跳过
        if pd.notna(df.at[i, "Research_Gap"]) and str(df.at[i, "Research_Gap"]).strip():
            continue

        print(f"正在处理第 {i + 1} / {total} 行...", end=" ", flush=True)
        result = call_api(df.at[i, "abstract"], system_prompt)

        df.at[i, "Research_Gap"] = result["gap"]
        df.at[i, "Academic_Question"] = result["question"]
        df.at[i, "Novel_Direction"] = result["direction"]
        print("完成。")

        if (i + 1) % SAVE_INTERVAL == 0:
            print(">>> 正在自动保存存档...")
            df.to_excel(CHECKPOINT_FILE, index=False)

        time.sleep(SLEEP_SECONDS)

    # 4. 最终保存
    print("\n所有数据处理完毕！最终保存中...")
    df.to_excel(CHECKPOINT_FILE, index=False)
    print(f"保存成功：{os.path.abspath(CHECKPOINT_FILE)}")

if __name__ == "__main__":
    main()
