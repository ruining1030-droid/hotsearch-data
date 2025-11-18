from flask import Flask, request, jsonify
import pandas as pd
import re
import os
from io import BytesIO
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import time

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ===== GitHub 上传配置 =====

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "ruining1030-droid/hotsearch-data"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/"

# ===== 数据源文件 =====
platform_files = {
    "weibo":   "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/weibo_hotsearch.xlsx",
    "toutiao": "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/toutiao_hotsearch.xlsx",
    "baidu":   "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/baidu_hotsearch.xlsx",
}

# ===== Requests 会话（稳定下载）=====
def make_session():
    s = requests.Session()
    retry = Retry(total=5, connect=5, read=5, backoff_factor=0.5,
                  status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "Hotsearch-Agent"})
    return s

SESSION = make_session()

def fetch_excel(url):
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return pd.read_excel(BytesIO(r.content))

# ===== 读取全部或指定平台 =====
def load_data(platform):
    dfs = []
    if platform in platform_files:
        df = fetch_excel(platform_files[platform])
        df["平台"] = platform
        dfs.append(df)
    else:
        for p, url in platform_files.items():
            tmp = fetch_excel(url)
            tmp["平台"] = p
            dfs.append(tmp)

    return pd.concat(dfs, ignore_index=True)

# ===== 清洗热度 =====
def clean_hot_value(x):
    if pd.isna(x):
        return 0
    s = str(x)
    num = re.findall(r"[\d.]+", s)
    if not num:
        return 0
    value = float(num[0])
    if "万" in s:
        value *= 10000
    return value

# ===== 上传到 GitHub =====
def upload_to_github(file_path, file_name):
    with open(file_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "message": f"Upload {file_name}",
        "content": content
    }

    r = requests.put(GITHUB_API_URL + file_name, json=payload, headers=headers)

    if r.status_code == 201:
        return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{file_name}"
    else:
        raise Exception(f"上传失败：{r.json()}")



#分支一：分析


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json or {}
        platform = data.get("platform", "all")
        topic = data.get("topic", "")
        limit = int(data.get("limit", 10))
        time_period = data.get("time_period", "")

        df = load_data(platform)
        df["热度"] = df["热度"].apply(clean_hot_value)
        df = df[df["热度"] > 0]

        if topic:
            df = df[df["标题"].astype(str).str.contains(topic, case=False, na=False)]

        df = df.sort_values("热度", ascending=False).head(10)

        if df.empty:
            return jsonify({"message": "没有找到相关数据。"})

        mean_hot = int(df["热度"].mean())
        summary = (
            f"在{time_period or '最近'}，{platform} 平台的平均热度为 {mean_hot}。\n"
            f"热门话题包括：{', '.join(df['标题'].head(5))}..."
        )

        return jsonify({
            "message": "分析成功",
            "raw_text": summary
        })

    except Exception as e:
        return jsonify({"error": str(e)})



#分支二：导出数据


@app.route("/download", methods=["POST"])
def download_csv():
    try:
        data = request.json or {}
        platform = data.get("platform", "all")
        topic = data.get("topic", "")
        raw_limit = data.get("limit", 0)
        try:
            limit = int(raw_limit) if str(raw_limit).strip() != "" else 0
        except Exception:
            limit = 0

        df = load_data(platform)
        df["热度"] = df["热度"].apply(clean_hot_value)
        df = df[df["热度"] > 0]

        if topic:
            df = df[df["标题"].astype(str).str.contains(topic, case=False, na=False)]

        df = df.sort_values("热度", ascending=False)

        if limit > 0:
            df = df.head(limit)
        ts = time.strftime("%Y%m%d_%H%M%S")
        file_name = f"hotsearch_{ts}.csv"
        file_path = f"/tmp/{file_name}"
        df.to_csv(file_path, index=False, encoding="utf-8-sig")

        download_url = upload_to_github(file_path, file_name)
        return jsonify({
            "message": "文件已上传至 GitHub",
            "file_url": download_url
        }),200
        
    except Exception as e:
        return jsonify({"error": str(e)})




if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000)










