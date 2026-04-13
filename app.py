import streamlit as st
import requests
import time
import csv
import os
import uuid
import base64
from datetime import datetime
from threading import Thread
import json

# ===================== 配置文件 =====================
CONFIG_FILE = "seedance_config.json"

# 加载配置
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "gen_url": "", "query_url": ""}

# 保存配置
def save_config(api_key, gen_url, query_url):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "api_key": api_key,
            "gen_url": gen_url,
            "query_url": query_url
        }, f, ensure_ascii=False, indent=2)

config = load_config()

# ===================== 页面设置 =====================
st.set_page_config(page_title="石导SeedanceAI", layout="wide")
st.markdown("""
<style>
.block-container { padding-top:1rem; padding-bottom:2rem; }
.stTextArea>div>div { min-height:100px; }
.stButton>button { height:3.2em; font-weight:bold; }
</style>
""", unsafe_allow_html=True)

# ===================== 状态初始化 =====================
if "tasks" not in st.session_state:
    st.session_state.tasks = {}

HISTORY_CSV = "seedance_history.csv"
if not os.path.exists(HISTORY_CSV):
    with open(HISTORY_CSV, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([
            "task_id", "create_time", "prompt", "ratio", "duration", "model",
            "status", "video_url", "cost", "error"
        ])

# ===================== 工具函数 =====================
def img_to_base64(img_file):
    if not img_file:
        return None
    b64 = base64.b64encode(img_file.read()).decode()
    return f"data:image/{img_file.type.split('/')[1]};base64,{b64}"

# ===================== 后台生成 =====================
def bg_task(task_id, prompt, img_b64_list, ratio, duration, model):
    task = st.session_state.tasks[task_id]
    api_key = config["api_key"]
    gen_url = config["gen_url"]
    query_url = config["query_url"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        task["status"] = "提交中"
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": ratio,
        }

        if img_b64_list:
            if len(img_b64_list) == 1:
                payload["image_url"] = img_b64_list[0]
            else:
                payload["images"] = img_b64_list

        res = requests.post(gen_url, headers=headers, json=payload).json()
        if res.get("code") != 0:
            task["status"] = "提交失败"
            task["error"] = res.get("msg", str(res))
            return

        req_id = res["data"]["requestId"]
        task["req_id"] = req_id
        task["status"] = "生成中"

        for _ in range(120):
            time.sleep(2)
            qres = requests.get(query_url, params={"requestId": req_id}, headers=headers).json()
            status = qres.get("data", {}).get("status")

            if status == "SUCCESS":
                task["status"] = "✅ 完成"
                task["video_url"] = qres["data"]["video_url"]
                task["cost"] = round(duration * 1.0, 2)
                break
            if status == "FAILED":
                task["status"] = "❌ 失败"
                task["error"] = qres["data"].get("error", "未知错误")
                break
        else:
            task["status"] = "⏱️ 超时"

    except Exception as e:
        task["status"] = "⚠️ 异常"
        task["error"] = str(e)

    with open(HISTORY_CSV, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([
            task_id,
            task["create_time"],
            task["prompt"],
            task["ratio"],
            task["duration"],
            task["model"],
            task["status"],
            task.get("video_url", ""),
            task.get("cost", 0),
            task.get("error", "")
        ])

# ===================== 界面布局 =====================
st.title("🎬 石导SeedanceAI视频生成工具")

# 左：上传 + 提示词 | 右：API设置
col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("📸 参考图（可多选）")
    uploaded_files = st.file_uploader(
        "选择图片",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    st.subheader("✍️ 提示词")
    prompt = st.text_area("提示词", height=100, label_visibility="collapsed")

with col_right:
    st.subheader("⚙️ API设置（保存后生效）")
    api_key = st.text_input("API Key", value=config["api_key"], type="password")
    gen_url = st.text_input("生成接口", value=config["gen_url"])
    query_url = st.text_input("查询接口", value=config["query_url"])

    if st.button("💾 保存配置"):
        save_config(api_key, gen_url, query_url)
        st.success("已保存！刷新后生效")

# 参数行
c1, c2, c3 = st.columns(3)
with c1:
    ratio = st.selectbox(
        "🖼️ 画面比例",
        ["9:16", "16:9", "4:3", "3:4", "1:1", "21:9"],
        index=0
    )
with c2:
    duration = st.selectbox(
        "⏱️ 时长(秒)",
        list(range(1, 16)),
        index=14
    )
with c3:
    model = st.selectbox(
        "🤖 模型版本",
        ["seedance-2.0", "seedance-2.0-fast"],
        index=0
    )

# 生成按钮
if st.button("🚀 立即生成（后台异步，可连续提交）", type="primary", use_container_width=True):
    if not api_key or not gen_url or not query_url:
        st.error("请先填写并保存API配置")
    elif not prompt:
        st.warning("请输入提示词")
    else:
        b64_list = [img_to_base64(f) for f in uploaded_files] if uploaded_files else []

        task_id = str(uuid.uuid4())[:8]
        st.session_state.tasks[task_id] = {
            "create_time": datetime.now().strftime("%m-%d %H:%M"),
            "prompt": prompt,
            "ratio": ratio,
            "duration": duration,
            "model": model,
            "status": "排队中",
            "req_id": None,
            "video_url": None,
            "cost": 0,
            "error": None
        }

        Thread(target=bg_task, args=(task_id, prompt, b64_list, ratio, duration, model)).start()
        st.success("任务已加入后台 ↓ 查看进度")

# ===================== 任务历史 =====================
st.divider()
st.subheader("📋 任务历史 & 实时状态")

if st.button("🔄 刷新状态"):
    st.rerun()

tasks = st.session_state.tasks
if not tasks:
    st.info("暂无任务")
else:
    total_cost = sum(t.get("cost", 0) for t in tasks.values())
    for tid in sorted(tasks.keys(), reverse=True):
        t = tasks[tid]
        expanded = t["status"] in ["排队中", "提交中", "生成中"]
        with st.expander(f"[{t['create_time']}] {t['model']}｜{t['duration']}s｜{t['status']}", expanded=expanded):
            st.caption(f"任务ID：{tid}")
            st.write(f"**提示词**：{t['prompt']}")
            st.write(f"**比例**：{t['ratio']}　**时长**：{t['duration']}s")
            if t.get("cost"):
                st.success(f"费用：{t['cost']} 元")
            if t.get("error"):
                st.error(f"错误：{t['error']}")
            if t.get("video_url"):
                st.video(t["video_url"])

    st.divider()
    st.metric("累计花费", f"{total_cost:.2f} 元")