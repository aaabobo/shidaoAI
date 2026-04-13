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
from PIL import Image, ImageOps

# ===================== 配置文件 =====================
CONFIG_FILE = "seedance_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "gen_url": "", "query_url": ""}

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
.stTextArea>div>div { min-height:120px; }
.stButton>button { height:2.8em; font-weight:bold; }
/* 核心样式：固定图片容器高度，统一显示为缩略图 */
.img-thumbnail-container {
    width: 100%;
    height: 180px; /* 固定高度，确保所有图一样大 */
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: 8px;
    background-color: #f0f2f6;
}
.img-thumbnail-container img {
    width: 100%;
    height: 100%;
    object-fit: cover; /* 保持比例填充，不拉伸 */
}
.at-button {
    margin-top: 5px;
    width: 100%;
}
</style>
""", unsafe_allow_html=True)

# ===================== 状态初始化 =====================
if "tasks" not in st.session_state:
    st.session_state.tasks = {}
if "prompt_text" not in st.session_state:
    st.session_state.prompt_text = ""
# 用于存储上传文件的原始对象，以便后续转Base64
if "uploaded_files_raw" not in st.session_state:
    st.session_state.uploaded_files_raw = []

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
    img_file.seek(0)
    b64 = base64.b64encode(img_file.read()).decode()
    ext = img_file.name.split('.')[-1].lower()
    return f"data:image/{ext};base64,{b64}"

def insert_at_tag(tag_num):
    """在提示词当前光标位置插入@标签"""
    # Streamlit 不支持直接获取光标位置，这里使用简单的追加策略
    # 如果想更精准，可以使用 st.experimental_set_block 配合 js，但为了稳定这里用简单拼接
    st.session_state.prompt_text += f" @{tag_num}"
    st.rerun() # 刷新以显示插入后的文本

# ===================== 后台生成 =====================
def bg_task(task_id, prompt, img_b64_list, ratio, duration, model):
    task = st.session_state.tasks[task_id]
    config = load_config()
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
            img_b64_list = [i for i in img_b64_list if i]
            if len(img_b64_list) == 1:
                payload["image_url"] = img_b64_list[0]
            else:
                payload["images"] = img_b64_list

        res = requests.post(gen_url, headers=headers, json=payload, timeout=30).json()
        if res.get("code") != 0:
            task["status"] = "提交失败"
            task["error"] = res.get("msg", str(res))
            return

        req_id = res["data"]["requestId"]
        task["req_id"] = req_id
        task["status"] = "生成中"

        for _ in range(120):
            time.sleep(2)
            qres = requests.get(query_url, params={"requestId": req_id}, headers=headers, timeout=15).json()
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
        task["error"] = f"请求异常：{str(e)}"

    try:
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
    except:
        pass

# ===================== 界面布局 =====================
st.title("🎬 石导SeedanceAI视频生成工具")

# 左：上传 + 提示词 | 右：API设置
col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("📸 参考图（统一缩略图尺寸）")
    # 接受多图上传
    uploaded_files = st.file_uploader(
        "选择图片",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )
    
    # 同步更新原始文件列表
    if uploaded_files != st.session_state.uploaded_files_raw:
        st.session_state.uploaded_files_raw = uploaded_files
        # 如果上传了新图，清空提示词的@标签（避免序号混乱）
        # 这里可以不加，保持提示词不变，但序号可能对应错，建议提示用户重写
        st.info("已更新图片列表，提示词中的 @序号 请确认是否对应。")

    # 显示缩略图区域 - 核心修改部分
    if st.session_state.uploaded_files_raw:
        st.markdown("**点击图片下方按钮引用 @序号**")
        # 使用列布局展示缩略图，根据图片数量自适应
        num_imgs = len(st.session_state.uploaded_files_raw)
        cols = st.columns(min(num_imgs, 6)) # 最多一行显示6个，超过会换行，保持整齐
        
        for i, file_obj in enumerate(st.session_state.uploaded_files_raw):
            with cols[i % 6]: # 取模实现换行
                # 显示统一尺寸的缩略图
                # 这里用 div 包裹强制样式，绕过 st.image 的自适应限制
                st.markdown(f"""
                    <div class="img-thumbnail-container">
                        <img src="data:image/{file_obj.type.split('/')[1]};base64,{base64.b64encode(file_obj.getvalue()).decode()}" 
                             alt="图{i+1}">
                    </div>
                """, unsafe_allow_html=True)
                # 引用按钮
                st.button(f"@ {i+1}", key=f"btn_{i}", on_click=insert_at_tag, args=(i+1,), type="secondary")

    st.subheader("✍️ 提示词")
    prompt = st.text_area(
        "提示词",
        value=st.session_state.prompt_text,
        height=120,
        label_visibility="collapsed",
        key="prompt_text"
    )

with col_right:
    st.subheader("⚙️ API设置")
    api_key = st.text_input("API Key", value=config["api_key"], type="password")
    gen_url = st.text_input("生成接口", value=config["gen_url"])
    query_url = st.text_input("查询接口", value=config["query_url"])

    if st.button("💾 保存配置", use_container_width=True):
        save_config(api_key, gen_url, query_url)
        config = load_config()
        st.success("已保存！")

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
st.markdown("<br>", unsafe_allow_html=True) # 增加一点间距
if st.button("🚀 立即生成", type="primary", use_container_width=True):
    if not api_key or not gen_url or not query_url:
        st.error("请先填写并保存API配置")
    elif not prompt.strip():
        st.warning("请输入提示词")
    else:
        # 转换图片为Base64
        b64_list = [img_to_base64(f) for f in st.session_state.uploaded_files_raw] if st.session_state.uploaded_files_raw else []

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
        st.success("任务已启动 ↓ 查看历史")

# ===================== 任务历史 =====================
st.divider()
st.subheader("📋 任务历史")
if st.button("🔄 刷新状态", use_container_width=True):
    st.rerun()

tasks = st.session_state.tasks
if not tasks:
    st.info("暂无任务")
else:
    total_cost = sum(t.get("cost", 0) for t in tasks.values())
    for tid in sorted(tasks.keys(), reverse=True):
        t = tasks[tid]
        expanded = t["status"] in ["排队中", "提交中", "生成中"]
        with st.expander(f"[{t['create_time']}] ｜ {t['duration']}s ｜ {t['status']}", expanded=expanded):
            st.caption(f"Task ID: {tid}")
            st.write(f"**提示词**: {t['prompt']}")
            st.write(f"**比例**: {t['ratio']} | **时长**: {t['duration']}s")
            if t.get("error"):
                st.error(f"❌ 错误: {t['error']}")
            if t.get("video_url"):
                st.video(t["video_url"])
            if t.get("cost") and t["cost"] > 0:
                st.info(f"💰 花费: {t['cost']} 元")

    st.divider()
    st.metric("累计花费", f"{total_cost:.2f} 元")