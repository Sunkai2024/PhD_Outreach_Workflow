import os
import json
import time
import pickle
import re
import pandas as pd
import numpy as np
from openai import OpenAI

# 非 QS 排名的顶尖研究所白名单 (与本脚本同目录)
from research_institutes_whitelist import WHITELIST

# 统一配置: DeepSeek API key + QS 录取阈值 (从 config.json 读取)
from load_config import DEEPSEEK_API_KEY, QS_THRESHOLD, call_with_retry

# ─── 配置 ─────────────────────────────────────────────────────────────────────
INPUT_FILE       = "verified_data_selected.xlsx"
QS_FILE          = "2026_QS_ranking.xlsx"
OUTPUT_FILE      = "verified_data_with_qs.xlsx"
PROGRESS_FILE    = "qs_match_progress.pkl"
BATCH_SIZE       = 10
SLEEP_BETWEEN    = 0.1

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=60,        # 单次调用最多等 60s
    max_retries=0,     # 重试统一交给 call_with_retry, 关掉 SDK 自带重试避免叠加
)

# ─── 核心逻辑函数 ─────────────────────────────────────────────────────────────
def get_email_domain(email):
    """精确提取域名，如 researcher@example.edu -> example.edu。"""
    if pd.isna(email) or "@" not in str(email):
        return "Unknown Domain"
    return str(email).split("@")[-1].strip().lower()

def create_rich_key(row):
    """
    创建一个包含地址首段和域名的富 Key。
    例如: "Department of Biomedicine | ub.edu"
    这能确保 API 看到机构名和域名的组合，显著提升识别率。
    """
    addr = str(row.get("RP_Pure_Address", ""))
    inst_part = addr.split(",")[0].strip() if addr != "nan" else "Unknown Inst"
    
    # 自动尝试多个可能的邮箱列名
    email = row.get("Email") or row.get("EM") or row.get("Email Address")
    domain = get_email_domain(email)
    
    return f"{inst_part} || {domain}"


def parse_qs_rank(rank_str):
    """把 QS rank 字符串转成数值。
    - '1' -> 1
    - '501-600' -> 501 (取下界)
    - 'N/A' / '' / 'Unknown' / None -> NaN
    """
    if rank_str is None:
        return np.nan
    s = str(rank_str).strip()
    if s in ("", "N/A", "Unknown", "nan", "None"):
        return np.nan
    m = re.match(r"^\s*(\d+)", s)
    return int(m.group(1)) if m else np.nan


def match_research_institute(address, domain, whitelist=WHITELIST):
    """白名单关键词匹配。命中返回机构名, 否则返回 None。
    匹配范围: RP_Pure_Address (全段) + 邮箱域名 (小写)。
    """
    haystack = (str(address) + " || " + str(domain)).lower()
    for inst in whitelist:
        for kw in inst.get("keywords", []):
            if kw.lower() in haystack:
                return inst["name"]
    return None


def assign_tier(qs_num, institute_match, threshold=QS_THRESHOLD):
    """根据 QS rank 数值和白名单匹配结果分层。
    优先级: QS rank 数值 > 白名单 > Unknown。
    """
    if pd.notna(qs_num):
        if qs_num <= 100:
            return "Top100"
        if qs_num <= threshold:
            return f"Top{threshold}"
        if qs_num <= 500:
            return "Top500"
        return "Other"
    if institute_match:
        return "Research Institute"
    return "Unknown"


# ─── 1. 加载数据 ─────────────────────────────────────────────────────────────
print("🚀 正在从头开始加载数据...")
data = pd.read_excel(INPUT_FILE, dtype=str)
qs_ranking = pd.read_excel(QS_FILE, dtype=str)

# 构建 QS 知识库字符串
qs_reference = "\n".join(
    f"{row['Rank']} | {row['University']} | {row['Country/Territory']}"
    for _, row in qs_ranking.iterrows()
)

# ─── 2. 预处理 ───────────────────────────────────────────────────────────────
data["_rich_key_"] = data.apply(create_rich_key, axis=1)

# 获取唯一组合
unique_tasks = (
    data.drop_duplicates(subset=["_rich_key_"])
    [["_rich_key_", "RP_Pure_Address"]]
    .reset_index(drop=True)
)

# 分离出地址和域名供 API 使用
unique_tasks["pure_addr"] = unique_tasks["RP_Pure_Address"]
unique_tasks["domain"] = unique_tasks["_rich_key_"].apply(lambda x: x.split(" || ")[-1])

# ─── 3. 系统提示词优化 ────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "你是一个全球顶尖的学术机构识别专家。\n"
    "你的任务是根据【学术地址】和【邮箱域名】判定所属的 QS 2026 排名大学。\n\n"
    "⚠️ 重要判定准则：\n"
    "1. 优先级推理：如果地址中的机构名模糊（如：Department of Medicine），必须强制根据【邮箱域名】进行关联推理。\n"
    "2. 域名关联逻辑示例：\n"
    "   - domain: 'ub.edu' -> University of Barcelona (巴塞罗那大学)\n"
    "   - domain: 'hku.hk' -> University of Hong Kong\n"
    "   - domain: 'tsinghua.edu.cn' -> Tsinghua University\n"
    "3. 即使地址里没写大学全称，只要域名指向该大学，就必须判定为该大学。\n\n"
    "参考 QS 2026 列表如下：\n" + qs_reference
)

# ─── 4. 断点续传 ─────────────────────────────────────────────────────────────
cache = {}
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "rb") as f:
        cache = pickle.load(f)

todo = unique_tasks[~unique_tasks["_rich_key_"].isin(cache)].reset_index(drop=True)
print(f"📊 总数据量: {len(data)} | 唯一识别任务: {len(unique_tasks)} | 待处理: {len(todo)}")

# ─── 5. API 调用 ──────────────────────────────────────────────────────────────
def call_expert_api(batch):
    # 格式化输入，显式把域名和地址对应起来
    lines = []
    for i, row in batch.iterrows():
        lines.append(f"Case {i+1}:\n- 地址: {row['pure_addr']}\n- 邮箱域名: {row['domain']}")
    
    user_content = "\n\n".join(lines) + (
        "\n\n请返回 JSON 数组，格式如下：\n"
        "[{\"index\":1, \"matched_university\":\"...\", \"qs_rank\":\"...\"}]"
    )

    fallback = [{"rich_key": r["_rich_key_"], "univ": "Unknown", "rank": "N/A"} for _, r in batch.iterrows()]

    try:
        response = call_with_retry(
            client,
            label="step2",
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={'type': 'json_object'}
        )
        reply = response.choices[0].message.content.strip()
        
        # 解析数据
        match = re.search(r"\[.*\]", reply, re.DOTALL)
        parsed = json.loads(match.group() if match else reply)
        if isinstance(parsed, dict): # 处理嵌套在 key 里的情况
            for k in parsed:
                if isinstance(parsed[k], list):
                    parsed = parsed[k]
                    break
        
        results = fallback.copy()
        for item in parsed:
            idx = int(item.get("index", 0)) - 1
            if 0 <= idx < len(batch):
                results[idx] = {
                    "rich_key": batch.iloc[idx]["_rich_key_"],
                    "univ": str(item.get("matched_university", "Unknown")),
                    "rank": str(item.get("qs_rank", "N/A"))
                }
        return results
    except Exception as e:
        print(f" ⚠️ 调用出错: {e}")
        return fallback

# ─── 6. 执行批处理 ────────────────────────────────────────────────────────────
if len(todo) > 0:
    for b_idx in range(0, len(todo), BATCH_SIZE):
        batch = todo.iloc[b_idx : b_idx + BATCH_SIZE].reset_index(drop=True)
        print(f"🔎 正在处理批次 {b_idx//BATCH_SIZE + 1}/{len(todo)//BATCH_SIZE + 1}...", end="", flush=True)
        
        batch_res = call_expert_api(batch)
        for r in batch_res:
            cache[r["rich_key"]] = {"univ": r["univ"], "rank": r["rank"]}
        
        # 实时保存进度
        with open(PROGRESS_FILE, "wb") as f:
            pickle.dump(cache, f)
        
        time.sleep(SLEEP_BETWEEN)
        print(" 完成")

# ─── 7. 回填与分层 ────────────────────────────────────────────────────────────
print("\n📝 正在回填最终结果...")
data["QS_University"] = data["_rich_key_"].map(lambda k: cache[k]["univ"] if k in cache else "Unknown")
data["QS_Rank"]       = data["_rich_key_"].map(lambda k: cache[k]["rank"] if k in cache else "N/A")

# QS_Rank 数值化 (便于在 Excel 中排序/比较, 区间排名取下界)
data["QS_Rank_Num"] = data["QS_Rank"].apply(parse_qs_rank)

# 白名单匹配 (针对没有 QS 排名的研究所; 用全段地址 + 邮箱域名)
domain_col = data["_rich_key_"].apply(
    lambda k: str(k).split(" || ")[-1] if " || " in str(k) else ""
)
data["Research_Institute"] = [
    match_research_institute(addr, dom)
    for addr, dom in zip(data["RP_Pure_Address"], domain_col)
]

# 分层标签: Top100 / Top{QS_THRESHOLD} / Research Institute / Top500 / Other / Unknown
data["Tier"] = [
    assign_tier(qs_num, inst)
    for qs_num, inst in zip(data["QS_Rank_Num"], data["Research_Institute"])
]

# 清理临时列
final_data = data.drop(columns=["_rich_key_"], errors='ignore')

# 按 Tier (自定义顺序) + QS_Rank_Num 升序排序, 方便手工筛选
tier_order = {
    "Top100": 0,
    f"Top{QS_THRESHOLD}": 1,
    "Research Institute": 2,
    "Top500": 3,
    "Other": 4,
    "Unknown": 5,
}
final_data["_tier_rank_"] = final_data["Tier"].map(tier_order).fillna(99)
final_data = (
    final_data
    .sort_values(by=["_tier_rank_", "QS_Rank_Num"], na_position="last")
    .drop(columns=["_tier_rank_"])
    .reset_index(drop=True)
)

# ─── 8. 统计并保存 ────────────────────────────────────────────────────────────
final_data.to_excel(OUTPUT_FILE, index=False)
success_count = final_data[final_data["QS_Rank"] != "N/A"].shape[0]

print("-" * 30)
print(f"✅ 处理完成！保存至: {OUTPUT_FILE}")
print(f"📈 成功匹配 QS 机构数: {success_count} / {len(final_data)}")

# Tier 分布 (建议保留前三档作为 selected.xlsx)
print(f"\n📊 Tier 分布 (建议筛选: Top100 + Top{QS_THRESHOLD} + Research Institute):")
tier_counts = (
    final_data["Tier"]
    .value_counts()
    .reindex(["Top100", f"Top{QS_THRESHOLD}", "Research Institute", "Top500", "Other", "Unknown"])
    .fillna(0)
    .astype(int)
)
recommended = 0
for tier, n in tier_counts.items():
    mark = " ⭐" if tier in ("Top100", f"Top{QS_THRESHOLD}", "Research Institute") else ""
    print(f"   - {tier}: {n}{mark}")
    if mark:
        recommended += n
print(f"\n   推荐入选总数: {recommended} / {len(final_data)}")
print("-" * 30)
