# Child Spoon Demo

儿童勺具配件原型项目。系统通过安装在勺柄尾端的摄像头识别每一口勺中食物，连续记录儿童真实摄入序列，并在家长端展示摄入结构、偏食倾向和进食节奏观察。

## Repository Structure

```text
child_spoon_demo/
  backend/                         Flask backend and parent dashboard
    server.py
    requirements.txt
    .env.example
    uploads/                       Runtime uploads, ignored by git
  firmware/
    child_spoon_demo/              Full Arduino sketch
    child_spoon_demo_minimal/      Camera/Wi-Fi smoke test
    child_spoon_demo_upload/       One-shot upload test
  docs/                            API notes, diagrams, PPT assets
```

## Hardware

- Seeed Studio XIAO ESP32S3 Sense
- OV5640 camera module
- 3.7V LiPo battery connected to `BAT+` and `GND`

## Backend Setup

```powershell
cd C:\Users\yichen\Desktop\child_spoon_demo\backend
python -m pip install -r requirements.txt
python server.py
```

Open the parent dashboard:

```text
http://127.0.0.1:5000/
```

API notes for the parent-side frontend are in `docs/API.md`.

For parent-side frontend integration, use:

```text
GET http://127.0.0.1:5000/api/latest
```

If the frontend runs on another device in the same Wi-Fi network, replace `127.0.0.1` with the computer's LAN IP, for example `http://YOUR_COMPUTER_IP:5000/api/latest`.

Health check:

```text
http://127.0.0.1:5000/health
```

The backend runs in `mock` mode by default. To use Alibaba Cloud Bailian / DashScope vision models, create `backend/.env` from `backend/.env.example` and fill in your own API key:

```powershell
cd C:\Users\yichen\Desktop\child_spoon_demo\backend
Copy-Item .env.example .env
notepad .env
python server.py
```

Recommended Bailian settings:

```text
DASHSCOPE_API_KEY=your_bailian_key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-vl-plus
```

You can also set the variables in PowerShell before starting the server:

```powershell
$env:DASHSCOPE_API_KEY="your_bailian_key"
$env:OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL="qwen-vl-plus"
python server.py
```

Do not commit real API keys. `backend/.env` is ignored by git; `backend/.env.example` is only a template. If `/health` returns `"mode": "bailian"`, the backend is using the real Bailian vision API.

To test the real model with the latest uploaded spoon photo:

```powershell
cd C:\Users\yichen\Desktop\child_spoon_demo\backend
python test_latest_image.py premeal
python test_latest_image.py frame
```

## Firmware Setup

Open the full sketch in Arduino IDE:

```text
firmware/child_spoon_demo/child_spoon_demo.ino
```

Before uploading, fill in:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_BASE_URL = "http://YOUR_COMPUTER_IP:5000";
```

Recommended Arduino IDE settings:

- Board: `XIAO_ESP32S3`
- PSRAM: `OPI PSRAM`
- Partition Scheme: `Maximum APP (7.9MB APP No OTA/No FS)`
- Upload Speed: `115200`
- Serial Monitor baud rate: `115200`

Serial commands:

```text
p : first-bite scan
m : start meal session
f : upload one spoonful frame
e : end meal session and request summary
h : help
```

Wireless spoon demo mode:

- Use USB-C only for firmware upload and debugging.
- During the meal demo, power the board from a 3.7V LiPo battery. Communication still uses Wi-Fi HTTP upload to the Flask backend.
- The full sketch stays idle after boot by default. Press the optional record button, or send `m` over Serial while debugging, to start capture/upload.
- `RECORD_BUTTON_PIN` is `D1` by default. Connect a push button between `D1` and `GND`; the internal pull-up is enabled in firmware.
- After start, the device captures the first bite after `AUTO_FIRST_BITE_DELAY_MS`, uploads spoonful frames every `MEAL_FRAME_INTERVAL_MS`, and requests a summary after `AUTO_SUMMARY_AFTER_FRAMES` frames.
- Set `WIRELESS_AUTO_DEMO_MODE` to `true` only if you want the device to start recording immediately after battery power-on.

## Debugging Notes

- If upload fails with `COM port busy`, close Serial Monitor, unplug/replug the board, and reselect the port.
- If the device prints `connection refused`, update `SERVER_BASE_URL` to the current IPv4 address of the computer running `backend/server.py`.
- If OpenAI calls return quota errors, the backend falls back to mock data so the classroom demo can still run.
- Runtime images are stored in `backend/uploads/` and ignored by git.

## Current Prototype Scope

This is a classroom demo prototype. It validates the flow from spoonful image capture to cloud analysis and parent-side visualization. Nutrition values are approximate and not medical-grade measurements.
