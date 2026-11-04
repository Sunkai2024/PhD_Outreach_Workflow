# -*- coding: utf-8 -*-
import os
import re
import json
import glob
import pandas as pd
import numpy as np
from getpass import getpass
from openai import OpenAI
from tqdm import tqdm

from load_config import DEEPSEEK_API_KEY, call_with_retry

# ==============================================================================
# 1. 配置区
# ==============================================================================
# 工作目录 = 本脚本所在目录 (load_config 已自动 chdir 过来)
# 把所有 WOS Excel 文件直接放到本目录即可, 无需再改路径。

# 目标国家列表
TARGET_COUNTRIES = ["germany", "ireland", "italy", "portugal", "spain", "france", "canada", "australia", "south korea"]

# 流水线中间产物和静态资源, 不算 WOS 源文件
INTERMEDIATE_FILES = {
    "verified_data_selected.xlsx",
    "verified_data_with_qs.xlsx",
    "selected.xlsx",
    "phd_fit_recommended.xlsx",
    "step5_checkpoint.xlsx",
    "2026_QS_ranking.xlsx",
}

# 国家名字典 (覆盖 WOS 常见写法)
COUNTRY_DICT = [
    # 目标国家
    "germany", "ireland", "italy", "portugal", "spain", "france",
    # 英语圈
    "england", "scotland", "wales", "uk", "united kingdom",
    "usa", "united states", "canada", "australia", "new zealand",
    # 亚洲
    "peoples r china", "china", "japan", "south korea", "india",
    "singapore", "taiwan", "thailand", "malaysia", "indonesia", "vietnam",
    # 欧洲其他
    "netherlands", "belgium", "switzerland", "austria", "sweden",
    "norway", "denmark", "finland", "poland", "czech republic",
    "greece", "romania", "hungary", "croatia", "turkey", "russia",
    # 美洲
    "brazil", "mexico", "argentina", "chile", "colombia",
    # 中东 / 非洲
    "saudi arabia", "israel", "egypt", "south africa", "nigeria"
]

# API 参数配置
BATCH_SIZE = 10
SYSTEM_PROMPT = '''Verify if each email belongs to the person. Return ONLY a JSON array of booleans in the same order. Example: [true, false, true]
Match: email contains name/surname, initial+surname, or abbreviation.
No match: completely different name or generic department email.'''

# ==============================================================================
# 2. 核心处理函数
# ==============================================================================

def extract_country(address):
    """稳健的国家提取函数：按逗号/分号拆段，从末尾往前匹配字典"""
    if pd.isna(address) or str(address).strip() == "":
        return np.nan
    
    parts = [p.strip().rstrip('.') for p in re.split(r'[,;]', str(address))]
    parts_lower = [p.lower() for p in parts]
    
    for part in reversed(parts_lower):
        if part in COUNTRY_DICT:
            return part.title() # 返回首字母大写
    return np.nan

def extract_prof_full_name(author_full_names, rp_short_name):
    """从全名列表中提取匹配的名字"""
    if pd.isna(author_full_names) or pd.isna(rp_short_name):
        return str(rp_short_name) if not pd.isna(rp_short_name) else ""
    all_names = [n.strip() for n in str(author_full_names).split(';')]
    for name in all_names:
        if str(rp_short_name) in name:
            return name
    return rp_short_name

def call_deepseek_batch(names, emails, client):
    """批量调用 DeepSeek API 进行匹配"""
    items = [f'{{"name":"{n}","email":"{e}"}}' for n, e in zip(names, emails)]
    user_input = f"[{','.join(items)}]"
    
    try:
        # 简单的 name/email 字符串匹配任务, 用 flash 足够, 也不开 thinking
        response = call_with_retry(
            client,
            label="step1",
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            stream=False,
        )
        content = response.choices[0].message.content
        # 提取并解析 JSON
        cleaned = re.sub(r'```json|```', '', content).strip()
        parsed = json.loads(cleaned)
        
        if isinstance(parsed, list) and len(parsed) == len(names):
            return parsed
        else:
            return [False] * len(names)
    except Exception as e:
        # 如果报错，静默返回 False 防止中断
        return [False] * len(names)

# ==============================================================================
# 3. 主流程 Pipeline
# ==============================================================================
def main():
    print(f"📂 工作目录: {os.getcwd()}")

    # 查找 WOS 导出文件 (.xls / .xlsx), 排除流水线中间产物和 QS 排名表
    file_list = glob.glob("*.xls") + glob.glob("*.xlsx")
    file_list = [f for f in file_list if f not in INTERMEDIATE_FILES]
    
    if not file_list:
        print("❌ 当前目录下未找到 Excel 文件，请检查路径。")
        return

    # 1. 验证 API Key (来自 config.json)
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=60,        # 单次调用最多等 60s
        max_retries=0,     # 重试统一交给 call_with_retry, 关掉 SDK 自带重试避免叠加
    )

    print(f"📄 开始读取文件 (共 {len(file_list)} 个)...")
    dfs = [pd.read_excel(f, dtype=str) for f in file_list]
    combined_data = pd.concat(dfs, ignore_index=True)

    print("🧹 第一阶段：清洗 WOS 数据...")
    df = combined_data.drop_duplicates(subset=['DOI'], keep='first').copy()
    cols_to_keep = ['Article Title', 'Email Addresses', 'DOI', 'Reprint Addresses', 'Author Full Names', 'Abstract']
    
    # 确保列存在
    for col in cols_to_keep:
        if col not in df.columns:
            df[col] = ""
    df = df[cols_to_keep].fillna("")

    # 拆分通讯作者行并清洗空格
    df = df.assign(**{'Reprint Addresses': df['Reprint Addresses'].str.split(';')}).explode('Reprint Addresses')
    df['Reprint Addresses'] = df['Reprint Addresses'].str.strip()
    
    # 过滤通讯作者关键词
    df = df[df['Reprint Addresses'].str.contains(r'(?i)通讯作者|corresponding author', regex=True, na=False)].copy()

    # 正则提取名称缩写和纯地址
    df['RP_Short_Name'] = df['Reprint Addresses'].apply(
        lambda x: re.search(r"^.*?(?=\s*\()", x).group(0).strip() if re.search(r"^.*?(?=\s*\()", x) else x
    )
    df['RP_Pure_Address'] = df['Reprint Addresses'].apply(
        lambda x: re.sub(r"^.*?\).*?[，,]\s*", "", x).strip()
    )

    # 匹配全名并拆分邮箱
    df['Prof_Full_Name'] = df.apply(lambda row: extract_prof_full_name(row['Author Full Names'], row['RP_Short_Name']), axis=1)
    df = df.assign(**{'Email Addresses': df['Email Addresses'].str.split(';')}).explode('Email Addresses')
    df['Email Addresses'] = df['Email Addresses'].str.strip()
    
    # 过滤掉名字或邮箱为空的无效行
    df = df[(df['Prof_Full_Name'] != "") & (df['Email Addresses'] != "")].copy()
    # 重置索引，防止后续按 index 匹配时出错
    df.reset_index(drop=True, inplace=True)
    
    print(f"🚀 有效姓名-邮箱对: {len(df)} 行 (将全部提交至 DeepSeek 进行验证)")

    # 准备 API 处理
    df['Match_Status'] = False
    api_indices = df.index.tolist()

    if api_indices:
        print("\n🧪 第二阶段：调用 DeepSeek AI 判断...")
        # 连通性测试 (用第一条数据)
        test_res = call_deepseek_batch(
            [df.loc[api_indices[0], 'Prof_Full_Name']], 
            [df.loc[api_indices[0], 'Email Addresses']], 
            client
        )
        if not test_res:
            print("❌ 测试失败！API 连接不通，请检查 Key、网络或模型状态。")
            return
        print("✅ 测试通过！开始批量验证...")

        # 进度条分批处理全部数据
        for i in tqdm(range(0, len(api_indices), BATCH_SIZE), desc="API 验证进度"):
            batch_idx = api_indices[i:i+BATCH_SIZE]
            names_batch = df.loc[batch_idx, 'Prof_Full_Name'].tolist()
            emails_batch = df.loc[batch_idx, 'Email Addresses'].tolist()
            
            results = call_deepseek_batch(names_batch, emails_batch, client)
            # 保证返回结果长度一致，防止赋值报错
            if len(results) == len(batch_idx):
                df.loc[batch_idx, 'Match_Status'] = results
    else:
        print("⚠️ 没有提取到有效的姓名-邮箱对。")
        return

    # 筛选大模型判定匹配成功的数据
    valid_matches = df[df['Match_Status'] == True].copy()
    
    print(f"\n   -> API 判定通过 {len(valid_matches)} 个，淘汰 {len(df) - len(valid_matches)} 个。")

    if len(valid_matches) == 0:
        print("⚠️ 没有匹配成功的记录，程序结束。")
        return

    print("\n🌍 第三阶段：筛选目标国家并去重精简...")
    valid_matches['Country'] = valid_matches['RP_Pure_Address'].apply(extract_country)
    
    # 提示未识别出国家的行
    n_no_country = valid_matches['Country'].isna().sum()
    if n_no_country > 0:
        print(f"   ⚠️ 有 {n_no_country} 行未识别到国家，可能需要补充 COUNTRY_DICT。")

    # 过滤目标国家 (统一转小写进行对比)
    final_result = valid_matches[valid_matches['Country'].str.lower().isin(TARGET_COUNTRIES)].copy()
    
    # 智能去重：优先保留带 .edu 的邮箱
    final_result['is_edu'] = final_result['Email Addresses'].str.contains(r'\.edu', regex=True, na=False)
    final_result = final_result.sort_values('is_edu', ascending=False)
    # 按姓名和邮箱去重
    final_result = final_result.drop_duplicates(subset=['Prof_Full_Name'], keep='first')
    final_result = final_result.drop_duplicates(subset=['Email Addresses'], keep='first')

    # 输出指定列
    final_columns = [
        'Prof_Full_Name', 'Email Addresses', 'Country', 
        'RP_Pure_Address', 'Article Title', 'DOI', 'Abstract'
    ]
    final_result = final_result[final_columns]

    print("\n📊 最终结果统计:")
    print(f"   - 目标国家内总人数: {len(final_result)}")
    if len(final_result) > 0:
        country_counts = final_result['Country'].value_counts()
        for c, count in country_counts.items():
            print(f"   - {c}: {count} 人")
    
    # 保存结果
    output_filename = "verified_data_selected.xlsx"
    final_result.to_excel(output_filename, index=False)
    print(f"\n💾 恭喜！处理已完成，已直接生成精简名单：{os.path.abspath(output_filename)}")

if __name__ == "__main__":
    main()
