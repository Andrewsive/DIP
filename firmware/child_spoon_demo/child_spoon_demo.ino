/**
 * Child Spoon Demo - full flow version
 * Hardware: Seeed Studio XIAO ESP32S3 Sense + OV5640
 *
 * Serial commands:
 *   p -> first-bite scan
 *   m -> start meal session
 *   f -> upload one spoonful frame
 *   e -> end meal session and request summary
 *   h -> help
 *
 * Wireless spoon demo mode:
 *   The device stays idle after battery power-on. Press the optional record
 *   button, or send "m" over Serial while debugging, to start capture/upload.
 *   After start, it captures the first bite, uploads several spoonful frames,
 *   and then requests a summary automatically.
 *
 * Important:
 * Put this .ino in its own Arduino sketch folder.
 * Do not compile it in the same folder with other standalone .ino files.
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// =========================
// User configuration
// =========================
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Example:
// const char* SERVER_BASE_URL = "http://192.168.31.20:5000";
// or use your cpolar/ngrok https URL:
// const char* SERVER_BASE_URL = "https://your-public-host";
const char* SERVER_BASE_URL = "http://YOUR_COMPUTER_IP:5000";

// Optional: set a friendly device name
const char* DEVICE_ID = "child-spoon-01";

// Wireless/battery demo settings.
const bool WIRELESS_AUTO_DEMO_MODE = true;   // true starts recording immediately after boot.
const int RECORD_BUTTON_PIN = D1;            // Connect button between D1 and GND. Set to -1 to disable.
const unsigned long AUTO_FIRST_BITE_DELAY_MS = 12000UL;
const unsigned long AUTO_NEXT_MEAL_DELAY_MS = 15000UL;
const bool AUTO_RESTART_AFTER_SUMMARY = false;
const int AUTO_SUMMARY_AFTER_FRAMES = 0;  // 0 keeps one meal active until button/Serial end.

// For automatic spoonful sampling after meal start.
const unsigned long MEAL_FRAME_INTERVAL_MS = 8000UL;

// =========================
// Camera pins for XIAO ESP32S3 Sense + OV5640
// Based on Seeed camera examples.
// =========================
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39
#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

// =========================
// State
// =========================
String currentMealId = "";
bool mealActive = false;
bool firstBiteUploaded = false;
int uploadedFrameCount = 0;
unsigned long lastMealFrameAt = 0;
unsigned long nextAutoFirstBiteAt = 0;
unsigned long nextAutoMealAt = 0;
bool lastRecordButtonState = HIGH;

#ifdef LED_BUILTIN
const int STATUS_LED_PIN = LED_BUILTIN;
#else
const int STATUS_LED_PIN = -1;
#endif

void setStatusLed(bool on) {
  if (STATUS_LED_PIN >= 0) {
    digitalWrite(STATUS_LED_PIN, on ? HIGH : LOW);
  }
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
  } else {
    config.frame_size = FRAMESIZE_QQVGA;
    config.jpeg_quality = 18;
    config.fb_count = 1;
  }

#ifdef CAMERA_FB_IN_PSRAM
  config.fb_location = CAMERA_FB_IN_PSRAM;
#endif

#ifdef CAMERA_GRAB_WHEN_EMPTY
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
#endif

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[Camera] init failed: 0x%x\n", err);
    return false;
  }

  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, 0);
  }

  Serial.println("[Camera] ready");
  return true;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] connected, IP=%s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("[WiFi] connection failed");
  }
}

camera_fb_t* getFreshFrame() {
  for (int i = 0; i < 2; i++) {
    camera_fb_t* throwaway = esp_camera_fb_get();
    if (throwaway) {
      esp_camera_fb_return(throwaway);
    }
    delay(60);
  }
  return esp_camera_fb_get();
}

String uploadMultipart(camera_fb_t* fb, const String& endpoint, const String& mealId, const String& stage) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      return "{\"success\":false,\"error\":\"wifi_not_connected\"}";
    }
  }

  String boundary = "----XIAOSpoonBoundary";
  String bodyHead =
    "--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"photo\"; filename=\"capture.jpg\"\r\n"
    "Content-Type: image/jpeg\r\n\r\n";

  String bodyMiddle =
    "\r\n--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"device_id\"\r\n\r\n" + String(DEVICE_ID) +
    "\r\n--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"meal_id\"\r\n\r\n" + mealId +
    "\r\n--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"stage\"\r\n\r\n" + stage;

  String bodyTail = "\r\n--" + boundary + "--\r\n";
  size_t totalLen = bodyHead.length() + fb->len + bodyMiddle.length() + bodyTail.length();

  uint8_t* body = (uint8_t*)malloc(totalLen);
  if (!body) {
    return "{\"success\":false,\"error\":\"malloc_failed\"}";
  }

  size_t pos = 0;
  memcpy(body + pos, bodyHead.c_str(), bodyHead.length());
  pos += bodyHead.length();
  memcpy(body + pos, fb->buf, fb->len);
  pos += fb->len;
  memcpy(body + pos, bodyMiddle.c_str(), bodyMiddle.length());
  pos += bodyMiddle.length();
  memcpy(body + pos, bodyTail.c_str(), bodyTail.length());

  String url = String(SERVER_BASE_URL) + endpoint;
  HTTPClient http;
  WiFiClient client;

  if (!http.begin(client, url)) {
    free(body);
    return "{\"success\":false,\"error\":\"http_begin_failed\"}";
  }

  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  http.setTimeout(30000);

  Serial.printf("[HTTP] POST %s (%u bytes)\n", url.c_str(), (unsigned int)fb->len);
  int httpCode = http.POST(body, totalLen);
  free(body);

  String response;
  if (httpCode > 0) {
    response = http.getString();
  } else {
    response = "{\"success\":false,\"error\":\"post_failed\"}";
    Serial.printf("[HTTP] error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
  return response;
}

String postJsonSummary() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      return "{\"success\":false,\"error\":\"wifi_not_connected\"}";
    }
  }

  String url = String(SERVER_BASE_URL) + "/api/summary";
  String payload = "{\"meal_id\":\"" + currentMealId + "\",\"device_id\":\"" + String(DEVICE_ID) + "\"}";

  HTTPClient http;
  WiFiClient client;
  if (!http.begin(client, url)) {
    return "{\"success\":false,\"error\":\"http_begin_failed\"}";
  }

  http.addHeader("Content-Type", "application/json");
  http.setTimeout(20000);
  int httpCode = http.POST(payload);

  String response;
  if (httpCode > 0) {
    response = http.getString();
  } else {
    response = "{\"success\":false,\"error\":\"post_failed\"}";
  }

  http.end();
  return response;
}

String newMealId() {
  uint32_t chip = (uint32_t)(ESP.getEfuseMac() & 0xFFFFFF);
  unsigned long nowSec = millis() / 1000UL;
  char buf[40];
  snprintf(buf, sizeof(buf), "meal-%06lx-%lu", (unsigned long)chip, nowSec);
  return String(buf);
}

bool uploadSucceeded(const String& response) {
  return response.indexOf("\"success\":true") >= 0 || response.indexOf("\"success\": true") >= 0;
}

bool doPremealScan() {
  if (currentMealId.length() == 0) {
    currentMealId = newMealId();
  }
  Serial.printf("[Meal] first-bite scan, meal_id=%s\n", currentMealId.c_str());

  setStatusLed(true);
  camera_fb_t* fb = getFreshFrame();
  if (!fb) {
    Serial.println("[Camera] first-bite capture failed");
    setStatusLed(false);
    return false;
  }

  String response = uploadMultipart(fb, "/api/premeal", currentMealId, "premeal");
  esp_camera_fb_return(fb);
  setStatusLed(false);

  Serial.println("[Meal] first-bite result:");
  Serial.println(response);
  bool ok = uploadSucceeded(response);
  firstBiteUploaded = ok;
  if (!ok) {
    Serial.println("[Meal] first-bite upload failed, will retry");
  }
  return ok;
}

void startMealSession() {
  if (currentMealId.length() == 0) {
    currentMealId = newMealId();
    firstBiteUploaded = false;
    uploadedFrameCount = 0;
  }
  mealActive = true;
  lastMealFrameAt = millis();
  nextAutoFirstBiteAt = millis() + AUTO_FIRST_BITE_DELAY_MS;
  Serial.printf("[Meal] started, meal_id=%s\n", currentMealId.c_str());
  Serial.printf("[Meal] first bite will capture in %lu ms\n", AUTO_FIRST_BITE_DELAY_MS);
}

bool uploadMealFrame() {
  if (!mealActive || currentMealId.length() == 0) {
    Serial.println("[Meal] no active meal session");
    return false;
  }

  setStatusLed(true);
  camera_fb_t* fb = getFreshFrame();
  if (!fb) {
    Serial.println("[Camera] meal frame capture failed");
    setStatusLed(false);
    return false;
  }

  String response = uploadMultipart(fb, "/api/frame", currentMealId, "inmeal");
  esp_camera_fb_return(fb);
  setStatusLed(false);

  Serial.println("[Meal] frame result:");
  Serial.println(response);
  bool ok = uploadSucceeded(response);
  if (ok) {
    uploadedFrameCount++;
  } else {
    Serial.println("[Meal] frame upload failed, not counted");
  }
  return ok;
}

void endMealSession() {
  if (currentMealId.length() == 0) {
    Serial.println("[Meal] nothing to summarize");
    return;
  }

  mealActive = false;
  String response = postJsonSummary();
  Serial.println("[Meal] summary:");
  Serial.println(response);
  currentMealId = "";
  firstBiteUploaded = false;
  uploadedFrameCount = 0;
  if (WIRELESS_AUTO_DEMO_MODE && AUTO_RESTART_AFTER_SUMMARY) {
    nextAutoMealAt = millis() + AUTO_NEXT_MEAL_DELAY_MS;
    Serial.printf("[Auto] next meal will start in %lu ms\n", AUTO_NEXT_MEAL_DELAY_MS);
  }
}

void printHelp() {
  Serial.println();
  Serial.println("=== Child Spoon Demo Commands ===");
  Serial.println("p : first-bite scan");
  Serial.println("m : start meal session");
  Serial.println("f : upload one spoonful frame");
  Serial.println("e : end meal and request summary");
  Serial.println("h : help");
  Serial.println("button : press record button to start/end a meal");
  Serial.printf("boot auto-start : %s\n", WIRELESS_AUTO_DEMO_MODE ? "on" : "off");
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(2500);

  if (STATUS_LED_PIN >= 0) {
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);
  }

  if (RECORD_BUTTON_PIN >= 0) {
    pinMode(RECORD_BUTTON_PIN, INPUT_PULLUP);
    lastRecordButtonState = digitalRead(RECORD_BUTTON_PIN);
  }

  Serial.println("\n=== Child Spoon Demo Boot ===");
  if (!initCamera()) {
    Serial.println("[Fatal] camera init failed");
    while (true) {
      delay(1000);
    }
  }

  connectWiFi();
  printHelp();

  if (WIRELESS_AUTO_DEMO_MODE) {
    startMealSession();
    Serial.println("[Auto] boot auto-start enabled");
  } else {
    Serial.println("[Auto] idle after boot; press button or send 'm' to start");
  }
}

void loop() {
  if (RECORD_BUTTON_PIN >= 0) {
    bool currentButtonState = digitalRead(RECORD_BUTTON_PIN);
    if (lastRecordButtonState == HIGH && currentButtonState == LOW) {
      if (mealActive) {
        endMealSession();
      } else {
        startMealSession();
      }
      delay(250);
    }
    lastRecordButtonState = currentButtonState;
  }

  if (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    if (cmd == 'p') {
      doPremealScan();
      lastMealFrameAt = millis();
    } else if (cmd == 'm') {
      startMealSession();
    } else if (cmd == 'f') {
      uploadMealFrame();
    } else if (cmd == 'e') {
      endMealSession();
    } else if (cmd == 'h') {
      printHelp();
    }
  }

  unsigned long now = millis();

  if (WIRELESS_AUTO_DEMO_MODE && !mealActive && currentMealId.length() == 0 && nextAutoMealAt > 0 && now >= nextAutoMealAt) {
    startMealSession();
    nextAutoMealAt = 0;
  }

  if (mealActive && !firstBiteUploaded && now >= nextAutoFirstBiteAt) {
    bool ok = doPremealScan();
    lastMealFrameAt = now;
    if (!ok) {
      nextAutoFirstBiteAt = now + MEAL_FRAME_INTERVAL_MS;
    }
  }

  if (mealActive && firstBiteUploaded && now - lastMealFrameAt >= MEAL_FRAME_INTERVAL_MS) {
    lastMealFrameAt = now;
    uploadMealFrame();

    if (AUTO_SUMMARY_AFTER_FRAMES > 0 && uploadedFrameCount >= AUTO_SUMMARY_AFTER_FRAMES) {
      endMealSession();
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    connectWiFi();
  }

  delay(50);
}
