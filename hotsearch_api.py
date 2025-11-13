from flask import Flask, request, jsonify
import pandas as pd
import re

app = Flask(__name__)

from io import BytesIO
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# === GitHub raw 域名（避免重定向/SSL问题） ===
platform_files = {
    "weibo":   "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/weibo_hotsearch.xlsx",
    "toutiao": "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/toutiao_hotsearch.xlsx",
    "baidu":   "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/baidu_hotsearch.xlsx",
}
realtime_file = "https://raw.githubusercontent.com/ruining1030-droid/hotsearch-data/main/%E5%85%A8%E7%BD%91%E7%83%AD%E6%90%9C%E6%80%BB%E8%A1%A8.csv"

def make_session():
    """构造带重试机制的 requests Session"""
    s = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Hotsearch-Agent; +https://github.com/ruining1030-droid)"
    })
    return s

SESSION = make_session()

def fetch_excel(url: str) -> pd.DataFrame:
    """从 GitHub 稳定拉取 Excel 文件"""
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        return pd.read_excel(BytesIO(r.content))
    except requests.exceptions.SSLError:
        # SSL 异常时尝试关闭验证再试一次
        r = SESSION.get(url, timeout=30, verify=False)
        r.raise_for_status()
        return pd.read_excel(BytesIO(r.content))
    except Exception as e:
        raise RuntimeError(f"读取远程文件失败: {url} ({e})")

def load_data(platform: str) -> pd.DataFrame:
    """加载指定平台或全部平台"""
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



# === 工具函数 ===
def clean_hot_value(x):
    """清洗热度字段：保留数字并统一单位"""
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


def load_data(platform: str):
    """加载指定平台或全部平台的热搜数据"""
    dfs = []
    if platform in platform_files:
        df = pd.read_excel(platform_files[platform])
        df["平台"] = platform
        dfs.append(df)
    else:
        for p, path in platform_files.items():
            tmp = pd.read_excel(path)
            tmp["平台"] = p
            dfs.append(tmp)
    df = pd.concat(dfs, ignore_index=True)
    return df


# === 主分析接口 ===
@app.route("/analyze", methods=["POST"])
def analyze():
    """
    主接口：处理智能体请求
    支持 intent:
      - fetch_data: 返回原始数据（可 limit 数量）
      - generate_report: 生成简要趋势报告
    """
    try:
        data = request.json or {}
        intent = data.get("intent", "fetch_data")
        platform = data.get("platform", "all")
        topic = data.get("topic", "")
        time_period = data.get("time_period", "")
        limit = int(data.get("limit", 0))  # 默认 0 = 全部

        # ===== 加载数据 =====
        df = load_data(platform)
        df["热度"] = df["热度"].apply(clean_hot_value)
        df = df[df["热度"] > 0]

        # 筛选主题
        if topic:
            df = df[df["标题"].astype(str).str.contains(topic, case=False, na=False)]

        # 排序
        df = df.sort_values("热度", ascending=False)

        # ===== Intent 分支 =====
        if intent == "fetch_data":
            if limit > 0:
                df = df.head(limit)
            result = df[["平台", "标题", "热度"]].to_dict(orient="records")
            return jsonify({
                "message": f"{time_period or '最近'}关于{topic or '全部'}的热搜数据（共 {len(result)} 条）：",
                "data": result
            })

        elif intent == "generate_report":
            df_head = df.head(10)
            if df_head.empty:
                return jsonify({"message": "无数据生成报告。", "raw_text": ""})
            top_titles = df_head["标题"].tolist()
            mean_hot = int(df_head["热度"].mean())
            summary = (
                f"在{time_period or '最近'}，{platform or '全平台'}热搜的平均热度约为 {mean_hot}。"
                f"主要热门话题包括：{', '.join(top_titles[:5])} 等。"
            )
            return jsonify({
                "message": "生成趋势分析报告成功",
                "raw_text": summary
            })

        else:
            return jsonify({"error": f"未知的 intent: {intent}"})

    except Exception as e:
        return jsonify({"error": str(e)})


if __name__ == "__main__":
    print("lask 热搜分析接口启动中……")
    from waitress import serve
    try:
        serve(app, host="0.0.0.0", port=5000)
    except Exception as e:
        print(f"启动失败: {e}")




