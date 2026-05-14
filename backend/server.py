from __future__ import annotations

import json
import os
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request


APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# Demo-stage in-memory store is enough for classroom use.
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
    "identified_items": [
        {"name": "rice", "label_zh": "米饭", "estimated_grams": 18},
    ],
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


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {"raw_text": text}


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


def _openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import OpenAI

    base_url = os.getenv("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _openai_schema_for_premeal() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "identified_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "label_zh": {"type": "string"},
                        "estimated_grams": {"type": "number"},
                    },
                    "required": ["name", "label_zh", "estimated_grams"],
                },
            },
            "structure_assessment": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "main_food": {"type": "string"},
                    "protein": {"type": "string"},
                    "vegetable": {"type": "string"},
                    "balance": {"type": "string"},
                },
                "required": ["main_food", "protein", "vegetable", "balance"],
            },
            "parent_message": {"type": "string"},
            "child_message": {"type": "string"},
        },
        "required": ["identified_items", "structure_assessment", "parent_message", "child_message"],
    }


def _openai_schema_for_frame() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "dominant_food_name": {"type": "string"},
            "label_zh": {"type": "string"},
            "food_group": {"type": "string"},
            "pace_hint": {"type": "string"},
            "child_message": {"type": "string"},
        },
        "required": ["dominant_food_name", "label_zh", "food_group", "pace_hint", "child_message"],
    }


def _analyze_with_openai(image_path: Path, mode: str) -> dict[str, Any]:
    client = _openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not set")

    with image_path.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="vision")

    if mode == "premeal":
        prompt = (
            "You are analyzing the food currently held in a child's spoon from a spoon-mounted camera view. "
            "This is for a classroom prototype, so rough estimation is acceptable. "
            "Focus on the current bite rather than the whole plate. "
            "Identify the most likely food in this bite using short canonical English keys where possible from this set: "
            "rice, noodles, bread, corn, chicken, egg, tofu, broccoli, carrot, bok_choy, apple, banana. "
            "Estimate rough grams for the visible bite contents. "
            "Then judge what nutrient group this bite mainly belongs to. "
            "Return a short parent-facing sentence describing this bite and one friendly child-facing sentence. "
            "Return only the requested JSON."
        )
        schema = _openai_schema_for_premeal()
        schema_name = "child_meal_premeal"
    else:
        prompt = (
            "You are analyzing one in-meal spoon-camera frame during a child's meal. "
            "Focus on the food currently nearest the spoon or dominating the frame. "
            "Return a coarse food group among 主食, 蛋白质, 蔬菜, 水果, 其他. "
            "Infer pace_hint as slow, normal, or fast only as a rough classroom-demo approximation. "
            "Provide one short, positive child-facing guidance sentence. "
            "Return only the requested JSON."
        )
        schema = _openai_schema_for_frame()
        schema_name = "child_meal_frame"

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "file_id": uploaded.id},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    )

    parsed = _safe_json_loads(response.output_text)
    if mode == "premeal":
        nutrition = _nutrition_for_items(parsed.get("identified_items", []))
        parsed["nutrition_estimate"] = nutrition["totals"]
        parsed["planned_groups"] = nutrition["groups"]
    return parsed


def analyze_image(image_path: Path, mode: str, meal: dict[str, Any] | None = None) -> dict[str, Any]:
    if os.getenv("OPENAI_API_KEY"):
        try:
            result = _analyze_with_openai(image_path, mode)
            result["success"] = True
            result["mode"] = "openai"
            return result
        except Exception as exc:
            fallback = _mock_premeal_analysis() if mode == "premeal" else _mock_frame_analysis(len((meal or {}).get("frames", [])))
            return {
                "success": False,
                "mode": "fallback_mock",
                "error": f"openai_analysis_failed: {exc}",
                **fallback,
            }

    if mode == "premeal":
        result = _mock_premeal_analysis()
    else:
        result = _mock_frame_analysis(len((meal or {}).get("frames", [])))
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
    premeal = meal.get("premeal") or {}
    frames = meal.get("frames", [])

    actual_counts: dict[str, int] = {}
    pace_counts: dict[str, int] = {}
    for frame in frames:
        group = frame.get("food_group", "其他")
        actual_counts[group] = actual_counts.get(group, 0) + 1
        pace = frame.get("pace_hint", "normal")
        pace_counts[pace] = pace_counts.get(pace, 0) + 1

    deviation_notes = []
    if actual_counts.get("蔬菜", 0) == 0 and len(frames) > 0:
        deviation_notes.append("当前记录中未观察到蔬菜摄入，存在蔬菜摄入不足风险。")
    if actual_counts.get("主食", 0) > actual_counts.get("蛋白质", 0) + actual_counts.get("蔬菜", 0) and len(frames) > 1:
        deviation_notes.append("连续多口以主食为主，存在摄入结构失衡风险。")
    if pace_counts.get("fast", 0) >= 2:
        deviation_notes.append("进食速度偏快，建议加强节奏引导。")
    if not deviation_notes:
        deviation_notes.append("当前摄入序列较平稳，尚未观察到明显偏食趋势。")

    if actual_counts.get("蔬菜", 0) == 0 and len(frames) >= 3:
        attribution = "主要表现为实际摄入偏好问题：孩子连续多口未摄入蔬菜。"
    elif actual_counts.get("主食", 0) >= 2 and actual_counts.get("蛋白质", 0) == 0:
        attribution = "当前摄入更偏向主食，蛋白质摄入偏少。"
    else:
        attribution = "当前记录下的实际摄入结构相对均衡。"

    child_feedback = "今天吃饭很认真，我们下次也试试换一口不同的食物吧。"
    if pace_counts.get("fast", 0) >= 2:
        child_feedback = "慢慢吃会更舒服，小勺陪你慢一点。"

    parent_summary = " ".join(deviation_notes + [attribution])

    return {
        "meal_id": meal["meal_id"],
        "captured_frames": len(frames),
        "first_bite_estimate": premeal.get("nutrition_estimate", {}),
        "first_bite_assessment": premeal.get("structure_assessment", {}),
        "actual_intake_proxy": actual_counts,
        "pace_observation": pace_counts,
        "deviation_analysis": deviation_notes,
        "attribution": attribution,
        "child_feedback": child_feedback,
        "parent_summary": parent_summary,
    }


def _latest_meal() -> dict[str, Any] | None:
    if not MEALS:
        return None
    return list(MEALS.values())[-1]


def _dashboard_html(meal: dict[str, Any] | None) -> str:
    template = """
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>儿童勺具配件 · 家长端结果页</title>
      <style>
        :root {
          --paper: rgba(255,255,255,.82);
          --ink: #17303d;
          --muted: #5b6a73;
          --accent: #2f7179;
          --line: rgba(23,48,61,.08);
        }
        * { box-sizing: border-box; }
        body {
          margin: 0;
          font-family: "PingFang SC","Microsoft YaHei",sans-serif;
          color: var(--ink);
          background:
            radial-gradient(circle at 8% 12%, #fff3dc 0, transparent 22%),
            radial-gradient(circle at 92% 10%, #d9efea 0, transparent 20%),
            linear-gradient(180deg, #f8f4ed 0%, #eef4f6 100%);
        }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 44px 24px 72px; }
        .hero { display: flex; justify-content: space-between; gap: 16px; align-items: end; margin-bottom: 26px; }
        h1 { margin: 0 0 10px; font-size: 38px; line-height: 1.2; }
        .lead { margin: 0; color: var(--muted); font-size: 18px; line-height: 1.7; max-width: 780px; }
        .badge { background: var(--paper); border: 1px solid var(--line); border-radius: 999px; padding: 10px 16px; color: var(--muted); font-size: 14px; white-space: nowrap; }
        .grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 20px; }
        .card { background: var(--paper); border: 1px solid var(--line); border-radius: 24px; padding: 22px; box-shadow: 0 16px 36px rgba(33,56,74,.08); backdrop-filter: blur(10px); }
        .card h2 { margin: 0 0 14px; font-size: 22px; }
        .meta { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
        .chip { border-radius: 999px; padding: 8px 12px; background: #fff; border: 1px solid var(--line); font-size: 14px; color: var(--muted); }
        .stack { display: grid; gap: 18px; }
        .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
        .metric { background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 14px 16px; }
        .metric .label { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
        .metric .value { font-size: 26px; font-weight: 700; }
        .section-title { margin: 0 0 10px; font-size: 16px; color: var(--muted); }
        .list { display: grid; gap: 10px; }
        .list-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; }
        .tone-box { background: linear-gradient(180deg, #ffffff 0%, #f7fbfc 100%); border: 1px solid var(--line); border-radius: 18px; padding: 16px; line-height: 1.7; }
        .warn-box { background: linear-gradient(180deg, #fff9ef 0%, #fff4dd 100%); border: 1px solid rgba(224, 167, 79, .22); border-radius: 18px; padding: 16px; line-height: 1.7; }
        .frames { display: grid; gap: 10px; }
        .frame-row { display: grid; grid-template-columns: 96px 1fr auto; gap: 12px; align-items: center; padding: 12px; background: #fff; border: 1px solid var(--line); border-radius: 16px; }
        .frame-index { font-weight: 700; color: var(--accent); }
        .empty { padding: 32px 24px; text-align: center; color: var(--muted); }
        @media (max-width: 960px) {
          .grid { grid-template-columns: 1fr; }
          .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <div>
            <h1>儿童勺具配件 · 家长端结果页</h1>
            <p class="lead">展示最近一餐的单口识别结果、连续摄入观察和餐后摄入结构总结。适合作为课堂 demo 展示页、录屏页和汇报中的“家长端应用原型”。</p>
          </div>
          <div class="badge">模式：{{ mode }}</div>
        </div>

        {% if meal %}
          {% set premeal = meal.premeal or {} %}
          {% set summary = summary_payload or {} %}
          <div class="grid">
            <div class="stack">
              <div class="card">
                <h2>本餐概览</h2>
                <div class="meta">
                  <div class="chip">Meal ID：{{ meal.meal_id }}</div>
                  <div class="chip">设备：{{ meal.device_id }}</div>
                  <div class="chip">已识别勺口：{{ summary.get('captured_frames', 0) }} 次</div>
                </div>
                <div class="metrics">
                  <div class="metric"><div class="label">首口热量估计</div><div class="value">{{ summary.get('first_bite_estimate', {}).get('kcal', '-') }}</div></div>
                  <div class="metric"><div class="label">首口蛋白质</div><div class="value">{{ summary.get('first_bite_estimate', {}).get('protein', '-') }}</div></div>
                  <div class="metric"><div class="label">首口碳水</div><div class="value">{{ summary.get('first_bite_estimate', {}).get('carbs', '-') }}</div></div>
                  <div class="metric"><div class="label">首口脂肪</div><div class="value">{{ summary.get('first_bite_estimate', {}).get('fat', '-') }}</div></div>
                </div>
              </div>

              <div class="card">
                <h2>首口识别结果</h2>
                <div class="section-title">当前勺子中的食物</div>
                <div class="list">
                  {% for item in premeal.get('identified_items', []) %}
                    <div class="list-item">
                      <div>{{ item.label_zh }}（{{ item.name }}）</div>
                      <div>{{ item.estimated_grams }}g</div>
                    </div>
                  {% endfor %}
                </div>
                <div style="height: 16px;"></div>
                <div class="section-title">单口营养判断</div>
                <div class="list">
                  {% for key, value in summary.get('first_bite_assessment', {}).items() %}
                    <div class="list-item"><div>{{ key }}</div><div>{{ value }}</div></div>
                  {% endfor %}
                </div>
              </div>

              <div class="card">
                <h2>连续摄入序列</h2>
                <div class="frames">
                  {% for frame in meal.frames %}
                    <div class="frame-row">
                      <div class="frame-index">Frame {{ loop.index }}</div>
                      <div>{{ frame.label_zh }} / {{ frame.food_group }}</div>
                      <div>{{ frame.pace_hint }}</div>
                    </div>
                  {% else %}
                    <div class="empty">还没有勺口识别数据。可先在串口输入 <code>m</code> 开始，再输入 <code>f</code> 上传当前一口的图像。</div>
                  {% endfor %}
                </div>
              </div>
            </div>

            <div class="stack">
              <div class="card">
                <h2>餐后摄入结构分析</h2>
                <div class="warn-box">
                  <strong>家长总结：</strong><br />
                  {{ summary.get('parent_summary', '暂无总结') }}
                </div>
                <div style="height: 14px;"></div>
                <div class="section-title">偏差说明</div>
                <div class="list">
                  {% for note in summary.get('deviation_analysis', []) %}
                    <div class="list-item">{{ note }}</div>
                  {% endfor %}
                </div>
              </div>

              <div class="card">
                <h2>问题归因</h2>
                <div class="tone-box">{{ summary.get('attribution', '暂无归因') }}</div>
                <div style="height: 14px;"></div>
                <div class="section-title">儿童端反馈建议</div>
                <div class="tone-box">{{ summary.get('child_feedback', '暂无反馈') }}</div>
              </div>

              <div class="card">
                <h2>实际摄入代理</h2>
                <div class="list">
                  {% for key, value in summary.get('actual_intake_proxy', {}).items() %}
                    <div class="list-item"><div>{{ key }}</div><div>{{ value }}</div></div>
                  {% else %}
                    <div class="list-item">暂无餐中采样</div>
                  {% endfor %}
                </div>
                <div style="height: 14px;"></div>
                <div class="section-title">进食节奏观察</div>
                <div class="list">
                  {% for key, value in summary.get('pace_observation', {}).items() %}
                    <div class="list-item"><div>{{ key }}</div><div>{{ value }}</div></div>
                  {% else %}
                    <div class="list-item">暂无节奏数据</div>
                  {% endfor %}
                </div>
              </div>
            </div>
          </div>
        {% else %}
          <div class="card empty">还没有收到任何一餐的数据。先启动硬件 demo，并让勺具识别第一口食物。</div>
        {% endif %}
      </div>
    </body>
    </html>
    """

    summary_payload = _build_summary(meal) if meal else None
    return render_template_string(
        template,
        meal=meal,
        summary_payload=summary_payload,
        mode="openai" if os.getenv("OPENAI_API_KEY") else "mock",
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "success": True,
            "mode": "openai" if os.getenv("OPENAI_API_KEY") else "mock",
            "meals_in_memory": len(MEALS),
        }
    )


@app.get("/")
def dashboard():
    return _dashboard_html(_latest_meal())


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
    meal["premeal"] = {
        **analysis,
        "image_path": str(image_path),
        "captured_at": _now(),
    }

    return jsonify(
        {
            "success": True,
            "meal_id": meal_id,
            "mode": "openai" if os.getenv("OPENAI_API_KEY") else "mock",
            "analysis": analysis,
        }
    )


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
    frame_record = {
        **analysis,
        "image_path": str(image_path),
        "captured_at": _now(),
    }
    meal["frames"].append(frame_record)

    return jsonify(
        {
            "success": True,
            "meal_id": meal_id,
            "frame_index": len(meal["frames"]) - 1,
            "analysis": analysis,
        }
    )


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
