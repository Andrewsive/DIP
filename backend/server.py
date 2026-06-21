from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request


APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
MEAL_HISTORY_PATH = DATA_DIR / "meal_history.json"


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


@app.after_request
def add_dev_cors_headers(response):
    # Allow the parent-side frontend prototype to run from a separate local dev server.
    response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ALLOW_ORIGIN", "*")
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# Demo-stage in-memory store. Restarting the backend clears it.
MEALS: dict[str, dict[str, Any]] = {}

MIN_BITE_INTERVAL_SECONDS = float(os.getenv("MIN_BITE_INTERVAL_SECONDS", "4"))


NUTRITION_DB = {
    "rice": {"group": "主食", "label_zh": "米饭", "kcal": 116, "protein": 2.6, "carbs": 25.9, "fat": 0.3},
    "noodles": {"group": "主食", "label_zh": "面条", "kcal": 138, "protein": 4.5, "carbs": 27.0, "fat": 1.7},
    "bread": {"group": "主食", "label_zh": "面包", "kcal": 265, "protein": 8.9, "carbs": 49.0, "fat": 3.2},
    "corn": {"group": "主食", "label_zh": "玉米", "kcal": 86, "protein": 3.4, "carbs": 19.0, "fat": 1.2},
    "chicken": {"group": "蛋白质", "label_zh": "鸡肉", "kcal": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.6},
    "egg": {"group": "蛋白质", "label_zh": "鸡蛋", "kcal": 155, "protein": 13.0, "carbs": 1.1, "fat": 11.0},
    "tofu": {"group": "蛋白质", "label_zh": "豆腐", "kcal": 76, "protein": 8.0, "carbs": 1.9, "fat": 4.8},
    "meatball": {"group": "蛋白质", "label_zh": "丸子", "kcal": 170, "protein": 10.0, "carbs": 9.0, "fat": 10.0},
    "dumpling": {"group": "混合", "label_zh": "饺子", "kcal": 220, "protein": 8.0, "carbs": 25.0, "fat": 10.0},
    "broccoli": {"group": "蔬菜", "label_zh": "西兰花", "kcal": 34, "protein": 2.8, "carbs": 7.0, "fat": 0.4},
    "carrot": {"group": "蔬菜", "label_zh": "胡萝卜", "kcal": 41, "protein": 0.9, "carbs": 9.6, "fat": 0.2},
    "bok_choy": {"group": "蔬菜", "label_zh": "青菜", "kcal": 13, "protein": 1.5, "carbs": 2.2, "fat": 0.2},
    "apple": {"group": "水果", "label_zh": "苹果", "kcal": 52, "protein": 0.3, "carbs": 14.0, "fat": 0.2},
    "banana": {"group": "水果", "label_zh": "香蕉", "kcal": 89, "protein": 1.1, "carbs": 23.0, "fat": 0.3},
}


FOOD_ALIASES = {
    "rice": "rice",
    "cooked rice": "rice",
    "米饭": "rice",
    "白米饭": "rice",
    "米": "rice",
    "饭": "rice",
    "noodles": "noodles",
    "noodle": "noodles",
    "面条": "noodles",
    "面": "noodles",
    "bread": "bread",
    "面包": "bread",
    "corn": "corn",
    "玉米": "corn",
    "chicken": "chicken",
    "鸡肉": "chicken",
    "鸡块": "chicken",
    "鸡丁": "chicken",
    "egg": "egg",
    "鸡蛋": "egg",
    "蛋": "egg",
    "tofu": "tofu",
    "豆腐": "tofu",
    "meatball": "meatball",
    "meat ball": "meatball",
    "fish ball": "meatball",
    "丸子": "meatball",
    "肉丸": "meatball",
    "鱼丸": "meatball",
    "虾丸": "meatball",
    "dumpling": "dumpling",
    "饺子": "dumpling",
    "broccoli": "broccoli",
    "西兰花": "broccoli",
    "carrot": "carrot",
    "胡萝卜": "carrot",
    "bok choy": "bok_choy",
    "bok_choy": "bok_choy",
    "青菜": "bok_choy",
    "小青菜": "bok_choy",
    "上海青": "bok_choy",
    "绿叶菜": "bok_choy",
    "apple": "apple",
    "苹果": "apple",
    "banana": "banana",
    "香蕉": "banana",
}


FOOD_KEY_HINTS = {
    "rice": ["rice", "米饭", "白米饭"],
    "noodles": ["noodles", "noodle", "面条"],
    "bread": ["bread", "面包"],
    "corn": ["corn", "玉米"],
    "chicken": ["chicken", "鸡肉", "鸡块", "鸡丁"],
    "egg": ["egg", "鸡蛋"],
    "tofu": ["tofu", "豆腐"],
    "meatball": ["meatball", "meat ball", "fish ball", "丸子", "肉丸", "鱼丸", "虾丸", "肉类", "肉"],
    "dumpling": ["dumpling", "饺子"],
    "broccoli": ["broccoli", "西兰花"],
    "carrot": ["carrot", "胡萝卜"],
    "bok_choy": ["bok choy", "青菜", "小青菜", "上海青", "绿叶菜", "绿色蔬菜", "蔬菜"],
    "apple": ["apple", "苹果"],
    "banana": ["banana", "香蕉"],
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
}


MOCK_FRAME_SEQUENCE = [
    {"dominant_food_name": "rice", "label_zh": "米饭", "food_group": "主食", "pace_hint": "normal"},
    {"dominant_food_name": "rice", "label_zh": "米饭", "food_group": "主食", "pace_hint": "fast"},
    {"dominant_food_name": "chicken", "label_zh": "鸡肉", "food_group": "蛋白质", "pace_hint": "normal"},
    {"dominant_food_name": "broccoli", "label_zh": "西兰花", "food_group": "蔬菜", "pace_hint": "normal"},
]


def _now(timestamp: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp or time.time()))


def _parse_local_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _save_upload(file_storage, prefix: str) -> Path:
    suffix = Path(file_storage.filename or "capture.jpg").suffix or ".jpg"
    file_name = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
    path = UPLOAD_DIR / file_name
    file_storage.save(path)
    return path


def _read_history_records() -> list[dict[str, Any]]:
    if not MEAL_HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(MEAL_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_history_records(records: list[dict[str, Any]]) -> None:
    MEAL_HISTORY_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_food_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _food_key_from_text(value: Any) -> str | None:
    normalized = _normalize_food_text(value)
    if not normalized:
        return None

    direct_key = normalized.replace(" ", "_")
    if direct_key in NUTRITION_DB:
        return direct_key
    if normalized in FOOD_ALIASES:
        return FOOD_ALIASES[normalized]

    for alias, canonical_key in FOOD_ALIASES.items():
        if alias and alias in normalized:
            return canonical_key
    return None


def _food_key_from_item(item: dict[str, Any]) -> str | None:
    for field in ("name", "dominant_food_name", "label_zh"):
        key = _food_key_from_text(item.get(field))
        if key:
            return key
    return None


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text not in {"未知", "未知食物", "unknown", "-"}


def _normalize_identified_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = item.copy()
    key = _food_key_from_item(normalized)
    if not key:
        return normalized

    ref = NUTRITION_DB[key]
    normalized["canonical_food_name"] = key
    normalized["name"] = key
    if not _has_meaningful_value(normalized.get("label_zh")):
        normalized["label_zh"] = ref["label_zh"]
    if not _has_meaningful_value(normalized.get("food_group")):
        normalized["food_group"] = ref["group"]
    return normalized


def _normalize_identified_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_normalize_identified_item(item) for item in items]


def _infer_food_keys_from_text(*values: Any) -> list[str]:
    text = " ".join(str(value or "") for value in values).lower().replace("_", " ")
    keys: list[str] = []
    for key, hints in FOOD_KEY_HINTS.items():
        if any(hint.lower() in text for hint in hints):
            keys.append(key)
    return keys


def _frame_components(frame: dict[str, Any]) -> list[dict[str, Any]]:
    raw_components = frame.get("components")
    if isinstance(raw_components, list) and raw_components:
        components = _normalize_identified_items([item for item in raw_components if isinstance(item, dict)])
        if components:
            return components

    inferred_keys = _infer_food_keys_from_text(
        frame.get("dominant_food_name"),
        frame.get("label_zh"),
        frame.get("food_group"),
        frame.get("parent_observation"),
    )
    if not inferred_keys:
        direct_key = _food_key_from_item(frame)
        if direct_key:
            inferred_keys = [direct_key]

    if not inferred_keys:
        return []

    total_grams = float(frame.get("estimated_grams", 0) or 0)
    grams_per_component = round(total_grams / len(inferred_keys), 1) if total_grams else 0
    components: list[dict[str, Any]] = []
    for key in inferred_keys:
        ref = NUTRITION_DB[key]
        components.append(
            {
                "name": key,
                "canonical_food_name": key,
                "label_zh": ref["label_zh"],
                "food_group": ref["group"],
                "estimated_grams": grams_per_component,
                "source": "inferred_from_components_or_text",
            }
        )
    return components


def _nutrition_for_frame(frame: dict[str, Any]) -> dict[str, Any]:
    components = _frame_components(frame)
    if components:
        return _nutrition_for_items(components)
    return _nutrition_for_items(
        [
            {
                "name": frame.get("canonical_food_name") or frame.get("dominant_food_name"),
                "label_zh": frame.get("label_zh"),
                "estimated_grams": frame.get("estimated_grams", 0),
            }
        ]
    )


def _group_component_counts(frames: list[dict[str, Any]]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for frame in frames:
        components = _frame_components(frame)
        if components:
            counted_groups = {component.get("food_group") or "未知" for component in components}
            for group in counted_groups:
                groups[group] = groups.get(group, 0) + 1
        else:
            group = frame.get("food_group") or "未知"
            groups[group] = groups.get(group, 0) + 1
    return groups


def _component_totals(frames: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for component in _frame_components(frame):
            key = component.get("canonical_food_name") or component.get("name") or component.get("label_zh") or "unknown"
            ref = NUTRITION_DB.get(str(key), {})
            label = component.get("label_zh") or ref.get("label_zh") or str(key)
            group = component.get("food_group") or ref.get("group") or "未知"
            entry = totals.setdefault(
                str(key),
                {
                    "canonical_food_name": key,
                    "label_zh": label,
                    "food_group": group,
                    "count": 0,
                    "estimated_grams": 0.0,
                },
            )
            entry["count"] += 1
            entry["estimated_grams"] = round(entry["estimated_grams"] + float(component.get("estimated_grams", 0) or 0), 1)
    return dict(sorted(totals.items(), key=lambda item: item[1]["count"], reverse=True))


def _display_food_items(component_totals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "canonical_food_name": item.get("canonical_food_name") or key,
            "label_zh": item.get("label_zh") or key,
            "food_group": item.get("food_group") or "未知",
            "count": item.get("count", 0),
            "estimated_grams": item.get("estimated_grams", 0),
        }
        for key, item in component_totals.items()
        if item.get("label_zh") not in {"混合食物", "混合", "未知", "未知食物"}
    ]


def _frame_display_label(frame: dict[str, Any]) -> str:
    components = _frame_components(frame)
    if components:
        labels = []
        for component in components:
            label = component.get("label_zh") or component.get("name")
            if label and label not in labels:
                labels.append(label)
        if labels:
            return " + ".join(labels)
    return frame.get("label_zh") or frame.get("dominant_food_name") or "未知"


def _meal_for_response(meal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not meal:
        return None
    response_meal = meal.copy()
    response_frames = []
    previous_components: list[dict[str, Any]] = []
    for frame in meal.get("frames", []):
        response_frame = frame.copy()
        components = _frame_components(response_frame)
        if not components and response_frame.get("label_zh") in {"混合食物", "混合"} and previous_components:
            components = [
                {
                    **component,
                    "source": "inferred_from_previous_valid_spoonful",
                }
                for component in previous_components
            ]
        if components:
            response_frame["raw_label_zh"] = response_frame.get("label_zh")
            response_frame["components"] = components
            response_frame["display_label_zh"] = _frame_display_label(response_frame)
            if response_frame.get("label_zh") in {"混合食物", "混合", "未知", "未知食物"}:
                response_frame["label_zh"] = response_frame["display_label_zh"]
            response_frame["nutrition_estimate"] = _nutrition_for_items(components)["totals"]
            previous_components = components
        else:
            response_frame["raw_label_zh"] = response_frame.get("label_zh")
            response_frame["display_label_zh"] = _frame_display_label(response_frame)
        response_frames.append(response_frame)
    response_meal["frames"] = response_frames
    return response_meal


def _nutrition_for_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    groups: dict[str, int] = {}

    for item in items:
        key = _food_key_from_item(item)
        grams = float(item.get("estimated_grams", 0) or 0)
        ref = NUTRITION_DB.get(key or "")
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
    identified_items = _normalize_identified_items(MOCK_PREMEAL["identified_items"])
    nutrition = _nutrition_for_items(identified_items)
    return {
        **MOCK_PREMEAL,
        "identified_items": identified_items,
        "nutrition_estimate": nutrition["totals"],
        "planned_groups": nutrition["groups"],
    }


def _mock_frame_analysis(frame_index: int) -> dict[str, Any]:
    result = MOCK_FRAME_SEQUENCE[frame_index % len(MOCK_FRAME_SEQUENCE)].copy()
    result["estimated_grams"] = 6
    result["components"] = [
        {
            "name": result["dominant_food_name"],
            "label_zh": result["label_zh"],
            "food_group": result["food_group"],
            "estimated_grams": result["estimated_grams"],
        }
    ]
    result["nutrition_estimate"] = _nutrition_for_items(
        result["components"]
    )["totals"]
    result["image_quality"] = {
        "spoon_visible": True,
        "food_visible": True,
        "clarity": "clear",
        "is_valid_bite": True,
        "quality_score": 0.8,
    }
    result["bite_event"] = {
        "is_new_bite": True,
        "duplicate_of_previous": False,
        "discard_reason": "",
    }
    result["parent_observation"] = f"本口主要识别为{result['label_zh']}，归类为{result['food_group']}。"
    return result


def _model_client():
    if _force_mock_mode():
        return None

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    from openai import OpenAI

    base_url = os.getenv("OPENAI_BASE_URL")
    if not base_url and os.getenv("DASHSCOPE_API_KEY"):
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    kwargs: dict[str, Any] = {"api_key": api_key}
    kwargs["timeout"] = float(os.getenv("MODEL_TIMEOUT_SECONDS", "45"))
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _force_mock_mode() -> bool:
    return os.getenv("FORCE_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def _model_name() -> str:
    if os.getenv("OPENAI_MODEL"):
        return os.getenv("OPENAI_MODEL", "")
    if os.getenv("DASHSCOPE_API_KEY"):
        return "qwen-vl-plus"
    return "gpt-4.1-mini"


def _model_mode() -> str:
    if _force_mock_mode():
        return "mock"
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


def _strip_removed_child_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    payload.pop("child_message", None)
    payload.pop("child_feedback", None)
    return payload


def _last_accepted_frame(meal: dict[str, Any] | None) -> dict[str, Any] | None:
    frames = (meal or {}).get("frames", [])
    return frames[-1] if frames else None


def _bool_from_model(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "是", "有效", "新一口"}
    return default


def _enrich_frame_analysis(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_food_name = parsed.get("dominant_food_name") or parsed.get("label_zh") or "unknown"
    food_key = _food_key_from_text(raw_food_name) or _food_key_from_text(parsed.get("food_group"))
    ref = NUTRITION_DB.get(food_key or "")
    parsed["canonical_food_name"] = food_key or "unknown"
    parsed.setdefault("dominant_food_name", raw_food_name)
    if ref and not _has_meaningful_value(parsed.get("label_zh")):
        parsed["label_zh"] = ref["label_zh"]
    else:
        parsed.setdefault("label_zh", "未知")
    if ref and not _has_meaningful_value(parsed.get("food_group")):
        parsed["food_group"] = ref["group"]
    else:
        parsed.setdefault("food_group", "未知")
    parsed.setdefault("estimated_grams", 0)
    parsed.setdefault("pace_hint", "unknown")
    parsed.setdefault("parent_observation", f"本口主要识别为{parsed.get('label_zh', '未知食物')}。")

    components = _frame_components(parsed)
    if components:
        parsed["components"] = components
        if len(components) == 1 and not _has_meaningful_value(parsed.get("food_group")):
            parsed["food_group"] = components[0]["food_group"]

    nutrition = _nutrition_for_items(components) if components else _nutrition_for_items(
        [
            {
                "name": food_key or raw_food_name,
                "label_zh": parsed.get("label_zh"),
                "estimated_grams": parsed.get("estimated_grams", 0),
            }
        ]
    )
    parsed["nutrition_estimate"] = nutrition["totals"]

    image_quality = parsed.get("image_quality") or {}
    parsed["image_quality"] = {
        "spoon_visible": _bool_from_model(image_quality.get("spoon_visible"), True),
        "food_visible": _bool_from_model(image_quality.get("food_visible"), parsed.get("food_group") != "未知"),
        "clarity": image_quality.get("clarity", "unknown"),
        "is_valid_bite": _bool_from_model(image_quality.get("is_valid_bite"), parsed.get("food_group") != "未知"),
        "quality_score": float(image_quality.get("quality_score", 0.5) or 0.5),
    }

    bite_event = parsed.get("bite_event") or {}
    parsed["bite_event"] = {
        "is_new_bite": _bool_from_model(bite_event.get("is_new_bite"), True),
        "duplicate_of_previous": _bool_from_model(bite_event.get("duplicate_of_previous"), False),
        "discard_reason": bite_event.get("discard_reason", ""),
    }
    return parsed


def _frame_gate(meal: dict[str, Any], analysis: dict[str, Any], captured_ts: float) -> dict[str, Any]:
    if analysis.get("success") is False:
        return {"accepted": False, "reason": analysis.get("error") or "模型分析失败，未写入有效单口序列。"}

    last_frame = _last_accepted_frame(meal)
    if last_frame:
        elapsed = captured_ts - float(last_frame.get("captured_ts", captured_ts))
        if elapsed < MIN_BITE_INTERVAL_SECONDS:
            return {
                "accepted": False,
                "reason": f"距离上一条有效单口仅 {elapsed:.1f}s，小于 {MIN_BITE_INTERVAL_SECONDS:.1f}s，判定为时间重复帧。",
            }

    quality = analysis.get("image_quality") or {}
    if not _bool_from_model(quality.get("is_valid_bite"), True):
        return {"accepted": False, "reason": "大模型判断该帧不是有效单口。"}
    if not _bool_from_model(quality.get("food_visible"), True):
        return {"accepted": False, "reason": "画面中未检测到清晰可见的勺中食物。"}

    bite_event = analysis.get("bite_event") or {}
    if _bool_from_model(bite_event.get("duplicate_of_previous"), False):
        return {"accepted": False, "reason": bite_event.get("discard_reason") or "大模型判断该帧与上一口重复。"}
    if not _bool_from_model(bite_event.get("is_new_bite"), True):
        return {"accepted": False, "reason": bite_event.get("discard_reason") or "大模型判断该帧不是新的一口。"}

    return {"accepted": True, "reason": "通过时间过滤与大模型有效单口判断。"}


def _analyze_with_llm(image_path: Path, mode: str, meal: dict[str, Any] | None = None) -> dict[str, Any]:
    client = _model_client()
    if client is None:
        raise RuntimeError("DASHSCOPE_API_KEY or OPENAI_API_KEY is not set")

    if mode == "premeal":
        prompt = (
            "You are analyzing the food currently held in a child's spoon from a spoon-mounted camera view. "
            "This is a classroom prototype, so rough estimation is acceptable. Focus on the current bite, not the whole plate. "
            "Use canonical English keys when possible: rice, noodles, bread, corn, chicken, egg, tofu, meatball, dumpling, broccoli, carrot, bok_choy, apple, banana. "
            "Estimate rough grams for the visible bite contents. "
            "Return only valid JSON with fields: identified_items, structure_assessment, parent_message. "
            "identified_items is an array of objects with name, label_zh, estimated_grams. "
            "structure_assessment contains main_food, protein, vegetable, balance. Use Chinese for label_zh and parent_message."
        )
    else:
        previous = _last_accepted_frame(meal)
        previous_note = ""
        if previous:
            previous_note = (
                f"Previous accepted bite summary: {previous.get('label_zh', 'unknown')} / "
                f"{previous.get('food_group', 'unknown')}, captured_at={previous.get('captured_at', '')}. "
                "Compare the current frame with the previous accepted bite image if provided. "
            )
        prompt = (
            "You are analyzing one spoon-mounted camera frame during a child's meal. "
            "Focus on the food currently in or nearest the spoon. The first image is the current frame. "
            "An optional second image is the previous accepted bite. "
            f"{previous_note}"
            "Decide whether the current frame is a valid new bite. Reject empty, blurred, no-spoon, no-food, or repeated frames. "
            "Estimate grams using a normal child spoon capacity, roughly 6-10 ml per spoonful. "
            "Use canonical English food keys when possible: rice, noodles, bread, corn, chicken, egg, tofu, meatball, dumpling, broccoli, carrot, bok_choy, apple, banana. "
            "For mixed food, do not only say mixed food. Break it down into visible components. "
            "Return only valid JSON with fields: dominant_food_name, label_zh, food_group, estimated_grams, components, pace_hint, image_quality, bite_event, parent_observation. "
            "components must be an array of visible foods in the spoon, each with name, label_zh, food_group, estimated_grams. "
            "For example: components=[{name:'rice', label_zh:'米饭', food_group:'主食', estimated_grams:5}, {name:'broccoli', label_zh:'西兰花', food_group:'蔬菜', estimated_grams:2}]. "
            "food_group must be one of: 主食, 蛋白质, 蔬菜, 水果, 混合, 未知. "
            "pace_hint must be one of: slow, normal, fast, unknown. "
            "image_quality must contain spoon_visible, food_visible, clarity, is_valid_bite, quality_score. "
            "bite_event must contain is_new_bite, duplicate_of_previous, discard_reason. "
            "Use Chinese for label_zh, discard_reason, and parent_observation."
        )

    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
    ]
    if mode != "premeal":
        previous = _last_accepted_frame(meal)
        if previous and previous.get("image_path") and Path(previous["image_path"]).exists():
            content.extend(
                [
                    {"type": "text", "text": "Previous accepted bite image:"},
                    {"type": "image_url", "image_url": {"url": _image_data_url(Path(previous["image_path"]))}},
                ]
            )

    response = client.chat.completions.create(
        model=_model_name(),
        messages=[{"role": "user", "content": content}],
        temperature=0.2,
    )

    text = response.choices[0].message.content or "{}"
    parsed = _extract_json_object(text)
    if mode == "premeal":
        parsed["identified_items"] = _normalize_identified_items(parsed.get("identified_items", []))
        nutrition = _nutrition_for_items(parsed.get("identified_items", []))
        parsed["nutrition_estimate"] = nutrition["totals"]
        parsed["planned_groups"] = nutrition["groups"]
    else:
        parsed = _enrich_frame_analysis(parsed)
    return _strip_removed_child_feedback(parsed)


def analyze_image(image_path: Path, mode: str, meal: dict[str, Any] | None = None) -> dict[str, Any]:
    if _model_mode() != "mock":
        try:
            result = _analyze_with_llm(image_path, mode, meal)
            result["success"] = True
            result["mode"] = _model_mode()
            result["model"] = _model_name()
            return _strip_removed_child_feedback(result)
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
    return _strip_removed_child_feedback(result)


def _get_or_create_meal(meal_id: str, device_id: str) -> dict[str, Any]:
    meal = MEALS.get(meal_id)
    if meal is None:
        meal = {
            "meal_id": meal_id,
            "device_id": device_id,
            "created_at": _now(),
            "premeal": None,
            "frames": [],
            "rejected_frames": [],
        }
        MEALS[meal_id] = meal
    return meal


def _sum_nutrition(frames: list[dict[str, Any]]) -> dict[str, float]:
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for frame in frames:
        nutrition = _nutrition_for_frame(frame)["totals"]
        for key in totals:
            totals[key] += float(nutrition.get(key, 0) or 0)
    return {key: round(value, 1) for key, value in totals.items()}


def _build_parent_recommendations(groups: dict[str, int], paces: dict[str, int], accepted_count: int) -> list[dict[str, str]]:
    if accepted_count == 0:
        return [
            {
                "priority": "high",
                "title": "先补充有效单口数据",
                "message": "当前还没有稳定识别到有效摄入口，建议检查摄像头角度、光线和勺面是否完整入镜。",
                "action": "让勺子在盛有食物时停留 1 秒左右，优先获得清晰样张。",
            }
        ]

    recommendations: list[dict[str, str]] = []
    if groups.get("蔬菜", 0) == 0:
        recommendations.append(
            {
                "priority": "high",
                "title": "下一餐优先补充蔬菜摄入",
                "message": "本餐有效单口中尚未观察到蔬菜成分，存在蔬菜摄入不足的风险。",
                "action": "可以把青菜切小，和孩子已接受的主食或丸子搭配成一小口，先从少量尝试开始。",
            }
        )
    if groups.get("主食", 0) >= 2 and groups.get("蛋白质", 0) == 0 and groups.get("混合", 0) == 0:
        recommendations.append(
            {
                "priority": "medium",
                "title": "关注主食比例",
                "message": "当前有效单口以主食成分为主，蛋白质类食物摄入证据不足。",
                "action": "下一餐可增加鸡蛋、豆腐或肉类，并观察孩子是否真正吃下。",
            }
        )
    if paces.get("fast", 0) > 0:
        recommendations.append(
            {
                "priority": "medium",
                "title": "放慢进食节奏",
                "message": "记录中出现偏快摄入节奏，可能影响咀嚼充分性和饱腹感判断。",
                "action": "家长可在孩子连续快速进食时提醒暂停、咀嚼或喝一小口水。",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "priority": "low",
                "title": "继续观察更多餐次",
                "message": "当前摄入结构暂未发现明显偏差，但单餐数据仍有限。",
                "action": "建议连续记录 3-5 餐，观察是否存在稳定的偏食模式。",
            }
        )
    return recommendations


def _build_long_term_advice(groups: dict[str, int], paces: dict[str, int], accepted_count: int) -> list[str]:
    advice: list[str] = []
    if accepted_count == 0:
        return ["先保证设备能稳定采集到有效单口，再开始判断长期饮食趋势。"]
    if groups.get("蔬菜", 0) == 0:
        advice.append("如果连续多餐都缺少蔬菜成分摄入，建议从孩子已接受的食物入手，少量混入蔬菜，逐步提高接受度。")
    if groups.get("主食", 0) > groups.get("蔬菜", 0) + groups.get("蛋白质", 0) + groups.get("混合", 0):
        advice.append("若多餐都以主食为主，需要关注餐食结构是否过于单一，并增加蛋白质与蔬菜类小口。")
    if paces.get("fast", 0) > 0:
        advice.append("若经常出现进食偏快，可通过分段进食、暂停咀嚼提醒等方式帮助孩子建立稳定节奏。")
    if not advice:
        advice.append("建议连续记录 7 天以上，用多餐数据判断真实偏好，避免根据单餐偶然情况做结论。")
    return advice


def _build_today_meal_summary(
    meal: dict[str, Any],
    groups: dict[str, int],
    paces: dict[str, int],
    actual_nutrition: dict[str, float],
    deviation: list[str],
    attribution: str,
) -> dict[str, Any]:
    accepted_count = len(meal.get("frames", []))
    rejected_count = len(meal.get("rejected_frames", []))
    uploaded_count = accepted_count + rejected_count
    if accepted_count == 0:
        message = "本餐暂未识别到稳定的有效摄入口，建议优先检查摄像头角度和勺面是否完整入镜。"
    else:
        structure_text = "、".join(f"含{name}成分{count}次" for name, count in groups.items()) or "暂无结构数据"
        message = f"本餐识别到 {accepted_count} 次有效摄入口，其中{structure_text}。{attribution}"

    return {
        "title": "今天这一餐的营养总结",
        "message": message,
        "nutrition": actual_nutrition,
        "intake_structure": groups,
        "intake_structure_note": "按有效单口是否包含某类成分统计；混合食物可能同时计入主食、蔬菜和蛋白质。",
        "pace_observation": paces,
        "deviation": deviation,
        "evidence": {
            "accepted_bites": accepted_count,
            "uploaded_frames": uploaded_count,
            "rejected_frames": rejected_count,
        },
    }


def _build_summary(meal: dict[str, Any]) -> dict[str, Any]:
    paces: dict[str, int] = {}
    frames = meal.get("frames", [])
    groups = _group_component_counts(frames)
    component_totals = _component_totals(frames)

    for frame in frames:
        pace = frame.get("pace_hint") or "unknown"
        paces[pace] = paces.get(pace, 0) + 1

    deviation: list[str] = []
    if groups and groups.get("蔬菜", 0) == 0:
        deviation.append("当前记录中未观察到蔬菜成分摄入，存在蔬菜摄入不足风险。")
    if groups.get("主食", 0) >= 2 and groups.get("蔬菜", 0) == 0:
        deviation.append("连续多口以主食为主，存在摄入结构失衡风险。")
    if paces.get("fast", 0) > 0:
        deviation.append("部分摄入节奏偏快，可引导孩子慢一点吃。")
    if not deviation:
        deviation.append("当前摄入结构暂未发现明显偏差，可继续观察更多单口数据。")

    if not groups:
        attribution = "当前有效单口数量不足，暂不进行偏食归因。"
    elif groups.get("蔬菜", 0) == 0:
        attribution = "主要表现为实际摄入偏好问题：孩子连续多口未摄入蔬菜成分。"
    else:
        attribution = "当前偏差较轻，建议继续累计更多餐次观察。"

    actual_nutrition = _sum_nutrition(frames)
    recommendations = _build_parent_recommendations(groups, paces, len(frames))
    long_term_advice = _build_long_term_advice(groups, paces, len(frames))
    risk_level = "attention" if any(item["priority"] == "high" for item in recommendations) else "normal"
    premeal = meal.get("premeal") or {}
    parent_summary = " ".join(deviation + [attribution])
    today_summary = _build_today_meal_summary(meal, groups, paces, actual_nutrition, deviation, attribution)
    return {
        "meal_id": meal["meal_id"],
        "captured_frames": len(frames),
        "uploaded_frames": len(frames) + len(meal.get("rejected_frames", [])),
        "rejected_frames": len(meal.get("rejected_frames", [])),
        "risk_level": risk_level,
        "planned_nutrition_estimate": premeal.get("nutrition_estimate", {}),
        "actual_nutrition_estimate": actual_nutrition,
        "planned_structure": premeal.get("structure_assessment", {}),
        "actual_intake_proxy": groups,
        "component_totals": component_totals,
        "display_food_items": _display_food_items(component_totals),
        "pace_observation": paces,
        "deviation_analysis": deviation,
        "attribution": attribution,
        "recommendations": recommendations,
        "long_term_advice": long_term_advice,
        "parent_feedback": {
            "today_meal_summary": today_summary,
            "tonight_suggestion": recommendations,
            "long_term_advice": long_term_advice,
            "trend_summary": "趋势分析需要累计多餐记录，可通过 /api/trends 获取近 7 天、14 天和 30 天概览。",
        },
        "event_filtering": {
            "method": "time_gate_plus_llm_valid_bite",
            "min_bite_interval_seconds": MIN_BITE_INTERVAL_SECONDS,
            "accepted_frames": len(frames),
            "rejected_frames": len(meal.get("rejected_frames", [])),
        },
        "parent_summary": parent_summary,
    }


def _meal_snapshot(meal: dict[str, Any]) -> dict[str, Any]:
    return {
        "meal_id": meal.get("meal_id"),
        "device_id": meal.get("device_id"),
        "created_at": meal.get("created_at") or _now(),
        "updated_at": _now(),
        "meal": meal,
        "summary": _build_summary(meal),
    }


def _upsert_meal_history(meal: dict[str, Any]) -> None:
    meal_id = meal.get("meal_id")
    if not meal_id:
        return
    records = _read_history_records()
    snapshot = _meal_snapshot(meal)
    for index, record in enumerate(records):
        if record.get("meal_id") == meal_id:
            records[index] = snapshot
            break
    else:
        records.append(snapshot)
    records.sort(key=lambda record: record.get("created_at", ""))
    _write_history_records(records)


def _load_history_into_memory() -> None:
    for record in _read_history_records():
        meal = record.get("meal")
        if isinstance(meal, dict) and meal.get("meal_id") and meal["meal_id"] not in MEALS:
            MEALS[meal["meal_id"]] = meal


def _all_meal_snapshots() -> list[dict[str, Any]]:
    _load_history_into_memory()
    snapshots_by_id: dict[str, dict[str, Any]] = {}
    for record in _read_history_records():
        meal_id = record.get("meal_id")
        if meal_id:
            snapshots_by_id[meal_id] = record
    for meal in MEALS.values():
        if meal.get("meal_id"):
            snapshots_by_id[meal["meal_id"]] = _meal_snapshot(meal)
    return sorted(snapshots_by_id.values(), key=lambda record: record.get("created_at", ""))


def _round_nutrition(values: dict[str, float]) -> dict[str, float]:
    return {key: round(float(value or 0), 1) for key, value in values.items()}


def _build_trend(days: int) -> dict[str, Any]:
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    records = []
    for record in _all_meal_snapshots():
        created_at = _parse_local_datetime(record.get("created_at"))
        if created_at and created_at >= cutoff:
            records.append(record)

    group_counts: dict[str, int] = {}
    pace_counts: dict[str, int] = {}
    food_counts: dict[str, int] = {}
    nutrition_totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    accepted_bites = 0
    uploaded_frames = 0
    rejected_frames = 0
    attention_meals = 0
    vegetable_missing_meals = 0

    for record in records:
        meal = record.get("meal") or {}
        summary = record.get("summary") or _build_summary(meal)
        accepted_bites += int(summary.get("captured_frames", 0) or 0)
        uploaded_frames += int(summary.get("uploaded_frames", 0) or 0)
        rejected_frames += int(summary.get("rejected_frames", 0) or 0)
        if summary.get("risk_level") == "attention":
            attention_meals += 1
        groups = summary.get("actual_intake_proxy") or {}
        if groups and groups.get("蔬菜", 0) == 0:
            vegetable_missing_meals += 1
        for group, count in groups.items():
            group_counts[group] = group_counts.get(group, 0) + int(count or 0)
        for pace, count in (summary.get("pace_observation") or {}).items():
            pace_counts[pace] = pace_counts.get(pace, 0) + int(count or 0)
        for key, value in (summary.get("actual_nutrition_estimate") or {}).items():
            nutrition_totals[key] = nutrition_totals.get(key, 0.0) + float(value or 0)
        for item in (summary.get("display_food_items") or _display_food_items(summary.get("component_totals") or {})):
            label = item.get("label_zh") or "未知"
            food_counts[label] = food_counts.get(label, 0) + int(item.get("count", 0) or 0)

    meal_count = len(records)
    if meal_count == 0:
        summary_text = f"近 {days} 天暂无历史餐次数据，建议先完成至少 1 餐记录。"
        trend_recommendations = ["先累计稳定餐次数据，再判断饮食偏好趋势。"]
    else:
        top_group = max(group_counts.items(), key=lambda item: item[1])[0] if group_counts else "暂无"
        summary_text = (
            f"近 {days} 天共记录 {meal_count} 餐、{accepted_bites} 次有效摄入口，"
            f"主要摄入类型为{top_group}。"
        )
        trend_recommendations = []
        if vegetable_missing_meals > 0:
            trend_recommendations.append(f"有 {vegetable_missing_meals} 餐未观察到蔬菜摄入，建议持续关注蔬菜接受度。")
        if attention_meals > 0:
            trend_recommendations.append(f"{attention_meals} 餐被标记为需要关注，建议结合真实餐盘情况复核。")
        if not trend_recommendations:
            trend_recommendations.append("近期摄入结构暂未出现明显持续偏差，可继续观察。")

    average_nutrition = {
        key: round(value / meal_count, 1) if meal_count else 0.0 for key, value in nutrition_totals.items()
    }
    return {
        "period": {
            "days": days,
            "from": cutoff.strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
        },
        "meal_count": meal_count,
        "accepted_bites": accepted_bites,
        "uploaded_frames": uploaded_frames,
        "rejected_frames": rejected_frames,
        "group_distribution": group_counts,
        "pace_distribution": pace_counts,
        "top_foods": dict(sorted(food_counts.items(), key=lambda item: item[1], reverse=True)[:5]),
        "nutrition_total": _round_nutrition(nutrition_totals),
        "nutrition_average_per_meal": average_nutrition,
        "risk_summary": {
            "attention_meals": attention_meals,
            "vegetable_missing_meals": vegetable_missing_meals,
        },
        "trend_summary": summary_text,
        "recommendations": trend_recommendations,
    }


def _latest_meal() -> dict[str, Any] | None:
    _load_history_into_memory()
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
          {% set actual_nutrition = summary.get('actual_nutrition_estimate', nutrition) %}
          <div class="grid">
            <div>
              <div class="card">
                <h2>本餐概览</h2>
                <div class="chips">
                  <div class="chip">Meal ID：{{ meal.get('meal_id') }}</div>
                  <div class="chip">设备：{{ meal.get('device_id') }}</div>
                  <div class="chip">有效小口：{{ meal.get('frames', [])|length }} 次</div>
                  <div class="chip">已过滤：{{ meal.get('rejected_frames', [])|length }} 帧</div>
                </div>
                <div class="stats">
                  <div class="stat">累计热量估计<b>{{ actual_nutrition.get('kcal', '-') }}</b></div>
                  <div class="stat">累计蛋白质<b>{{ actual_nutrition.get('protein', '-') }}</b></div>
                  <div class="stat">累计碳水<b>{{ actual_nutrition.get('carbs', '-') }}</b></div>
                  <div class="stat">累计脂肪<b>{{ actual_nutrition.get('fat', '-') }}</b></div>
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
                <h2>家长行动建议</h2>
                <div class="list">
                {% for item in summary.get('recommendations', []) %}
                  <div class="item"><span>{{ item.get('title') }}：{{ item.get('message') }}</span><span>{{ item.get('priority') }}</span></div>
                {% else %}
                  <div class="item">暂无建议</div>
                {% endfor %}
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>长期建议</h2>
                <div class="list">
                {% for advice in summary.get('long_term_advice', []) %}
                  <div class="item"><span>{{ advice }}</span></div>
                {% else %}
                  <div class="item">暂无长期建议</div>
                {% endfor %}
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>成分摄入结构</h2>
                <div class="sub" style="margin-bottom:12px">按有效单口是否包含某类成分统计，混合食物可同时计入多类。</div>
                <div class="list">
                {% for key, value in summary.get('actual_intake_proxy', {}).items() %}
                  <div class="item"><span>含{{ key }}成分</span><span>{{ value }} 次</span></div>
                {% else %}
                  <div class="item">暂无数据</div>
                {% endfor %}
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>混合食物成分</h2>
                <div class="list">
                {% for key, item in summary.get('component_totals', {}).items() %}
                  <div class="item"><span>{{ item.get('label_zh') }} / {{ item.get('food_group') }}</span><span>{{ item.get('count') }} 次 · {{ item.get('estimated_grams') }}g</span></div>
                {% else %}
                  <div class="item">暂无成分拆解</div>
                {% endfor %}
                </div>
              </div>
              <div style="height:24px"></div>
              <div class="card">
                <h2>过滤说明</h2>
                <div class="list">
                {% for frame in meal.get('rejected_frames', []) %}
                  <div class="item"><span>Rejected {{ loop.index }}</span><span>{{ frame.get('gate_reason') }}</span></div>
                {% else %}
                  <div class="item">暂无过滤帧</div>
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
    return jsonify({"success": True, "meal": _meal_for_response(meal), "summary": _build_summary(meal) if meal else None})


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
    _upsert_meal_history(meal)
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
    captured_ts = time.time()
    analysis = analyze_image(image_path, "frame", meal)
    gate = _frame_gate(meal, analysis, captured_ts)
    frame_record = {
        **analysis,
        "image_path": str(image_path),
        "captured_at": _now(captured_ts),
        "captured_ts": captured_ts,
        "accepted": gate["accepted"],
        "gate_reason": gate["reason"],
    }

    if gate["accepted"]:
        meal["frames"].append(frame_record)
        _upsert_meal_history(meal)
        return jsonify(
            {
                "success": True,
                "meal_id": meal_id,
                "accepted": True,
                "frame_index": len(meal["frames"]) - 1,
                "analysis": analysis,
                "gate": gate,
            }
        )

    meal["rejected_frames"].append(frame_record)
    _upsert_meal_history(meal)
    return jsonify(
        {
            "success": True,
            "meal_id": meal_id,
            "accepted": False,
            "rejected_index": len(meal["rejected_frames"]) - 1,
            "analysis": analysis,
            "gate": gate,
        }
    )


@app.post("/api/summary")
def summary():
    data = request.get_json(silent=True) or {}
    meal_id = data.get("meal_id")
    _load_history_into_memory()
    if not meal_id or meal_id not in MEALS:
        return jsonify({"success": False, "error": "meal not found"}), 404
    _upsert_meal_history(MEALS[meal_id])
    return jsonify({"success": True, "summary": _build_summary(MEALS[meal_id])})


@app.get("/api/trends")
def trends():
    days_arg = request.args.get("days")
    if days_arg:
        try:
            days = max(1, min(365, int(days_arg)))
        except ValueError:
            return jsonify({"success": False, "error": "days must be an integer"}), 400
        return jsonify({"success": True, "trend": _build_trend(days)})

    return jsonify(
        {
            "success": True,
            "trends": {
                "7d": _build_trend(7),
                "14d": _build_trend(14),
                "30d": _build_trend(30),
            },
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True, use_reloader=False)
