# -*- coding: utf-8 -*-
"""
Step 3: 从 Step 2 输出中自动筛选目标导师, 输出 selected.xlsx 供 Step 4 使用。

筛选规则:
- 大学:   QS 排名 <= QS_THRESHOLD  (即 Tier ∈ {Top100, Top<QS_THRESHOLD>})
- 研究所: 命中 research_institutes_whitelist.py 中的白名单 (Tier == Research Institute)
- 其余:   Top500 / Other / Unknown 全部淘汰

QS_THRESHOLD 在 config.json 中配置, 当前文件无需任何编辑即可使用。
"""

import pandas as pd
from load_config import QS_THRESHOLD

INPUT_FILE  = "verified_data_with_qs.xlsx"
OUTPUT_FILE = "selected.xlsx"

KEEP_TIERS = {"Top100", f"Top{QS_THRESHOLD}", "Research Institute"}


def main():
    print(f"📂 读取 {INPUT_FILE} ...")
    df = pd.read_excel(INPUT_FILE)

    if "Tier" not in df.columns:
        raise KeyError(
            "输入文件缺 'Tier' 列。请先用更新版 Step 2 (step2_detect_university.py) 重新生成。"
        )

    total = len(df)
    selected = df[df["Tier"].isin(KEEP_TIERS)].copy().reset_index(drop=True)

    print(f"\n📊 筛选结果:")
    print(f"   - 入选规则: Tier ∈ {sorted(KEEP_TIERS)}")
    print(f"   - 总行数:   {total}")
    print(f"   - 入选:     {len(selected)}")
    print(f"   - 淘汰:     {total - len(selected)}")

    # 各档分布
    if len(selected) > 0:
        print("\n   各档分布:")
        breakdown = selected["Tier"].value_counts().reindex(sorted(KEEP_TIERS)).fillna(0).astype(int)
        for tier, n in breakdown.items():
            print(f"     · {tier}: {n}")

    selected.to_excel(OUTPUT_FILE, index=False)
    print(f"\n✅ 已保存: {OUTPUT_FILE}  (共 {len(selected)} 位导师, 可进 Step 4)")


if __name__ == "__main__":
    main()
