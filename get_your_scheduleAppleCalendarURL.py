"""
GDUT Class Schedule Fetcher (GitHub Actions 专用版)
用于全自动爬取课表并生成 .ics 文件，供 Apple Calendar 订阅。
"""

import html
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import sys
import os
import concurrent.futures
from datetime import datetime
from zoneinfo import ZoneInfo
from ics import Calendar, Event

# 尝试导入自动登录模块
try:
    from gdut_login import login as auto_login
except ImportError:
    print("[-] Error: gdut_login.py not found.")
    sys.exit(1)

# 常量设置
ENTIRE_SEMESTER_WEEKS = 20
CLASS_TIMES = {
    "01": ("08:30", "09:15"), "02": ("09:20", "10:05"),
    "03": ("10:25", "11:10"), "04": ("11:15", "12:00"),
    "05": ("13:50", "14:35"), "06": ("14:40", "15:25"),
    "07": ("15:30", "16:15"), "08": ("16:30", "17:15"),
    "09": ("17:20", "18:05"), "10": ("18:30", "19:15"),
    "11": ("19:20", "20:05"), "12": ("20:10", "20:55"),
}
CST_TZ = ZoneInfo("Asia/Shanghai")

def get_auto_semester_code() -> str:
    """根据日期自动推算学期代码"""
    now = datetime.now()
    month, year = now.month, now.year
    if month >= 8: return f"{year}01"
    elif month == 1: return f"{year - 1}01"
    else: return f"{year - 1}02"

def get_authenticated_session():
    """从环境变量读取凭据并登录"""
    username = os.environ.get("GDUT_USERNAME")
    password = os.environ.get("GDUT_PASSWORD")
    
    missing = []
    if not username: missing.append("GDUT_USERNAME")
    if not password: missing.append("GDUT_PASSWORD")
    
    if missing:
        print(f"[-] Error: The following environment variables are missing: {', '.join(missing)}")
        print("[!] Please check your GitHub Repository Secrets (NOT Variables).")
        sys.exit(1)

    print(f"[*] Attempting auto-login for user: {username[:4]}****")
    session = auto_login(username, password)
    if not session:
        print("[-] Error: Login failed.")
        sys.exit(1)
    return session

def fetch_week_data(session, semester_code, week):
    url = f"https://jxfw.gdut.edu.cn/xsgrkbcx!getKbRq.action?xnxqdm={semester_code}&zc={week}"
    headers = {"Referer": "https://jxfw.gdut.edu.cn/xsgrkbcx!xsjkbcx.action"}
    try:
        res = session.get(url, headers=headers, timeout=15)
        return res
    except Exception as e:
        print(f"[-] Error fetching week {week}: {e}")
        return None

def add_course_to_calendar(calendar, course, date_map):
    course_name = course.get("kcmc", "N/A").strip()
    teacher = course.get("teaxms", "N/A").strip()
    location = course.get("jxcdmc", "Online/TBD")
    day_of_week, periods = course.get("xq", "?"), course.get("jcdm", "")

    if day_of_week in date_map and len(periods) >= 2:
        event_date_str = date_map[day_of_week]
        start_p, end_p = periods[:2], periods[-2:]
        if start_p in CLASS_TIMES and end_p in CLASS_TIMES:
            start_dt = datetime.fromisoformat(f"{event_date_str} {CLASS_TIMES[start_p][0]}:00").replace(tzinfo=CST_TZ)
            end_dt = datetime.fromisoformat(f"{event_date_str} {CLASS_TIMES[end_p][1]}:00").replace(tzinfo=CST_TZ)
            e = Event()
            e.name = html.unescape(course_name)
            e.begin, e.end, e.location = start_dt, end_dt, location
            e.description = f"Teacher: {teacher}\nRemarks: {course.get('sknrjj', '')}"
            calendar.events.add(e)

def main():
    semester_code = get_auto_semester_code()
    print(f"[*] Target semester: {semester_code}")
    
    session = get_authenticated_session()
    
    # 重试策略
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))

    calendar = Calendar()
    print("[*] Fetching schedule data for 20 weeks...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_week_data, session, semester_code, week): week for week in range(1, ENTIRE_SEMESTER_WEEKS + 1)}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res and res.status_code == 200 and res.text.startswith("["):
                data = res.json()
                class_schedule, week_dates = data[0], data[1]
                date_map = {day["xqmc"]: day["rq"] for day in week_dates}
                for course in class_schedule:
                    add_course_to_calendar(calendar, course, date_map)

    # 生成一个难以猜测的文件名以增加安全性
    filename = "schedule_private_sync.ics"
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(calendar.serialize_iter())
    
    print(f"[+] Success! {filename} has been generated.")

if __name__ == "__main__":
    main()
