from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request


APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _load_env_file() -> None:
    """Load local backend/.env values without adding an extra dependency."""
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

app = Flask(__name__)

# Demo-stage in-memory store. Restarting the backend clears it.
MEALS: dict[str, dict[str, Any]] = {}


NUTRITION_DB = {
    "rice": {"group": "主食", "label_zh": "米饭", "kcal": 116, "protein": 2.6, "carbs": 25.9, "fat": 0.3},
    "noodles": {"group": "主食", "label_zh": "面条", "kcal": 138, "protein": 4.5, "carbs": 27.0, "fat": 1.7},
    "bread": {"group": "主食", "label_zh": "面包", "kcal": 265, "protein": 8.9, "carbs": 49.0, "fat": 3.2},
    "corn": {"group": "主食", "label_zh": "玉米", "kcal": 86, "protein": 3.4, "carbs": 19.0, "fat": 1.2},
    "chicken": {"group": "蛋白质", "label_zh": "鸡肉", "kcal": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.6},
    "egg": {"group": "蛋白质", "label_zh": "鸡蛋", "kcal": 155, "protein": 13.0, "carbs": 1.1, "fat": 11.0},
    "tofu": {"group": "蛋白质", "label_zh": "豆腐", "kcal": 76, "protein": 8.0, "carbs": 1.9, "fat": 4.8},
    "broccoli": {"group": "蔬菜", "label_zh": "西兰花", "kcal": 34, "protein": 2.8, "carbs": 7.0, "fat": 0.4},
    "carrot": {"group": "蔬菜", "label_zh": "胡萝卜", "kcal": 41, "protein": 0.9, "carbs": 9.6, "fat": 0.2},
    "bok_choy": {"group": "蔬菜", "label_zh": "青菜", "kcal": 13, "protein": 1.5, "carbs": 2.2, "fat": 0.2},
    "apple": {"group": "水果", "label_zh": "苹果", "kcal": 52, "protein": 0.3, "carbs": 14.0, "fat": 0.2},
    "banana": {"group": "水果", "label_zh": "香蕉", "kcal": 89, "protein": 1.1, "carbs": 23.0, "fat": 0.3},
}


MOCK_PREMEAL = {
    "identified_items": [{"name": "rice", "label_zh": "米饭", "estimated_grams": 18}],
    "structure_assessment": {
        "main_food": "本口为主食",
        "protein": "未检测到",
        "vegetable": "未检测到",
        "balance": "单口信息不足以判断整餐",
    },
    "parent_message": "已识别当前这一口主要为主食，可继续累计多口结果后判断摄入结构。",
    "child_message": "小勺看到这一口啦，继续吃饭吧。",
}


MOCK_FRAME_SEQUENCE = [
    {"dominant_food_name": "rice", "label_zh": "米饭", "food_group": "主食", "pace_hint": "normal"},
    {"dominant_food_name": "rice", "label_zh": "米饭", "food_group": "主食", "pace_hint": "fast"},
    {"dominant_food_name": "chicken", "label_zh": "鸡肉", "food_group": "蛋白质", "pace_hint": "normal"},
    {"dominant_food_name": "broccoli", "label_zh": "西兰花", "food_group": "蔬菜", "pace_hint": "normal"},
]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _save_upload(file_storage, prefix: str) -> Path:
    suffix = Path(file_storage.filename or "capture.jpg").suffix or ".jpg"
    file_name = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
    path = UPLOAD_DIR / file_name
    file_storage.save(path)
    return path


def _nutrition_for_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    groups: dict[str, int] = {}

    for item in items:
        key = item.get("name")
        grams = float(item.get("estimated_grams", 0) or 0)
        ref = NUTRITION_DB.get(key)
        if not ref:
            continue
        factor = grams / 100.0
        totals["kcal"] += ref["kcal"] * factor
        totals["protein"] += ref["protein"] * factor
        totals["carbs"] += ref["carbs"] * factor
        totals["fat"] += ref["fat"] * factor
        groups[ref["group"]] = groups.get(ref["group"], 0) + 1

    return {
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "groups": groups,
    }


def _mock_premeal_analysis() -> dict[str, Any]:
    nutrition = _nutrition_for_items(MOCK_PREMEAL["identified_items"])
    return {
        **MOCK_PREMEAL,
        "nutrition_estimate": nutrition["totals"],
        "planned_groups": nutrition["groups"],
    }


def _mock_frame_analysis(frame_index: int) -> dict[str, Any]:
    result = MOCK_FRAME_SEQUENCE[frame_index % len(MOCK_FRAME_SEQUENCE)].copy()
    result["child_message"] = "慢慢吃更好哦" if result["pace_hint"] == "fast" else "吃得真不错"
    return result


def _model_client():
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    from openai import OpenAI

    base_url = os.getenv("OPENAI_BASE_URL")
    if not base_url and os.getenv("DASHSCOPE_API_KEY"):
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _model_name() -> str:
    if os.getenv("OPENAI_MODEL"):
        return os.getenv("OPENAI_MODEL", "")
    if os.getenv("DASHSCOPE_API_KEY"):
        return "qwen-vl-plus"
    return "gpt-4.1-mini"


def _model_mode() -> str:
    if os.getenv("DASHSCOPE_API_KEY"):
        return "bailian"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "mock"


def _image_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _analyze_with_llm(image_path: Path, mode: str) -> dict[str, Any]:
    client = _model_client()
    if client is None:
        raise RuntimeError("DASHSCOPE_API_KEY or OPENAI_API_KEY is not set")

    if mode == "premeal":
        prompt = (
            "You are analyzing the food currently held in a child's spoon from a spoon-mounted camera view. "
            "This is a classroom prototype, so rough estimation is acceptable. Focus on the current bite, not the whole plate. "
            "Use canonical English keys when possible: rice, noodles, bread, corn, chicken, egg, tofu, broccoli, carrot, bok_choy, apple, banana. "
            "Estimate rough grams for the visible bite contents. "
            "Return only valid JSON with fields: identified_items, structure_assessment, parent_message, child_message. "
            "identified_items is an array of objects with name, label_zh, estimated_grams. "
            "structure_assessment contains main_food, protein, vegetable, balance. Use Chinese for label_zh and messages."
        )
    else:
        prompt = (
            "You are analyzing one spoon-mounted camera frame during a child's meal. "
            "Focus on the food currently in or nearest the spoon. "
            "Return only valid JSON with fields: dominant_food_name, label_zh, food_group, pace_hint, child_message. "
            "food_group must be one of: 主食, 蛋白质, 蔬菜, 水果, 混合, 未知. "
            "pace_hint must be one of: slow, normal, fast, unknown. Use Chinese for label_zh and child_message."
        )

    response = client.chat.completions.create(
        model=_model_name(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            }
        ],
        temperature=0.2,
    )

    text = response.choices[0].message.content or "{}"
    parsed = _extract_json_object(text)
    if mode == "premeal":
        nutrition = _nutrition_for_items(parsed.get("identified_items", []))
        parsed["nutrition_estimate"] = nutrition["totals"]
        parsed["planned_groups"] = nutrition["groups"]
    return parsed


def analyze_image(image_path: Path, mode: str, meal: dict[str, Any] | None = None) -> dict[str, Any]:
    if _model_mode() != "mock":
        try:
            result = _analyze_with_llm(image_path, mode)
            result["success"] = True
            result["mode"] = _model_mode()
            result["model"] = _model_name()
            return result
        except Exception as exc:
            fallback = _mock_premeal_analysis() if mode == "premeal" else _mock_frame_analysis(len((meal or {}).get("frames", [])))
            return {
                "success": False,
                "mode": "fallback_mock",
                "model": _model_name(),
                "error": f"llm_analysis_failed: {exc}",
                **fallback,
            }

    result = _mock_premeal_analysis() if mode == "premeal" else _mock_frame_analysis(len((meal or {}).get("frames", [])))
    result["success"] = True
    result["mode"] = "mock"
    return result


def _get_or_create_meal(meal_id: str, device_id: str) -> dict[str, Any]:
    meal = MEALS.get(meal_id)
    if meal is None:
        meal = {
            "meal_id": meal_id,
            "device_id": device_id,
            "created_at": _now(),
            "premeal": None,
            "frames": [],
        }
        MEALS[meal_id] = meal
    return meal


def _build_summary(meal: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, int] = {}
    paces: dict[str, int] = {}

    for frame in meal.get("frames", []):
        group = frame.get("food_group") or "未知"
        pace = frame.get("pace_hint") or "unknown"
        groups[group] = groups.get(group, 0) + 1
        paces[pace] = paces.get(pace, 0) + 1

    deviation: list[str] = []
    if groups and groups.get("蔬菜", 0) == 0:
        deviation.append("当前记录中未观察到蔬菜摄入，存在蔬菜摄入不足风险。")
    if groups.get("主食", 0) >= 2 and groups.get("蔬菜", 0) == 0:
        deviation.append("连续多口以主食为主，存在摄入结构失衡风险。")
    if paces.get("fast", 0) > 0:
        deviation.append("部分摄入节奏偏快，可引导孩子慢一点吃。")
    if not deviation:
        deviation.append("当前摄入结构暂未发现明显偏差，可继续观察更多单口数据。")

    attribution = "主要表现为实际摄入偏好问题：孩子连续多口未摄入蔬菜。" if groups.get("蔬菜", 0) == 0 else "当前偏差较轻，建议继续累计更多餐次观察。"

    premeal = meal.get("premeal") or {}
    return {
        "meal_id": meal["meal_id"],
        "captured_frames": len(meal.get("frames", [])),
        "planned_nutrition_estimate": premeal.get("nutrition_estimate", {}),
        "planned_structure": premeal.get("structure_assessment", {}),
        "actual_intake_proxy": groups,
        "pace_observation": paces,
        "deviation_analysis": deviation,
        "attribution": attribution,
        "parent_summary": " ".join(deviation + [attribution]),
        "child_feedback": "今天吃饭很认真，我们下次也试试换一口不同的食物吧。",
    }


def _latest_meal() -> dict[str, Any] | None:
    if not MEALS:
        return None
    return next(reversed(MEALS.values()))


def _dashboard_html(meal: dict[str, Any] | None) -> str:
    template = """
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>儿童勺具配件 - 家长端结果页</title>
      <style>
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f3eb; color: #18313c; }
        .wrap { max-width: 1180px; margin: 0 auto; padding: 48px 28px; }
        h1 { font-size: 42px; margin: 0 0 12px; }
        h2 { margin: 0 0 16px; font-size: 24px; }
        .sub { color: #667681; max-width: 760px; line-height: 1.8; }
        .badge { display: inline-block; padding: 10px 18px; border-radius: 999px; background: #fff; margin-top: 8px; }
        .grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 24px; margin-top: 32px; }
        .card { background: rgba(255,255,255,.88); border: 1px solid rgba(0,0,0,.06); border-radius: 24px; padding: 28px; box-shadow: 0 18px 45px rgba(30,48,54,.08); }
        .chips { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 20px; }
        .chip { padding: 8px 14px; border: 1px solid #e8e2d8; border-radius: 999px; background: #fff; color: #667681; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
        .stat { padding: 18px; border: 1px solid #eee7dc; border-radius: 18px; background: #fff; }
        .stat b { display: block; margin-top: 10px; font-size: 22px; }
        .list { display: grid; gap: 10px; }
        .item { display: flex; justify-content: space-between; gap: 18px; padding: 14px 16px; border: 1px solid #eee7dc; border-radius: 16px; background: #fff; }
        .tone { background: #fff7e8; border: 1px solid #f3deba; border-radius: 18px; padding: 18px; line-height: 1.8; }
        .empty { text-align: center; color: #667681; margin-top: 34px; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <h1>儿童勺具配件 · 家长端结果页</h1>
        <div class="sub">展示最近一餐的单口识别结果、连续摄入观察和餐后摄入结构总结。适合作为课堂 demo、录屏和前端联调参考。</div>
        <div class="badge">模式：{{ mode }}</div>
        {% if meal %}
          {% set pre = meal.get('premeal') or {} %}
          {% set summary = summary_payload or {} %}
          {% set nutrition = pre.get('nutrition_estimate', {}) %}
          <div class="grid">
            <div>
              <div class="card">
                <h2>本餐概览</h2>
                <div class="chips">
                  <div class="chip">Meal ID：{{ meal.get('meal_id') }}</div>
                  <div class="chip">设备：{{ meal.get('device_id') }}</div>
                  <div class="chip">已识别小口：{{ meal.get('frames', [])|length }} 次</div>
                </div>
                <div class="stats">
                  <div class="stat">首口热量<b>{{ nutrition.get('kcal', '-') }}</b></div>
                  <div class="stat">蛋白质<b>{{ nutrition.get('protein', '-') }}</b></div>
                  <div class="stat">碳水<b>{{ nutrition.get('carbs', '-') }}</b></div>
                  <div class="stat">脂肪<b>{{ nutrition.get('fat', '-') }}</b></div>
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>首口识别结果</h2>
                <div class="list">
                {% for item in pre.get('identified_items', []) %}
                  <div class="item"><span>{{ item.get('label_zh') or item.get('name') }}</span><span>{{ item.get('estimated_grams') }}g</span></div>
                {% else %}
                  <div class="item">暂无首口识别</div>
                {% endfor %}
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>连续摄入序列</h2>
                <div class="list">
                {% for frame in meal.get('frames', []) %}
                  <div class="item"><span>Frame {{ loop.index }} · {{ frame.get('label_zh') }} / {{ frame.get('food_group') }}</span><span>{{ frame.get('pace_hint') }}</span></div>
                {% else %}
                  <div class="item">暂无餐中采样</div>
                {% endfor %}
                </div>
              </div>
            </div>
            <div>
              <div class="card">
                <h2>餐后摄入结构分析</h2>
                <div class="tone">{{ summary.get('parent_summary', '暂无总结') }}</div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>实际摄入代理</h2>
                <div class="list">
                {% for key, value in summary.get('actual_intake_proxy', {}).items() %}
                  <div class="item"><span>{{ key }}</span><span>{{ value }}</span></div>
                {% else %}
                  <div class="item">暂无数据</div>
                {% endfor %}
                </div>
              </div>
            </div>
          </div>
        {% else %}
          <div class="card empty">还没有收到任何一餐的数据。先启动硬件 demo，让勺具识别第一口食物。</div>
        {% endif %}
      </div>
    </body>
    </html>
    """
    summary_payload = _build_summary(meal) if meal else None
    return render_template_string(template, meal=meal, summary_payload=summary_payload, mode=_model_mode())


@app.get("/health")
def health():
    return jsonify({"success": True, "mode": _model_mode(), "model": _model_name(), "meals_in_memory": len(MEALS)})


@app.get("/")
def dashboard():
    return _dashboard_html(_latest_meal())


@app.get("/api/latest")
def latest():
    meal = _latest_meal()
    return jsonify({"success": True, "meal": meal, "summary": _build_summary(meal) if meal else None})


@app.post("/api/premeal")
def premeal():
    photo = request.files.get("photo")
    meal_id = request.form.get("meal_id") or f"meal-{uuid.uuid4().hex[:8]}"
    device_id = request.form.get("device_id") or "unknown-device"
    if not photo:
        return jsonify({"success": False, "error": "photo is required"}), 400

    image_path = _save_upload(photo, "premeal")
    meal = _get_or_create_meal(meal_id, device_id)
    analysis = analyze_image(image_path, "premeal", meal)
    meal["premeal"] = {**analysis, "image_path": str(image_path), "captured_at": _now()}
    return jsonify({"success": True, "meal_id": meal_id, "mode": _model_mode(), "analysis": analysis})


@app.post("/api/frame")
def frame():
    photo = request.files.get("photo")
    meal_id = request.form.get("meal_id")
    device_id = request.form.get("device_id") or "unknown-device"
    if not meal_id:
        return jsonify({"success": False, "error": "meal_id is required"}), 400
    if not photo:
        return jsonify({"success": False, "error": "photo is required"}), 400

    meal = _get_or_create_meal(meal_id, device_id)
    image_path = _save_upload(photo, "frame")
    analysis = analyze_image(image_path, "frame", meal)
    meal["frames"].append({**analysis, "image_path": str(image_path), "captured_at": _now()})
    return jsonify({"success": True, "meal_id": meal_id, "frame_index": len(meal["frames"]) - 1, "analysis": analysis})


@app.post("/api/summary")
def summary():
    data = request.get_json(silent=True) or {}
    meal_id = data.get("meal_id")
    if not meal_id or meal_id not in MEALS:
        return jsonify({"success": False, "error": "meal not found"}), 404
    return jsonify({"success": True, "summary": _build_summary(MEALS[meal_id])})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
