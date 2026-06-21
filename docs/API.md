# Parent App API

This document describes the backend APIs used by the parent-side app prototype.

## Base URL

Local development:

```text
http://127.0.0.1:5000
```

When the ESP32 board uploads images over Wi-Fi, use the computer's LAN IP:

```text
http://YOUR_COMPUTER_IP:5000
```

## Data Flow

1. The spoon device starts a meal session and captures the first spoonful.
2. The device uploads the first spoonful image to `/api/premeal`.
3. The device uploads subsequent candidate frames to `/api/frame`.
4. The backend uses a hybrid gate: minimum time interval + LLM valid-bite judgement.
5. Only accepted frames are counted as real spoonful intake; rejected frames are kept for debugging.
6. The device calls `/api/summary` when the meal ends.
7. The parent app can poll `/api/latest` to render the newest meal result, or use the dashboard at `/` for quick debugging.

## GET /health

Checks whether the backend is running and whether it is using mock or real model mode.

Example response:

```json
{
  "success": true,
  "mode": "mock",
  "meals_in_memory": 1
}
```

`mode` is `mock` by default, `bailian` when `DASHSCOPE_API_KEY` is set, and `openai` when `OPENAI_API_KEY` is set. If the real API call fails, individual analysis results may fall back to mock data and include `mode: "fallback_mock"` plus an `error` message.

## GET /api/latest

Returns the newest meal stored in backend memory. This is the easiest endpoint for the parent-side frontend demo because the ESP32 board writes data into the backend first, then the frontend only needs to read the latest state.

Example response:

```json
{
  "success": true,
  "meal": {
    "meal_id": "meal-abc123-10",
    "device_id": "child-spoon-01",
    "premeal": {},
    "frames": []
  },
  "summary": {}
}
```

For local frontend development, CORS headers are enabled by default. If needed, set `CORS_ALLOW_ORIGIN` in `backend/.env`.

`meal.frames` contains accepted valid spoonfuls. `meal.rejected_frames` contains uploaded images that were filtered out because they were too close in time, blurry, empty, repeated, or not a valid bite.

## POST /api/premeal

Uploads the first spoonful image. In the current concept, this is used as the first-bite recognition entry, not whole-plate scanning.

Content type:

```text
multipart/form-data
```

Fields:

```text
photo     required, JPEG image
meal_id   optional, string
device_id optional, string
stage     optional, string
```

Example response:

```json
{
  "success": true,
  "meal_id": "meal-abc123-10",
  "mode": "mock",
  "analysis": {
    "identified_items": [
      {
        "name": "rice",
        "label_zh": "米饭",
        "estimated_grams": 18
      }
    ],
    "nutrition_estimate": {
      "kcal": 20.9,
      "protein": 0.5,
      "carbs": 4.7,
      "fat": 0.1
    },
    "structure_assessment": {
      "main_food": "本口为主食",
      "protein": "未检测到",
      "vegetable": "未检测到",
      "balance": "单口信息不足以判断整餐"
    },
    "parent_message": "已识别当前这一口主要为主食，可继续累计多口结果后判断摄入结构。"
  }
}
```

## POST /api/frame

Uploads one candidate frame during the meal. The backend does not blindly count every image as a spoonful. It first applies a time gate and asks the LLM whether the frame is a valid new bite.

Content type:

```text
multipart/form-data
```

Fields:

```text
photo     required, JPEG image
meal_id   required, string
device_id optional, string
stage     optional, string
```

Example response:

```json
{
  "success": true,
  "meal_id": "meal-abc123-10",
  "accepted": true,
  "frame_index": 0,
  "gate": {
    "accepted": true,
    "reason": "通过时间过滤与大模型有效单口判断。"
  },
  "analysis": {
    "dominant_food_name": "rice",
    "canonical_food_name": "rice",
    "label_zh": "米饭",
    "food_group": "主食",
    "estimated_grams": 6,
    "components": [
      {
        "name": "rice",
        "canonical_food_name": "rice",
        "label_zh": "米饭",
        "food_group": "主食",
        "estimated_grams": 6
      }
    ],
    "nutrition_estimate": {
      "kcal": 7,
      "protein": 0.2,
      "carbs": 1.6,
      "fat": 0
    },
    "pace_hint": "normal",
    "image_quality": {
      "spoon_visible": true,
      "food_visible": true,
      "clarity": "clear",
      "is_valid_bite": true,
      "quality_score": 0.8
    },
    "bite_event": {
      "is_new_bite": true,
      "duplicate_of_previous": false,
      "discard_reason": ""
    },
    "parent_observation": "本口主要识别为米饭，归类为主食。"
  }
}
```

If the frame is uploaded successfully but filtered out:

```json
{
  "success": true,
  "meal_id": "meal-abc123-10",
  "accepted": false,
  "rejected_index": 0,
  "gate": {
    "accepted": false,
    "reason": "大模型判断该帧不是有效单口。"
  },
  "analysis": {
    "dominant_food_name": "未知",
    "label_zh": "未知",
    "food_group": "未知",
    "image_quality": {
      "spoon_visible": false,
      "food_visible": false,
      "clarity": "模糊",
      "is_valid_bite": false,
      "quality_score": 0.2
    }
  }
}
```

Common `food_group` values:

```text
主食
蛋白质
蔬菜
水果
混合
未知
```

Common `pace_hint` values:

```text
slow
normal
fast
unknown
```

## POST /api/summary

Requests the meal summary after a meal session ends.

Content type:

```text
application/json
```

Request body:

```json
{
  "meal_id": "meal-abc123-10",
  "device_id": "child-spoon-01"
}
```

Example response:

```json
{
  "success": true,
  "summary": {
    "meal_id": "meal-abc123-10",
    "captured_frames": 3,
    "uploaded_frames": 5,
    "rejected_frames": 2,
    "risk_level": "attention",
    "planned_nutrition_estimate": {
      "kcal": 20.9,
      "protein": 0.5,
      "carbs": 4.7,
      "fat": 0.1
    },
    "actual_nutrition_estimate": {
      "kcal": 46.5,
      "protein": 1.2,
      "carbs": 10.4,
      "fat": 0.1
    },
    "actual_intake_proxy": {
      "主食": 2,
      "蛋白质": 1,
      "蔬菜": 1
    },
    "component_totals": {
      "rice": {
        "canonical_food_name": "rice",
        "label_zh": "米饭",
        "food_group": "主食",
        "count": 2,
        "estimated_grams": 12
      },
      "broccoli": {
        "canonical_food_name": "broccoli",
        "label_zh": "西兰花",
        "food_group": "蔬菜",
        "count": 1,
        "estimated_grams": 3
      }
    },
    "display_food_items": [
      {
        "canonical_food_name": "rice",
        "label_zh": "米饭",
        "food_group": "主食",
        "count": 2,
        "estimated_grams": 12
      },
      {
        "canonical_food_name": "broccoli",
        "label_zh": "西兰花",
        "food_group": "蔬菜",
        "count": 1,
        "estimated_grams": 3
      }
    ],
    "pace_observation": {
      "normal": 2,
      "fast": 1
    },
    "deviation_analysis": [
      "当前摄入结构暂未发现明显偏差，可继续观察更多单口数据。",
      "连续多口以主食为主，存在摄入结构失衡风险。"
    ],
    "attribution": "当前偏差较轻，建议继续累计更多餐次观察。",
    "recommendations": [
      {
        "priority": "high",
        "title": "下一餐优先补充蔬菜摄入",
        "message": "本餐有效单口中尚未观察到蔬菜成分，存在蔬菜摄入不足的风险。",
        "action": "可以把青菜切小，和孩子已接受的主食或丸子搭配成一小口，先从少量尝试开始。"
      }
    ],
    "long_term_advice": [
      "如果连续多餐都缺少蔬菜成分摄入，建议从孩子已接受的食物入手，少量混入蔬菜，逐步提高接受度。"
    ],
    "parent_feedback": {
      "today_meal_summary": {
        "title": "今天这一餐的营养总结",
        "message": "本餐识别到 3 次有效摄入口，其中含主食成分2次、含蛋白质成分1次、含蔬菜成分1次。当前偏差较轻，建议继续累计更多餐次观察。",
        "nutrition": {
          "kcal": 46.5,
          "protein": 1.2,
          "carbs": 10.4,
          "fat": 0.1
        },
        "intake_structure": {
          "主食": 2,
          "蛋白质": 1,
          "蔬菜": 1
        },
        "intake_structure_note": "按有效单口是否包含某类成分统计；混合食物可能同时计入主食、蔬菜和蛋白质。",
        "evidence": {
          "accepted_bites": 3,
          "uploaded_frames": 5,
          "rejected_frames": 2
        }
      },
      "tonight_suggestion": [
        {
          "priority": "high",
          "title": "下一餐优先补充蔬菜摄入",
          "message": "本餐有效单口中尚未观察到蔬菜成分，存在蔬菜摄入不足的风险。",
          "action": "可以把青菜切小，和孩子已接受的主食或丸子搭配成一小口，先从少量尝试开始。"
        }
      ],
      "long_term_advice": [
        "如果连续多餐都缺少蔬菜成分摄入，建议从孩子已接受的食物入手，少量混入蔬菜，逐步提高接受度。"
      ],
      "trend_summary": "趋势分析需要累计多餐记录，可通过 /api/trends 获取近 7 天、14 天和 30 天概览。"
    },
    "event_filtering": {
      "method": "time_gate_plus_llm_valid_bite",
      "min_bite_interval_seconds": 4,
      "accepted_frames": 3,
      "rejected_frames": 2
    },
    "parent_summary": "当前摄入结构暂未发现明显偏差，可继续观察更多单口数据。"
  }
}
```

For parent-side UI, recommended fields are:

```text
summary.parent_summary
summary.recommendations
summary.parent_feedback
summary.long_term_advice
summary.actual_nutrition_estimate
summary.actual_intake_proxy
summary.component_totals
summary.display_food_items
summary.event_filtering
meal.frames[].components
meal.frames[].display_label_zh
meal.frames[].parent_observation
meal.frames[].nutrition_estimate
```

`summary.actual_intake_proxy` is component-based. It means “how many accepted bites contain this food group”, not exclusive bite counts. For mixed food, one bite may contain both `主食` and `蔬菜`.

For frontend food lists, prefer `summary.display_food_items` instead of counting `meal.frames[].label_zh`. `label_zh` may contain the raw model label such as `混合食物`, while `display_food_items` is already decomposed into concrete foods.

Recommended parent-side display mapping:

```text
今天这一餐的营养总结  -> summary.parent_feedback.today_meal_summary
今晚的建议            -> summary.parent_feedback.tonight_suggestion
长期建议              -> summary.parent_feedback.long_term_advice
趋势总结              -> GET /api/trends
```

## GET /api/trends

Returns trend summaries from persisted local meal snapshots. The backend stores snapshots in `backend/data/meal_history.json`, which is ignored by git.

Default response includes 7-day, 14-day, and 30-day summaries:

```text
GET /api/trends
```

You can also request a single period:

```text
GET /api/trends?days=7
```

Example response:

```json
{
  "success": true,
  "trends": {
    "7d": {
      "period": {
        "days": 7,
        "from": "2026-05-12",
        "to": "2026-05-19"
      },
      "meal_count": 3,
      "accepted_bites": 18,
      "uploaded_frames": 42,
      "rejected_frames": 24,
      "group_distribution": {
        "主食": 8,
        "混合": 7,
        "蔬菜": 3
      },
      "top_foods": {
        "米饭": 8,
        "丸子": 7,
        "青菜": 3
      },
      "nutrition_total": {
        "kcal": 188.4,
        "protein": 9.2,
        "carbs": 31.6,
        "fat": 5.8
      },
      "nutrition_average_per_meal": {
        "kcal": 62.8,
        "protein": 3.1,
        "carbs": 10.5,
        "fat": 1.9
      },
      "risk_summary": {
        "attention_meals": 2,
        "vegetable_missing_meals": 2
      },
      "trend_summary": "近 7 天共记录 3 餐、18 次有效摄入口，主要摄入类型为主食。",
      "recommendations": [
        "有 2 餐未观察到蔬菜摄入，建议持续关注蔬菜接受度。"
      ]
    }
  }
}
```

## Dashboard

For classroom demo and quick debugging:

```text
GET /
```

This renders the latest meal in a browser. It is not the final parent app, but it is useful for checking backend data quickly.
