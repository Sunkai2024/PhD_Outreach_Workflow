# PhD Outreach Workflow · 博士套磁信工作流

**有需求欢迎交流**


<img width="652" height="671" alt="微信图片_20261104172708_25_95(1)" src="https://github.com/user-attachments/assets/83ffe617-45e6-42d4-ad8c-db294e9b5f96" />

将 Web of Science 导出的论文数据与申请人的 PDF 简历结合，完成导师筛选、研究方向建议、套磁信生成及润色。当前提示词和研究所白名单以生物医学为主。

主流程共 7 步，输出为邮件文本。另附 Gmail OAuth 授权工具，用于准备后续发送程序需要的授权文件；本项目目前没有发送邮件或批量发送的程序。

## 1. 开始前需要准备什么

| 材料或账号 | 获取位置 | 用途 |
| --- | --- | --- |
| Python 3.12 和 conda | [Miniconda 安装文档](https://www.anaconda.com/docs/getting-started/miniconda/install) | 运行脚本、隔离依赖 |
| Web of Science 访问权限 | [Web of Science](https://www.webofscience.com/) | 检索论文、导出 Excel，一般通过学校或图书馆访问 |
| QS 2026 排名数据 | [QS World University Rankings 2026](https://www.topuniversities.com/world-university-rankings/2026) | 匹配大学排名 |
| DeepSeek API 账号及密钥 | [DeepSeek 开放平台](https://platform.deepseek.com/) | 调用模型完成筛选与写信 |
| 申请人简历 | 申请人提供的文字版 PDF | 提取背景、经历和研究技能 |
| Gmail 账号与 Google Cloud 项目（可选） | [Google Cloud Console](https://console.cloud.google.com/) | 为后续发送程序准备 OAuth 授权 |

DeepSeek 网页聊天的登录状态不能代替 API 密钥。API 调用会产生费用，需要确保 API 账户可用。

## 2. 路径与目录怎么安排

### 2.1 核心规则

主流程通过同目录下的 load_config.py 定位工作目录。脚本会自动切换到该目录，然后从这里读取输入并写入结果。

- **一位申请人、一轮数据使用一份独立工作目录。**
- Python 脚本、WOS Excel、CV PDF 和 QS Excel 放在工作目录的同一层。
- 目前不会自动扫描 input/、data/、CV/ 等子目录，资料放进去不会被自动发现。
- 输出也写在工作目录中；仅在终端 cd 到另一个目录，不能改变输出位置。
- 将源码复制到新的工作目录后运行，通常不需要修改代码中的绝对路径。不要用指向源码目录的符号链接代替副本。

### 2.2 推荐的本地目录框架

下面以 Windows E 盘为例，目录名可自行调整，示例不包含真实申请人信息。

~~~text
E:\phd-outreach\
├── repository\                       干净源码，用于 GitHub
│   ├── README.md
│   ├── config.example.json
│   ├── load_config.py
│   ├── requirements.txt
│   ├── requirements-gmail.txt
│   ├── authorize_gmail.py
│   ├── research_institutes_whitelist.py
│   ├── 套磁信prompt.txt
│   ├── step1_clean_wos.py
│   ├── step2_detect_university.py
│   ├── step3_filter_top_tiers.py
│   ├── step4_evaluate_phd_fit.py
│   ├── step5_generate_research_topics.py
│   ├── step6_generate_emails.py
│   ├── step7_polish_letters.py
│   ├── start.sh
│   ├── run_pipeline.sh
│   ├── run_rest.sh
│   └── tests\

~~~

首次使用可将下载并解压的干净源码保留在 repository，再用文件管理器将其公开文件全部复制到全新的 applicant-001 目录，包括 requirements.txt、config.example.json 和提示词。若源码来自 git clone，不需要复制 .git 目录。不要从已有运行结果的申请人目录复制新任务。

只向 GitHub 上传 repository 的公开源码。runs 和 gmail-private 都放在仓库外。

### 2.3 同一路径在不同环境中的写法

| 环境 | 示例路径 | 使用位置 |
| --- | --- | --- |
| Windows PowerShell / Windows Python | E:\phd-outreach\runs\applicant-001 | Windows 终端命令和 Python 参数 |
| WSL Ubuntu | /mnt/e/phd-outreach/runs/applicant-001 | WSL 的 Bash 和 Linux Python |
| Linux 服务器 | /home/your-user/phd-outreach-runs/applicant-001 | 服务器 SSH 终端 |

含空格或中文的路径用引号括起来。Windows 路径不能原样传给 Linux Python；WSL 路径也不能原样传给 Windows Python。WSL 中需要 Linux 版 conda，Windows 的 conda 环境不会自动成为 WSL 环境。

服务器的目录结构与本地相同。将源码副本、CV 和 Excel 上传到服务器的同一工作目录，再从该目录启动。

### 2.4 建立第一份运行目录

先将公开源码解压到示例的 repository 目录。下面的命令用于尚未开始运行的新目录；若 applicant-001 已有资料，请使用新名称。

Windows PowerShell：

~~~powershell
$sourceDir = "E:\phd-outreach\repository"
$caseDir = "E:\phd-outreach\runs\applicant-001"
New-Item -ItemType Directory -Force -Path $caseDir | Out-Null
Get-ChildItem -LiteralPath $sourceDir -Force |
    Where-Object { $_.Name -notin @(".git", "__pycache__", ".venv") } |
    Copy-Item -Destination $caseDir -Recurse
Set-Location $caseDir
~~~

Linux / WSL（需要 rsync）：

~~~bash
SOURCE_DIR="/mnt/e/phd-outreach/repository"
CASE_DIR="/mnt/e/phd-outreach/runs/applicant-001"
mkdir -p "$CASE_DIR"
rsync -a --exclude='.git/' --exclude='__pycache__/' --exclude='.venv/' "$SOURCE_DIR/" "$CASE_DIR/"
cd "$CASE_DIR"
~~~

随后把 CV.pdf、WOS 导出表和 2026_QS_ranking.xlsx 放入该目录，按第 3、5 节安装依赖和创建本地配置。源码目录应保持干净，避免把其他申请人的输入或结果一起复制。

## 3. 安装运行环境

### 3.1 Linux / WSL / 服务器：推荐方式

安装适合当前系统的 Miniconda，打开 Bash 后执行：

~~~bash
conda create -n agent python=3.12 -y
conda activate agent
cd "/mnt/e/phd-outreach/runs/applicant-001"
python -m pip install -r requirements.txt
python --version
~~~

服务器用户将 cd 后的路径替换为自己的工作目录。推荐 Python 3.12；不需要把旧 Python 安装目录复制到项目里。

run_pipeline.sh 和 run_rest.sh 默认激活名为 agent 的 conda 环境。使用其他环境名称时：

~~~bash
CONDA_ENV=my-env bash run_pipeline.sh
~~~

脚本会寻找 conda.sh；找不到时可用 CONDA_SH 指定实际路径。PYTHON_BIN 可指定解释器，但不会跳过 conda 激活。

### 3.2 Windows 原生 Python

在 Miniconda Prompt 中创建环境，激活后进入工作目录：

~~~powershell
conda create -n agent python=3.12 -y
conda activate agent
cd "E:\phd-outreach\runs\applicant-001"
python -m pip install -r requirements.txt
~~~

Python 步骤可在 Windows 原生环境逐个执行。三个 .sh 文件使用 Bash，后台启动的 start.sh 还依赖 Linux /proc。Windows 原生运行请按第 6 节逐步执行 Python；希望一键后台运行时使用 Linux / WSL。

## 4. 去哪里下载数据、如何导出

### 4.1 Web of Science：论文数据

1. 打开 [Web of Science](https://www.webofscience.com/)，通过学校或图书馆提供的方式（小黄鱼）进入检索。
2. 在 Web of Science Core Collection 中按学科、主题、年份和文献类型筛选，确认主题与申请人相关。
3. 选择记录，进入 Export / 导出，选择 Excel 格式。
4. 记录内容选择 Full Record / 完整记录，或自定义字段，确保包含下表的字段。仅导出“作者、标题、来源”通常不够。
5. 按页面允许的条数分批导出，保留真正的 .xls 或 .xlsx 格式，命名为 wos_batch_001.xls、wos_batch_002.xls 等，放进申请人工作目录。
6. 打开一份表格检查：第一行是字段名，每行一篇论文，没有额外说明行、合并标题或手工改过的中文表头。

不同账号的界面及单批上限可能不同，以页面选项为准。脚本不能直接读取网页、CSV、BibTeX 或 Plain Text；不要只修改后缀来转换格式。

| 代码要求的列名 | 内容与注意事项 |
| --- | --- |
| Article Title | 论文标题 |
| Email Addresses | 作者邮箱；多个邮箱用分号分隔 |
| DOI | 论文 DOI；第 1 步按此列去重，缺少 DOI 的记录可能被合并，需先检查 |
| Reprint Addresses | 通讯作者及地址；应含 corresponding author 或“通讯作者”标记 |
| Author Full Names | 作者全名 |
| Abstract | 论文摘要，不能只导出题录 |

第 1 步读取工作目录中所有 .xls / .xlsx，排除已知中间文件和名为 2026_QS_ranking.xlsx 的排名表。该目录不要混放费用清单等无关 Excel。

### 4.2 QS：大学排名数据

在 [QS 2026 世界大学排名页](https://www.topuniversities.com/world-university-rankings/2026) 获取 2026 年度数据；如页面提供下载入口，可登录后下载。不要用其他年份的数据代替。

将数据整理成 2026_QS_ranking.xlsx，放到申请人工作目录。第一张工作表的第一行必须包含以下列名，注意大小写与斜杠：

| Rank | University | Country/Territory |
| --- | --- | --- |
| 10 | Example University | Example Country |

上表仅演示格式，数据为虚构示例。实际填官方排名、大学英文名称和国家或地区。Rank 应从数字开始，例如 10 或 501-600；有 = 等前缀时先清理。区间排名取下界。

项目不附带 QS 原表，也不会自动下载或清洗官网文件。第 2 步的文件名和提示词均按 2026 年设计。

### 4.3 CV：申请人简历

使用文字版 PDF，命名为 CV.pdf，放进申请人工作目录。可以尝试从 PDF 选中并复制一段文字，确认不是只有扫描图片。

自动选择规则：优先取文件名含 cv（不区分大小写）的 PDF；没有这类文件时，仅在目录中恰好只有一份 PDF 时使用它。多份 CV 或含糊的多份 PDF 会报错。不要把流程 PDF、成绩单等一起放进该目录。

### 4.4 已随源码提供的资源

- research_institutes_whitelist.py：研究所白名单，可按申请人学科调整。
- 套磁信prompt.txt：邮件模板，仅应引用 CV 和论文资料明确支持的事实。
- step1_clean_wos.py 中的 TARGET_COUNTRIES：默认德国、爱尔兰、意大利、葡萄牙、西班牙、法国、加拿大、澳大利亚、韩国。

## 5. 配置 DeepSeek

在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API 密钥，任选下面一种配置方式。

### 5.1 本地配置文件：适合首次部署

Linux / WSL / 服务器：

~~~bash
cd "/mnt/e/phd-outreach/runs/applicant-001"
cp config.example.json config.json
~~~

Windows PowerShell：

~~~powershell
Set-Location "E:\phd-outreach\runs\applicant-001"
Copy-Item config.example.json config.json
~~~

用编辑器打开本地 config.json，填入自己的密钥：

~~~json
{
  "deepseek_api_key": "your-api-key",
  "qs_threshold": 350
}
~~~

your-api-key 是占位符，必须替换。默认保留 Top100、Top350 和白名单研究所；修改 qs_threshold 后第 2、3 步读取同一阈值。本地 config.json 不会被 Git 默认收录。

### 5.2 环境变量

Linux / WSL / 服务器可交互输入，避免把密钥直接写进命令历史：

~~~bash
read -rsp 'DeepSeek API key: ' DEEPSEEK_API_KEY
echo
export DEEPSEEK_API_KEY
export QS_THRESHOLD=350
~~~

Windows PowerShell 可使用 $env:DEEPSEEK_API_KEY 和 $env:QS_THRESHOLD 设置进程环境变量，也可继续使用本地 config.json。

环境变量优先于 config.json。项目不会自动读取 .env。终端设置的变量不会自动出现在下一次 SSH 登录中；后台任务继承启动时的环境。

默认模型是 deepseek-v4-flash 和 deepseek-v4-pro，以账户实际可用列表为准；可修改对应脚本的 model、MODEL 或 MODEL_NAME。第 7 步额外支持 DEEPSEEK_MODEL、DEEPSEEK_BASE_URL、DEEPSEEK_REASONING_EFFORT 和 SLEEP_BETWEEN 环境变量。

## 6. 按 1–7 步运行

| 步骤 | 脚本 | 输出 |
| --- | --- | --- |
| 1. 数据清洗、姓名邮箱匹配、国家筛选 | step1_clean_wos.py | verified_data_selected.xlsx |
| 2. 大学识别、QS 排名与研究所分层 | step2_detect_university.py | verified_data_with_qs.xlsx |
| 3. 保留目标层级 | step3_filter_top_tiers.py | selected.xlsx |
| 4. 判断 CV 与论文方向是否匹配 | step4_evaluate_phd_fit.py | phd_fit_recommended.xlsx |
| 5. 生成研究空白、问题和建议方向 | step5_generate_research_topics.py | step5_checkpoint.xlsx |
| 6. 生成邮件草稿 | step6_generate_emails.py | Generated_Emails_PDF/*.txt |
| 7. 轮换五种风格润色 | step7_polish_letters.py | Generated_Emails_PDF_polished/*.txt |

Generated_Emails_PDF 是保留的历史目录名，实际输出为 .txt。每封文件一般包含 To: 收件人行、Subject: 主题和正文。

### 6.1 首次运行：逐步执行

激活环境、进入申请人工作目录后，按顺序逐条执行。每步检查终端及输出，成功后再运行下一步：

~~~bash
python step1_clean_wos.py
python step2_detect_university.py
python step3_filter_top_tiers.py
python step4_evaluate_phd_fit.py
python step5_generate_research_topics.py
python step6_generate_emails.py
python step7_polish_letters.py --input-dir Generated_Emails_PDF
~~~

第 7 步可先空跑，或只处理少量文件：

~~~bash
python step7_polish_letters.py --input-dir Generated_Emails_PDF --dry-run
python step7_polish_letters.py --input-dir Generated_Emails_PDF --limit 3
~~~

--dry-run 无需密钥，不调用 API，仅输出分配信息和提示词预览；不能验证前 6 步或 API 连通性。

### 6.2 Linux / WSL / 服务器：一键执行

~~~bash
bash run_pipeline.sh
~~~

后台运行，断开 SSH 后继续：

~~~bash
bash start.sh
~~~

start.sh 打印 PID 和日志名。用实际日志名替换示例：

~~~bash
tail -f pipeline_YYYYmmdd_HHMMSS.log
ps -p "$(cat pipeline.pid)"
~~~

### 6.3 断点续跑

~~~bash
bash run_rest.sh
bash run_rest.sh 5
~~~

第一条自动判断进度；第二条从第 5 步“研究方向生成”开始。起点可指定 1–7，或写 step1 至 step7。

第 2 步用 qs_match_progress.pkl，第 5 步用 step5_checkpoint.xlsx，第 6、7 步跳过已有输出。第 4 步中断后需要重新评估，续跑工具结合日志与 .pipeline_progress 判断完成情况。pickle 缓存只使用自己本轮生成的文件。

换申请人、WOS 数据、CV 或筛选规则时，创建新的工作目录。续跑不能验证资料属于哪一轮；不要带入旧检查点或同名邮件。旧编号版本的检查点名称和进度记录不作为本版的直接续跑依据。

## 7. Gmail API 配置：可选的后续发送准备

完成 1–7 步不需要 Gmail API。以下操作获取 Gmail OAuth 授权文件，供另行实现的发送程序使用。authorize_gmail.py 只授权、保存 token，不发送邮件。

Gmail OAuth 与 DeepSeek 密钥是两套独立配置。Gmail 登录密码、Google API key 或服务账号 JSON 都不能代替桌面应用 OAuth 客户端。

### 7.1 创建项目、启用 API

1. 登录 [Google Cloud Console](https://console.cloud.google.com/)，选择或新建项目，例如 phd-outreach-mail。
2. 进入 APIs & Services / API 和服务 → Library / 库，搜索 Gmail API。
3. 点击 Enable / 启用，确认当前选择的是上述项目。

### 7.2 配置 OAuth 同意屏幕

在 Google Auth platform 中配置，旧界面可能叫 OAuth consent screen：

1. Branding：填写应用名称、用户支持邮箱、开发者联系邮箱。
2. Audience：个人 Gmail 通常选 External；只有符合条件的 Google Workspace 组织应用才能选 Internal。
3. 保持 Testing 时，在 Test users 中添加实际准备授权的 Gmail 账号。
4. Data Access：添加 https://www.googleapis.com/auth/gmail.send，允许代表用户发送邮件。

gmail.send 属于敏感权限。Testing 适用于自己或列出的测试用户；向其他用户公开使用时，需按 Google 要求处理发布状态和可能的应用验证。

### 7.3 创建桌面 OAuth 客户端并下载 JSON

1. 进入 Google Auth platform → Clients → Create client。
2. Application type 选择 Desktop app，填写名称后创建。
3. 下载该客户端 JSON，将本地文件命名为 credentials.json。
4. 放在仓库外，例如 E:\phd-outreach\gmail-private\sender-001\credentials.json。

Desktop app 配合本地回调。本工具不使用 Web application 类型，也不需要配置网站回调地址。文件顶层通常是 installed，不应是服务账号文件。

### 7.4 安装依赖、运行授权

在有浏览器的本地电脑授权最方便。激活环境，在源码目录安装可选依赖；主流程不需要这些包：

~~~bash
python -m pip install -r requirements-gmail.txt
~~~

Windows PowerShell：

~~~powershell
python authorize_gmail.py --credentials "E:\phd-outreach\gmail-private\sender-001\credentials.json" --token "E:\phd-outreach\gmail-private\sender-001\token.json"
~~~

WSL：

~~~bash
python authorize_gmail.py --credentials "/mnt/e/phd-outreach/gmail-private/sender-001/credentials.json" --token "/mnt/e/phd-outreach/gmail-private/sender-001/token.json"
~~~

默认使用本机 127.0.0.1:8765 回调并打开浏览器。登录实际发信的 Gmail 账号，核对应用名称和权限后同意。若未自动打开浏览器，加 --no-browser，再在同一台电脑上打开终端打印的链接。

端口被占用时加 --port 8766。完成同意后，浏览器跳回本机回调，终端提示 token.json 已保存。不要公开完整授权链接或凭据 JSON。

### 7.5 两个 JSON 文件的区别

| 文件 | 来源 | 内容 | 上传 GitHub |
| --- | --- | --- | --- |
| credentials.json | Google Cloud 下载 | OAuth 客户端 ID 和配置 | 否 |
| token.json | 用户同意后生成 | Access token、refresh token、权限和过期信息 | 否 |

每个发信账号使用独立目录和 token。申请人工作目录与发信账号不一定一一对应，由后续发送程序明确选择。

重跑工具会尝试复用有效 token，或刷新过期 access token；refresh token 失效时重新打开授权。External + Testing 项目请求 Gmail 权限时，refresh token 通常在 7 天后失效，不一定是首次配置出错。

更换 OAuth 客户端、账号或权限时，先将旧 token.json 移到备份位置，再重新授权。不要把不同项目的 credentials.json 与 token.json 混用。

### 7.6 在服务器使用

推荐在本地完成授权，再通过 SSH/SCP 将对应的两个 JSON 传到服务器私有目录：

~~~text
/home/your-user/.config/phd-outreach/gmail/sender-001/
├── credentials.json
└── token.json
~~~

Linux 文件权限建议仅当前用户可读写：

~~~bash
chmod 700 "/home/your-user/.config/phd-outreach/gmail/sender-001"
chmod 600 "/home/your-user/.config/phd-outreach/gmail/sender-001/credentials.json"
chmod 600 "/home/your-user/.config/phd-outreach/gmail/sender-001/token.json"
~~~

必须在无浏览器服务器授权时，从本地建立 SSH 转发：

~~~bash
ssh -L 8765:127.0.0.1:8765 your-user@your-server
~~~

保持连接，在远程终端运行工具并加 --no-browser --port 8765，再用本地浏览器打开打印的链接。localhost 回调通过隧道到达服务器；不要在另一台电脑打开链接却不做端口转发。

### 7.7 后续发送程序需要接什么

发送程序需读取私有 token.json、按需刷新授权，调用 Gmail API 的 users.messages.send（userId 为 me），并将人工审核的收件人、主题和正文组装成 MIME 邮件。

Generated_Emails_PDF_polished/*.txt 是本项目提供的材料。主流程目前不读取 Gmail 凭据，没有自动发送开关；仅完成授权不会投递邮件。额度、速率和拒信情况按实际 Gmail / Workspace 账号规则处理。

官方参考：[Python 快速入门](https://developers.google.com/workspace/gmail/api/quickstart/python)、[OAuth 同意屏幕](https://developers.google.com/workspace/guides/configure-oauth-consent)、[Gmail 权限列表](https://developers.google.com/workspace/gmail/api/auth/scopes)、[OAuth token 失效规则](https://developers.google.com/identity/protocols/oauth2#expiration)。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 CV / 多个 PDF | 将一份文字版 CV.pdf 放在实际脚本目录，移走无关 PDF |
| 找不到 Excel / 格式不支持 | 确认是真正的 .xls / .xlsx，未放在子目录；旧 .xls 需要 xlrd |
| KeyError: DOI 等列名 | 检查 WOS 表头、导出字段与第一行，避免简略题录 |
| 第 1 步没有通讯作者记录 | 检查 Reprint Addresses 的通讯作者内容和标记 |
| QS 缺列 | 第一张表需有 Rank、University、Country/Territory |
| API 401 / 403 / 404 | 分别检查密钥、账户权限或余额、模型名称及接口地址 |
| 关终端后任务停止 | Linux / WSL 使用 bash start.sh，查看打印的日志 |
| Gmail access_denied / 403 | 检查测试账号、Gmail API 启用情况、Workspace 管理策略和具体错误 |
| Gmail redirect_uri_mismatch | 确认使用 Desktop app OAuth 客户端，重新下载配置 |
| Gmail invalid_grant | Token 可能过期或被撤销，移走旧 token 后重新授权 |
| Gmail 回调失败 | 保持授权脚本运行，远程需转发相同端口 |

发送前人工核对姓名、邮箱、论文细节、研究建议和资助状态。某些步骤在 API 失败时会跳过记录，退出并不代表每条记录都成功，应结合日志检查完整性。

## 9. 验证与上传 GitHub

在干净源码目录运行离线检查，不需要真实 CV、API 密钥或 Gmail 账号：

~~~bash
python -m unittest discover -s tests -v
bash -n start.sh run_pipeline.sh run_rest.sh
python authorize_gmail.py --help
~~~

运行主流程时会将论文信息、联系方式、CV 或草稿发给 DeepSeek，具体取决于步骤。离线测试不会调用服务，也不能证明模型可用或整条业务流程通过。

~~~bash
git init
git add .
git diff --cached --stat
git diff --cached
git status --short
~~~

确认后再提交推送。Git 忽略规则不会保护被强制添加或网页拖入的文件。已泄露的密钥需在服务商后台撤销；删除当前文件不会删除 Git 历史。项目未指定开源许可证。
