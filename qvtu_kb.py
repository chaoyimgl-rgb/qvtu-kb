# -*- coding: utf-8 -*-
"""
qvtu-kb —— 泉州职业技术大学 教务课表导出工具（单文件独立版）

两种登录方式，任选其一：
  A. 教务自有登录（直连，推荐）
       账号 = 学号，密码 = 教务系统密码
       POST /bzb_njwhd/login  pwd = base64(base64(AES-ECB(JSON.stringify(密码))))
  B. 超星 hall 免登链路
       账号 = 超星账号（手机号），密码 = 超星密码
       hall 登录 → 应用中心 → transform/redirectUrl → casLogin（该 URL 即"带登录态的直达链接"）

产出（全部内嵌，无外部脚本依赖）：
  课表链接.txt                 带登录态的课表直达链接（B 模式必有；A 模式按需生成）
  课表_<学期>.csv              逐周明细
  课表_<学期>.ics              日历（每节课一个事件，含 20 分钟提醒）
  课表_<学期>_wakeup.csv       WakeUp 课程表导入（合并版）
  课表_<学期>_wakeup_明细.csv  WakeUp 导入（明细版，保留每周实际教室）

用法：
  python qvtu_kb.py                 # 交互输入（默认先试教务登录）
  python qvtu_kb.py --mode jw       # 强制教务自有登录
  python qvtu_kb.py --mode hall     # 强制超星 hall 链路

环境变量（免交互）：
  QVTU_JW_USER / QVTU_JW_PASS      教务账号 / 密码
  QVTU_USER    / QVTU_PASS         超星账号 / 密码
"""
import base64
import csv
import datetime as dt
import getpass
import json
import os
import re
import sys
import time

import requests
import urllib3

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings()

# ============================== 配置区 ==============================
HALL = "https://qvtu.hall.chaoxing.com"     # 学校 hall 门户（B 模式用）
JW = "https://jw.qvtu.edu.cn"               # 教务系统
API = JW + "/bzb_njwhd"                     # 强智 sjd 接口前缀
AES_KEY = b"qzkj1kjghd=876&*"               # 前端硬编码密钥（教务登录密码加密）
KBM_FALLBACK = "960B231E38697ADCE053A578A8C0F3C2"
HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36")
# ===================================================================


def mask(s: str) -> str:
    if not s:
        return "<空>"
    return s[:3] + "*" * max(0, len(s) - 7) + s[-4:] if len(s) > 8 else "***"


# ---------------------------------------------------------------- 登录：A 教务自有
def jw_encrypt(text: str) -> str:
    """复刻前端 window.btoa(Uw.encrypt(text))：JSON.stringify -> AES-ECB/PKCS7 -> base64 -> btoa"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    inner = base64.b64encode(
        AES.new(AES_KEY, AES.MODE_ECB).encrypt(pad(json.dumps(text).encode(), 16))
    ).decode()
    return base64.b64encode(inner.encode()).decode()


def login_jw(user: str, pwd: str):
    """教务自有登录 -> (token, userType, 直达链接)"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Origin": JW, "Referer": JW + "/sjd/"})
    data = {"userNo": user, "pwd": jw_encrypt(pwd), "encode": "1",
            "captchaData": "", "codeVal": ""}
    r = s.post(API + "/login", data=data, timeout=20, verify=False)
    j = r.json()
    if str(j.get("code")) == "1" and isinstance(j.get("data"), dict) and j["data"].get("token"):
        d = j["data"]
        print(f"[jw] 登录成功 (账号 {mask(user)}, 身份 {d.get('userType')})")
        link = (f"{JW}/sjd//#/casLogin?token={d['token']}"
                f"&userType={d.get('userType', 2)}&thirdLogin=oauth2")
        return d["token"], str(d.get("userType", "2")), link
    msg = j.get("Msg") or j.get("msg") or ""
    if "验证码" in msg:
        print(f"[jw] 需要验证码：{msg}")
        try:
            img = s.post(API + "/getVerifyImg", data={}, timeout=15, verify=False).json()
            data_url = img.get("data", "")
            if data_url.startswith("data:image"):
                p = os.path.join(HERE, "验证码.png")
                open(p, "wb").write(base64.b64decode(data_url.split(",", 1)[1]))
                print(f"[jw] 验证码已保存: {p}")
                data["codeVal"] = input("请输入验证码: ").strip()
                data["captchaData"] = img.get("captchaData") or img.get("data2") or ""
                j = s.post(API + "/login", data=data, timeout=20, verify=False).json()
                if str(j.get("code")) == "1":
                    d = j["data"]
                    print("[jw] 验证码校验通过，登录成功")
                    return (d["token"], str(d.get("userType", "2")),
                            f"{JW}/sjd//#/casLogin?token={d['token']}&userType={d.get('userType',2)}&thirdLogin=oauth2")
        except Exception as e:
            print("[jw] 验证码流程异常:", repr(e)[:80])
    print(f"[jw] 登录失败: {msg or '未知原因'}")
    return None, None, None


# ---------------------------------------------------------------- 登录：B 超星 hall
def login_hall(user: str, pwd: str):
    """超星 hall 免登链路 -> (token, casLogin 直达链接)"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Origin": HALL, "Referer": HALL + "/login",
                      "Accept-Language": "zh-CN,zh;q=0.9"})
    s.post(HALL + "/login", data={"uname": user, "pwd": pwd},
           timeout=25, verify=False, allow_redirects=True)
    html = s.get(HALL + "/toAppCenter", timeout=20, verify=False)
    if "/login" in html.url or html.status_code != 200:
        print("[hall] 登录失败：被踢回登录页（账号密码错或需要验证码）")
        return None, None
    print(f"[hall] 登录成功 (账号 {mask(user)})")

    ent = None
    for m in re.finditer(r"redirectUrl\('([^']+)','(\d+)','([^']+)','([^']+)'\)", html.text):
        if "loginQzzy" in m.group(1) or "jw." in m.group(1) or "bzb" in m.group(1):
            ent = m.groups()
            break
    if not ent:
        print("[hall] 应用中心里未找到教务入口")
        return None, None

    base, mapp, appid, appkey = ent
    url = (HALL + f"/transform/redirectUrl?redirectUri={requests.utils.quote(base, safe='')}"
                  f"&mappId={mapp}&appId={appid}&appKey={appkey}")
    rr = s.get(url, timeout=25, verify=False, allow_redirects=True)
    locs = [str(h.headers.get("Location", "")) for h in rr.history]
    cas = next((l if l.startswith("http") else JW + l
                for l in locs + [rr.url] if "/casLogin?" in l and "token=" in l), None)
    tok = None
    for src in ([rr.url] + locs + [rr.text[:60000]]):
        m = re.search(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}", src)
        if m:
            tok = m.group(0)
            break
    if not tok:
        print("[hall] 跳转链未捡到 token")
        return None, None
    print(f"[hall] 拿到会话 token -> {mask(tok)}")
    return tok, cas


# ---------------------------------------------------------------- 会话与数据
def get_school_code() -> str:
    try:
        r = requests.get(JW + "/sjd/serverconfig.json", timeout=10, verify=False)
        return r.json().get("schoolCode") or "12928"
    except Exception:
        return "12928"


def sjd_session(token: str, user_type: str = "2"):
    """token 若已是会话 JWT 直接用；否则走 authUser 换取"""
    hdr = {"token": token, "User-Agent": UA, "Origin": JW, "Referer": JW + "/sjd/"}
    p = requests.post(API + "/currentTerm", headers=hdr, data={}, timeout=15, verify=False)
    try:
        if str(p.json().get("code")) == "1":
            print("[sjd] token 有效")
            return requests.Session(), hdr
    except Exception:
        pass
    r = requests.post(API + "/authUser",
                      headers={"User-Agent": UA, "Origin": JW, "Referer": JW + "/sjd/"},
                      data={"token": token, "xxid": get_school_code()},
                      timeout=15, verify=False)
    j = r.json()
    if str(j.get("code")) == "1" and isinstance(j.get("data"), dict) and j["data"].get("token"):
        print("[sjd] authUser 换取 JWT 成功")
        hdr["token"] = j["data"]["token"]
        return requests.Session(), hdr
    print("[sjd] 会话校验失败:", str(j)[:120])
    return None, None


def get_kbm(s) -> str:
    try:
        j = s.post(API + "/Get_sjkbms", data={}, timeout=15, verify=False).json()
        arr = j.get("data") or []
        if arr and arr[0].get("kbjcmsid"):
            return arr[0]["kbjcmsid"]
    except Exception:
        pass
    return KBM_FALLBACK


def fetch_semester(hdr):
    s = requests.Session()
    s.headers.update(hdr)
    kbm = get_kbm(s)
    cur = s.post(API + "/student/curriculum", params={"week": "", "kbjcmsid": kbm},
                 timeout=25, verify=False).json()
    if str(cur.get("code")) != "1":
        print("[kb] 当前周查询失败:", str(cur)[:150])
        return None
    d0 = cur["data"][0]
    top = d0.get("topInfo", [{}])[0]
    week_now = int(top.get("week") or 5)
    max_week = int(top.get("maxWeek") or 20)
    dates = {int(x["xqid"] or 7): x["mxrq"] for x in d0["date"] if x.get("mxrq")}
    first_monday = dt.date.fromisoformat(min(dates.values())) - dt.timedelta(weeks=week_now - 1)
    print(f"[kb] 学期 {top.get('semesterId')} 第{week_now}周 第1周周一={first_monday} 共{max_week}周")
    weeks = {}
    for w in range(1, max_week + 1):
        j = s.post(API + "/student/curriculum", params={"week": str(w), "kbjcmsid": kbm},
                   timeout=25, verify=False).json()
        if str(j.get("code")) == "1" and j.get("data"):
            n = len(j["data"][0].get("courses") or [])
            if n:
                weeks[str(w)] = j
                print(f"   week {w}: {n} 节")
        time.sleep(0.25)
    return {"first_monday": first_monday.isoformat(), "weeks": weeks,
            "semester": top.get("semesterId", "")}


# ---------------------------------------------------------------- 导出
def build_rows(cache):
    FIRST = dt.date.fromisoformat(cache["first_monday"])
    DOW = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 0: 6}
    rows = []
    for w, j in cache["weeks"].items():
        for c in (j["data"][0].get("courses") or []):
            wd = int(c.get("weekDay") or 0)
            day = FIRST + dt.timedelta(days=(int(w) - 1) * 7 + DOW.get(wd, 0))
            rows.append({"week": int(w), "wd": wd, "date": day.isoformat(), **c})
    rows.sort(key=lambda r: (r["date"], r.get("startTime") or ""))
    return rows


def export_csv(rows, sem):
    WD = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 0: "周日"}
    path = os.path.join(HERE, f"课表_{sem}.csv")
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["周次", "星期", "日期", "时间", "课程", "教师", "教室", "教学楼", "班级", "考核"])
            for r in rows:
                wr.writerow([r["week"], WD.get(r["wd"], ""), r["date"],
                             f'{r.get("startTime","")}-{r.get("endTIme") or r.get("endTime","")}',
                             r.get("courseName", ""), r.get("teacherName", ""),
                             r.get("location", ""), r.get("buildingName", ""),
                             r.get("ktmc", ""), r.get("khfs", "")])
        print("CSV ->", path)
    except PermissionError:
        print("!! CSV 被占用（关掉 Excel/WPS 后重跑）:", path)


def export_ics(rows, sem):
    def esc(t):
        return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN",
           "PRODID:-//qvtu-kb//CN", f"X-WR-CALNAME:{esc(sem)} 课表"]
    seen = set()
    for r in rows:
        st = (r.get("startTime") or "").replace(":", "")
        et = ((r.get("endTIme") or r.get("endTime") or "")).replace(":", "")
        if not st:
            continue
        uid = f'{r.get("jx0404id")}-{r["date"]}-{st}'
        if uid in seen:
            continue
        seen.add(uid)
        desc = "{} 第{}周".format(r.get("teacherName", ""), r["week"])
        ics += ["BEGIN:VEVENT", f"UID:{uid}",
                f"DTSTAMP:{dt.datetime.now():%Y%m%dT%H%M%S}Z",
                f'SUMMARY:{esc(r.get("courseName",""))}',
                f'DTSTART:{r["date"].replace("-","")}T{st}00',
                f'DTEND:{r["date"].replace("-","")}T{et}00',
                f'LOCATION:{esc(r.get("location",""))}',
                f"DESCRIPTION:{esc(desc)}",
                "BEGIN:VALARM", "TRIGGER:-PT20M", "ACTION:DISPLAY",
                "DESCRIPTION:20分钟后上课", "END:VALARM", "END:VEVENT"]
    ics.append("END:VCALENDAR")
    path = os.path.join(HERE, f"课表_{sem}.ics")
    open(path, "w", encoding="utf-8", newline="\r\n").write("\n".join(ics))
    print(f"ICS -> {path} ({len(seen)} events)")


def anti_excel(s: str) -> str:
    """裸 'a-b' 会被 WPS/Excel 当日期(6-18→2026/6/18)，等价改写为含顿号的多段写法"""
    m = re.fullmatch(r"(\d+)-(\d+)", s.strip())
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b - a >= 2:
            return f"{a}、{a + 1}-{b}"
        if b - a == 1:
            return f"{a}、{b}"
    return s


def compress_weeks(weeks):
    ws = sorted(set(int(w) for w in weeks))
    if not ws:
        return ""
    out, i = [], 0
    while i < len(ws):
        if i + 1 < len(ws):
            step = ws[i + 1] - ws[i]
            if step in (1, 2):
                j = i + 1
                while j + 1 < len(ws) and ws[j + 1] - ws[j] == step:
                    j += 1
                run = ws[i:j + 1]
                if len(run) >= 2:
                    if step == 1:
                        out.append(f"{run[0]}-{run[-1]}" if len(run) > 2 else f"{run[0]}、{run[1]}")
                    else:
                        out.append(f"{run[0]}-{run[-1]}{'单' if run[0] % 2 else '双'}")
                    i = j + 1
                    continue
        out.append(str(ws[i]))
        i += 1
    return anti_excel("、".join(out))


def export_wakeup(cache, sem):
    """WakeUp 课程表导入 CSV：合并版 + 明细版"""
    groups = {}
    for w, j in cache["weeks"].items():
        for c in (j["data"][0].get("courses") or []):
            wd = int(c.get("weekDay") or 0) or 7
            notes = [int(x) for x in c.get("weekNoteDetail", "").split(",") if x.strip().isdigit()]
            if not notes:
                continue
            s0, s1 = min(notes) % 100, max(notes) % 100
            key = (c.get("courseName", ""), wd, s0, s1,
                   c.get("teacherName", ""), c.get("location", ""))
            groups.setdefault(key, set()).add(int(w))

    merged = {}
    for (name, wd, s0, s1, teacher, loc), weeks in groups.items():
        mk = (name, wd, s0, s1, teacher)
        m = merged.setdefault(mk, {"weeks": set(), "rooms": {}})
        m["weeks"] |= weeks
        m["rooms"][loc or "无"] = m["rooms"].get(loc or "无", 0) + len(weeks)

    FIELDS = ["课程名称", "星期", "开始节数", "结束节数", "老师", "地点", "周数"]
    outputs = []

    def dump(fname, rows):
        path = os.path.join(HERE, fname)
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                wr = csv.DictWriter(f, fieldnames=FIELDS)
                wr.writeheader()
                wr.writerows(rows)
        except PermissionError:
            stem, ext = os.path.splitext(fname)
            path = os.path.join(HERE, f"{stem}_v2{ext}")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                wr = csv.DictWriter(f, fieldnames=FIELDS)
                wr.writeheader()
                wr.writerows(rows)
        outputs.append((path, len(rows)))

    # 合并版
    rows = []
    for (name, wd, s0, s1, teacher), m in merged.items():
        rows.append({"课程名称": name, "星期": wd, "开始节数": s0, "结束节数": s1,
                     "老师": teacher or "无",
                     "地点": max(m["rooms"].items(), key=lambda kv: kv[1])[0],
                     "周数": compress_weeks(m["weeks"])})
    rows.sort(key=lambda r: (r["星期"], r["开始节数"], r["课程名称"]))
    dump(f"课表_{sem}_wakeup.csv", rows)

    # 明细版
    rows = []
    for (name, wd, s0, s1, teacher, loc), weeks in groups.items():
        rows.append({"课程名称": name, "星期": wd, "开始节数": s0, "结束节数": s1,
                     "老师": teacher or "无", "地点": loc or "无",
                     "周数": compress_weeks(weeks)})
    rows.sort(key=lambda r: (r["星期"], r["开始节数"], r["课程名称"]))
    dump(f"课表_{sem}_wakeup_明细.csv", rows)

    for p, n in outputs:
        print(f"WakeUp CSV -> {os.path.basename(p)} ({n} 行)")


# ---------------------------------------------------------------- 主流程
def save_link(link, token):
    if not link:
        return
    exp = None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = dt.datetime.fromtimestamp(
            json.loads(base64.urlsafe_b64decode(payload))["exp"] / 1000)
    except Exception:
        pass
    print("\n" + "=" * 62)
    print("[课表直达链接] 任意浏览器/手机打开即看课表，无需登录")
    if exp:
        print(f"  有效期: {exp:%Y-%m-%d %H:%M}（约4小时）")
    print(f"  {link}")
    print("  ⚠ 链接等于登录态，请勿外传；过期后重跑本脚本即可")
    print("=" * 62)
    try:
        with open(os.path.join(HERE, "课表链接.txt"), "w", encoding="utf-8") as f:
            head = f"（{exp:%Y-%m-%d %H:%M} 前有效，勿外传）" if exp else ""
            f.write(f"课表直达链接{head}\n{link}\n")
        print("  已保存 -> 课表链接.txt")
    except Exception:
        pass


def ask(mode):
    """按模式取凭据"""
    if mode == "hall":
        u = os.environ.get("QVTU_USER") or input("超星账号(手机号): ").strip()
        p = os.environ.get("QVTU_PASS") or getpass.getpass("超星密码(不回显): ")
        return u, p
    u = os.environ.get("QVTU_JW_USER") or input("教务账号(学号): ").strip()
    p = os.environ.get("QVTU_JW_PASS") or getpass.getpass("教务密码(不回显): ")
    return u, p


def main():
    args = sys.argv[1:]
    mode = "jw"
    if "--mode" in args:
        mode = args[args.index("--mode") + 1]
    elif "--hall" in args:
        mode = "hall"
    elif "--jw" in args:
        mode = "jw"

    print(f"[mode] {mode}（{'教务自有登录' if mode == 'jw' else '超星 hall 免登链路'}）")
    if mode == "jw":
        try:
            import Crypto  # noqa: F401
        except ImportError:
            sys.exit("教务直登需要 pycryptodome：pip install pycryptodome")
        user, pwd = ask("jw")
        token, utype, link = login_jw(user, pwd)
    else:
        user, pwd = ask("hall")
        token, link = login_hall(user, pwd)
        utype = "2"
    if not token:
        sys.exit(1)

    sess, hdr = sjd_session(token, utype)
    if not hdr:
        sys.exit(2)

    sem = fetch_semester(hdr)
    if not sem:
        sys.exit(3)
    total = sum(len(v["data"][0].get("courses") or []) for v in sem["weeks"].values())
    print(f"[kb] 合计 {total} 节实例")

    json.dump(sem, open(os.path.join(HERE, "kb_weeks.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    rows = build_rows(sem)
    export_csv(rows, sem["semester"])
    export_ics(rows, sem["semester"])
    export_wakeup(sem, sem["semester"])
    save_link(link, token)

    print(f"\n完成：课表_{sem['semester']}.csv / .ics / _wakeup.csv / _wakeup_明细.csv"
          "（凭据与 token 未写入任何文件）")


if __name__ == "__main__":
    main()
