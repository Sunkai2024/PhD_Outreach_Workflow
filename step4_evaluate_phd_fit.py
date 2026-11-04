"""
Evaluate PhD application fit by comparing the applicant's CV against
paper abstracts from selected.xlsx using DeepSeek API.

Sequential processing (one paper at a time).
Output: only papers judged as suitable are saved.
"""

import time
import pandas as pd
import pdfplumber
from openai import OpenAI

from load_config import DEEPSEEK_API_KEY, find_cv_pdf, call_with_retry

# ---------- Config ----------
XLSX_PATH = "selected.xlsx"
CV_PATH = find_cv_pdf()   # 自动定位本目录下的 CV PDF
RECOMMENDED_PATH = "phd_fit_recommended.xlsx"
MODEL = "deepseek-v4-pro"
SLEEP_BETWEEN_CALLS = 1.0


# ---------- Helpers ----------
def read_cv(pdf_path: str) -> str:
    """Extract all text from a PDF CV."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


def read_abstracts(xlsx_path: str) -> pd.DataFrame:
    """Read xlsx and keep only rows with a non-empty abstract in column G."""
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    col_g = df.columns[6]  # G column = index 6
    df = df.rename(columns={col_g: "abstract"})
    df = df[df["abstract"].notna() & (df["abstract"].astype(str).str.strip() != "")]
    return df.reset_index(drop=True)


def build_prompt(cv_text: str, abstract: str, row_info: dict) -> str:
    paper_meta = ""
    for k, v in row_info.items():
        if k != "abstract" and pd.notna(v):
            paper_meta += f"{k}: {v}\n"

    return f"""以下是申请者的简历（CV）：

--- CV START ---
{cv_text}
--- CV END ---

以下是一篇论文的信息：
{paper_meta}
Abstract: {abstract}

请根据申请者的研究背景与这篇论文的研究方向，判断申请者是否适合向该论文的通讯作者申请博士。
如果申请者和导师方向完全不一致，如研究者做的是生命科学基础类研究，而论文是纯计算机算法，或者流行病学等，判定为不适合。
不考虑研究主题的差异，如申请者研究乳腺癌，而论文研究肺癌，这种情况不影响适合与否的判断。
不考虑申请者的地理因素和语言因素。
不考虑申请者是否关注基础研究还是临床转换研究。

只输出一个字：是 或 否。
不要输出其他任何内容、解释、标点。
"""


def is_suitable(client: OpenAI, cv_text: str, abstract: str, row_info: dict) -> bool:
    """Ask DeepSeek for a single yes/no judgement."""
    prompt = build_prompt(cv_text, abstract, row_info)
    resp = call_with_retry(
        client,
        label="step4",
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是一位经验丰富的留学申请顾问，只输出'是'或'否'。"},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    content = (resp.choices[0].message.content or "").strip()
    # 取第一个字符判断，兼容模型偶尔多输出的情况
    return content.startswith("是")


# ---------- Main ----------
def main():
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=60,        # 单次调用最多等 60s
        max_retries=0,     # 重试统一交给 call_with_retry, 关掉 SDK 自带重试避免叠加
    )

    print("[1/3] 读取 CV ...")
    cv_text = read_cv(CV_PATH)
    print(f"      CV 字符数: {len(cv_text)}")

    print("[2/3] 读取摘要 ...")
    df = read_abstracts(XLSX_PATH)
    total = len(df)
    print(f"      共 {total} 篇论文待评估")

    print("[3/3] 调用 DeepSeek 逐篇评估 ...")
    recommended_rows = []
    for i, row in df.iterrows():
        abstract = str(row["abstract"])
        row_info = {c: row[c] for c in df.columns if c != "abstract"}

        print(f"  [{i+1}/{total}] 评估中 ...", end=" ", flush=True)
        try:
            ok = is_suitable(client, cv_text, abstract, row_info)
            print("是" if ok else "否")
        except Exception as e:
            print(f"ERROR: {e}")
            ok = False

        if ok:
            recommended_rows.append(row.to_dict())
            # 每新增一条就保存一次，防止崩溃丢失
            pd.DataFrame(recommended_rows).to_excel(
                RECOMMENDED_PATH, index=False, engine="openpyxl"
            )

        if SLEEP_BETWEEN_CALLS > 0:
            time.sleep(SLEEP_BETWEEN_CALLS)

    if recommended_rows:
        pd.DataFrame(recommended_rows).to_excel(
            RECOMMENDED_PATH, index=False, engine="openpyxl"
        )
        print(f"\n推荐教授已保存: {RECOMMENDED_PATH}")
    else:
        print("\n没有匹配的教授。")

    print(f"\n汇总：{len(recommended_rows)} / {total} 篇推荐申请")


if __name__ == "__main__":
    main()
