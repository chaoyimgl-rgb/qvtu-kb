# qvtu-kb

> 泉州职业技术大学课表导出工具 · **单文件独立版**
>
> 输入一次账号密码，自动拉取全学期课表，产出 **带登录态的课表直达链接**、
> **Excel 明细表**、**日历 ICS**、**WakeUp 课程表导入 CSV**。

纯 HTTP 实现（`requests`），不依赖学习通客户端、不需要抓包、不需要浏览器自动化。
所有导出逻辑内嵌在同一文件里，拷走 `qvtu_kb.py` 即可运行。

---

## ⚠️ 使用须知（务必先读）

- 本工具**仅供导出你自己账号的课表**，请勿用于批量采集、他人账号或任何未授权用途。
- 请求为低频（逐周间隔 0.25s），请勿去掉限速或高频重跑。
- `课表链接.txt` 里的直达链接**等同于登录态**（等于密码），请勿分享；有效期约 4 小时，过期重跑即可。
- 使用本工具产生的任何后果由使用者自行承担，请遵守学校信息系统管理规定。

---

## ✨ 两种登录方式

| 模式 | 账号 | 密码 | 说明 |
| --- | --- | --- | --- |
| `jw`（默认，推荐） | 学号 | **教务系统密码** | 直连教务 `/login`，不经过超星；密码按前端算法 AES 加密 |
| `hall` | 超星账号（手机号） | 超星密码 | 超星 hall 门户 → 应用中心 → 免登跳转；**该链路能拿到带登录态的直达链接** |

两种模式最终都得到同一个 sjd 会话 token，后续拉课表逻辑完全一致。

> 教务自有登录的密码加密（前端复刻）：
> `pwd = base64( base64( AES-ECB( JSON.stringify(密码), key="qzkj1kjghd=876&*" ) ) )`

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- 依赖：`requests`、`urllib3`、`pycryptodome`（仅 `jw` 模式需要）

```bash
pip install -r requirements.txt
```

### 方式一：一键脚本（Windows）

右键运行 `run_kb.ps1`，选择登录方式后按提示输入账号密码（密码不回显、仅存内存）。

### 方式二：命令行

```bash
# 教务自有登录（默认）
python qvtu_kb.py

# 超星 hall 免登链路
python qvtu_kb.py --mode hall
```

免交互（环境变量）：

```powershell
# jw 模式
$env:QVTU_JW_USER='学号'; $env:QVTU_JW_PASS='教务密码'; python qvtu_kb.py

# hall 模式
$env:QVTU_USER='手机号'; $env:QVTU_PASS='超星密码'; python qvtu_kb.py --mode hall
```

---

## 📦 产出说明

| 文件 | 说明 |
| --- | --- |
| `课表链接.txt` | 带登录态的课表直达链接（hall 模式必有；jw 模式同样生成），打开即看，无需登录 |
| `课表_<学期>.csv` | 逐周明细：周次 / 星期 / 日期 / 时间 / 课程 / 教师 / 教室 / 班级 / 考核方式 |
| `课表_<学期>.ics` | 日历文件，每节课一个事件（天然适配调课、换教室、单双周），含 20 分钟提前提醒 |
| `课表_<学期>_wakeup.csv` | WakeUp 导入（合并版：同课换教室自动归并，地点取主教室） |
| `课表_<学期>_wakeup_明细.csv` | WakeUp 导入（明细版：保留每周实际教室） |
| `kb_weeks.json` | 中间缓存（课表原始响应 + 学期锚点），可随时删除 |

WakeUp 的 CSV 只描述"第几节"，具体钟点需在 App 内 `课表设置 → 上课时间` 按学校节次表设置：

```
第1节 08:10   第3节 10:10   第5节 14:10   第7节 16:10   第9节 19:10
```

---

## 🔧 工作原理

```
【jw 模式】
  POST /bzb_njwhd/login
       pwd = base64(base64(AES-ECB(JSON.stringify(密码))))   # 前端硬编码密钥
       → data.token（会话 JWT）

【hall 模式】
  POST https://qvtu.hall.chaoxing.com/login                  # 学号/手机号 + 密码
   → GET /toAppCenter                                        # 找教务入口 redirectUrl(...)
   → GET /transform/redirectUrl?...                          # 超星 OAuth，跟随 302
   → jw.qvtu.edu.cn/bzb_njwhd/loginQzzy?...                   # 教务免登票据
   → jw.qvtu.edu.cn/sjd//#/casLogin?token=<JWT>               # ← 这就是「直达链接」
                                                              #   SPA 自动签收 token 写入 sessionStorage

【共同后续】
  POST /bzb_njwhd/Get_sjkbms                                  # 节次模式 ID
  POST /bzb_njwhd/student/curriculum?week=N&kbjcmsid=...      # 逐周拉取（token 走请求头）
  → 合并 → CSV / ICS / WakeUp CSV
```

要点：

- 课表接口按周返回，脚本按 `teachingWeek` 的周数逐周拉取后合并；
- 学期锚点（第 1 周周一）取自当前周响应的 `topInfo`，不靠本地猜测；
- WakeUp CSV 中单一区间会被 WPS/Excel 误认成日期（`6-18` → `2026/6/18`），
  脚本已自动改写为等价多段写法（`6、7-18`），详见 [docs/wakeup-csv.md](docs/wakeup-csv.md)。

---

## ⚙️ 适配其他学校

脚本顶部集中了学校相关常量，同属「超星 hall + 强智 sjd」体系的学校一般只需改这三行：

```python
HALL = "https://qvtu.hall.chaoxing.com"   # hall 门户域名（jw 模式用不到）
JW   = "https://jw.qvtu.edu.cn"           # 教务系统域名
API  = JW + "/bzb_njwhd"                  # 强智 sjd 接口前缀
```

学校代码（`xxid`）与节次模式 ID（`kbjcmsid`）会自动从
`/sjd/serverconfig.json`、`/Get_sjkbms` 获取，无需手改。

---

## ❓ 常见问题

**Q：`jw` 模式提示"该帐号不存在或密码错误！"？**
教务密码与超星密码通常**不是同一个**，请填教务系统登录用的密码；账号填学号。

**Q：`jw` 模式提示需要验证码？**
脚本会保存 `验证码.png` 并在终端提示输入，输入后自动重试。

**Q：`hall` 模式提示"被踢回登录页"？**
超星账号密码错误，或超星触发了风控验证码，稍后再试。

**Q：直达链接多久失效？**
服务端签发 JWT 有效期 4 小时，过期重跑脚本即可。

**Q：CSV 写不进去 / 周数变成日期？**
CSV 被 Excel/WPS 占用时请关闭后重跑；周数问题见
[docs/wakeup-csv.md](docs/wakeup-csv.md)（脚本已自动规避）。

---

## 📁 项目结构

```
qvtu-kb/
├── qvtu_kb.py            # 全部逻辑：双模式登录 + 拉取 + CSV/ICS/WakeUp 导出 + 直达链接
├── run_kb.ps1            # Windows 一键入口（登录方式选择 + 密码隐藏输入）
├── requirements.txt
├── docs/
│   └── wakeup-csv.md     # WakeUp CSV 格式说明与 Excel 日期陷阱
├── LICENSE
└── README.md
```

运行产物（`kb_weeks.json`、`课表_*`、`课表链接.txt`）已在 `.gitignore` 中排除，不会误提交。

---

## 📄 License

[MIT](LICENSE)
