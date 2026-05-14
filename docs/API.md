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
3. The device uploads subsequent spoonful images to `/api/frame`.
4. The device calls `/api/summary` when the meal ends.
5. The parent app can render the returned JSON or use the dashboard at `/`.

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

`mode` is `openai` when `OPENAI_API_KEY` is set. If the API call fails, individual analysis results may fall back to mock data.

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
    "parent_message": "已识别当前这一口主要为主食，可继续累计多口结果后判断摄入结构。",
    "child_message": "小勺看到这一口啦，继续吃饭吧。"
  }
}
```

## POST /api/frame

Uploads one spoonful frame during the meal.

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
  "frame_index": 0,
  "analysis": {
    "dominant_food_name": "rice",
    "label_zh": "米饭",
    "food_group": "主食",
    "pace_hint": "normal",
    "child_message": "吃得真不错"
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
    "planned_nutrition_estimate": {
      "kcal": 20.9,
      "protein": 0.5,
      "carbs": 4.7,
      "fat": 0.1
    },
    "actual_intake_proxy": {
      "主食": 2,
      "蛋白质": 1
    },
    "pace_observation": {
      "normal": 2,
      "fast": 1
    },
    "deviation_analysis": [
      "当前记录中未观察到蔬菜摄入，存在蔬菜摄入不足风险。",
      "连续多口以主食为主，存在摄入结构失衡风险。"
    ],
    "attribution": "主要表现为实际摄入偏好问题：孩子连续多口未摄入蔬菜。",
    "parent_summary": "当前记录中未观察到蔬菜摄入，存在蔬菜摄入不足风险。",
    "child_feedback": "今天吃饭很认真，我们下次也试试换一口不同的食物吧。"
  }
}
```

## Dashboard

For classroom demo and quick debugging:

```text
GET /
```

This renders the latest meal in a browser. It is not the final parent app, but it is useful for checking backend data quickly.

