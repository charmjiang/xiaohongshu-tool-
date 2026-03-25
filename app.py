from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
import os, json, hashlib, time
from datetime import date
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "xhs-secret-2024")

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

FREE_LIMIT = int(os.environ.get("FREE_LIMIT", 3))

# 三档激活码
CODE_MONTH1   = os.environ.get("CODE_MONTH1", "")    # 9.9首月
CODE_MONTHLY  = os.environ.get("CODE_MONTHLY", "")   # 19.9次月起
CODE_LIFETIME = os.environ.get("CODE_LIFETIME", "")  # 199终身

ADMIN_CODES = {c for c in [CODE_MONTH1, CODE_MONTHLY, CODE_LIFETIME] if c}

# 内存存储使用次数（生产环境可换Redis）
usage_store = {}

def get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()

def get_usage_key():
    ip = get_ip()
    today = str(date.today())
    return f"{ip}:{today}"

def get_remaining():
    # 已解锁用户不限制
    if session.get("unlocked"):
        return 9999
    key = get_usage_key()
    used = usage_store.get(key, 0)
    return max(0, FREE_LIMIT - used)

def increment_usage():
    if session.get("unlocked"):
        return
    key = get_usage_key()
    usage_store[key] = usage_store.get(key, 0) + 1

STYLES = {
    "真实日记体": "像普通人写的真实日记，有个人感受和小细节，不完美但有温度",
    "闺蜜碎碎念": "像跟闺蜜聊天，随性，有口头禅，偶尔吐槽，不刻意",
    "理性测评": "像真实用户写的测评，有优点也有缺点，数据具体，不夸大",
    "故事叙述": "以一段经历或故事引入，有起伏，让人代入感强",
    "干货清单": "实用为主，分点列举，简洁有据，像笔记整理",
    "踩坑避雷": "以自己的失败经历开头，提醒别人注意，语气真诚不说教",
    "对比测评": "同类产品横向对比，有具体差异描述，帮助读者做选择",
    "新手攻略": "从零讲起，语气亲切，预判新手疑问，步骤清晰易懂",
    "悬念开场": "开头设悬念或反转，吊足胃口，让人忍不住看下去",
    "数字技巧": "标题和正文大量使用数字，如'3个方法''第2个最好用'，直接高效",
    "情绪共鸣": "先描述一种普遍情绪或困境，让读者觉得'说的就是我'，再给出解法",
    "场景代入": "开头用一个具体生活场景切入，让读者迅速感同身受",
    "专家口吻": "以该领域内行人的视角写，有专业细节但不晦涩，给人可信感",
    "轻吐槽风": "带点小抱怨小无奈，轻松幽默，有自嘲成分，读起来解压",
    "治愈温暖": "语气温柔舒缓，注重情绪价值，让人读完感到被治愈或被鼓励",
}

SCENES = {
    "产品种草": "产品推荐/安利",
    "探店打卡": "餐厅/咖啡店/网红地打卡",
    "旅游攻略": "旅游游记或攻略",
    "美食分享": "美食探索或自制美食",
    "穿搭分享": "穿搭/时尚/搭配",
    "日常生活": "日常vlog/生活记录",
    "学习成长": "干货/知识分享/学习笔记",
    "AI/科技": "AI工具/科技产品测评",
}

def generate_copy(scene, style, keywords, extra=""):
    scene_desc = SCENES.get(scene, scene)
    style_desc = STYLES.get(style, style)

    prompt = f"""你是一个真实的小红书用户，不是营销号。请写一篇关于"{keywords}"的笔记，场景是{scene_desc}，风格是{style_desc}。

【必须遵守的规则，否则会被平台限流】
- 禁止使用：强烈推荐、必入、绝了、yyds、宝子们、姐妹们、绝绝子、种草、拔草、测评结论式总结
- 禁止开头就夸产品，要先讲自己的场景或遇到的问题
- 最多3个emoji，不要每句话都加
- 不要用感叹号堆砌，语气平实自然
- 可以提1个小缺点或注意事项，显得更真实
- 字数控制在250-400字，不要太长

{f"补充信息：{extra}" if extra else ""}

输出JSON格式：
{{
  "title": "标题（像真人写的，可以是疑问句或个人感受，不超过18字，最多1个emoji）",
  "content": "正文（自然分段，口语化，有真实细节）",
  "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"],
  "hook": "第一句话（从个人遭遇/问题/场景切入，不要直接夸产品）"
}}

只输出JSON，不要其他内容。"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)

@app.route("/")
def index():
    remaining = get_remaining()
    return render_template("index.html", scenes=SCENES, styles=STYLES,
                           free_limit=FREE_LIMIT, remaining=remaining,
                           unlocked=session.get("unlocked", False))

@app.route("/generate", methods=["POST"])
def generate():
    if get_remaining() <= 0:
        return jsonify({"error": "LIMIT_REACHED"}), 429

    data = request.json
    scene = data.get("scene", "日常生活")
    style = data.get("style", "真实日记体")
    keywords = data.get("keywords", "")
    extra = data.get("extra", "")

    if not keywords:
        return jsonify({"error": "请输入关键词"}), 400

    try:
        result = generate_copy(scene, style, keywords, extra)
        increment_usage()
        result["remaining"] = get_remaining()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"生成失败：{str(e)}"}), 500

@app.route("/unlock", methods=["POST"])
def unlock():
    code = request.json.get("code", "").strip()
    # 验证码：ADMIN_CODES 里的任意一个，或者硬编码的格式
    valid = code in ADMIN_CODES and code != ""
    if valid:
        session["unlocked"] = True
        session.permanent = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "无效的激活码"}), 400

if __name__ == "__main__":
    app.run(debug=True, port=5000)
