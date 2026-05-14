/**
 * Upload test sketch for XIAO ESP32S3 Sense + OV5640
 *
 * Serial commands:
 *   c -> capture one spoonful frame and upload to /api/premeal
 *   h -> help
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_BASE_URL = "http://YOUR_COMPUTER_IP:5000";
const char* DEVICE_ID = "child-spoon-01";

// XIAO ESP32S3 Sense + OV5640 pins
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
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
  }

#ifdef CAMERA_FB_IN_PSRAM
  config.fb_location = CAMERA_FB_IN_PSRAM;
#endif

#ifdef CAMERA_GRAB_LATEST
  config.grab_mode = CAMERA_GRAB_LATEST;
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
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
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
    delay(50);
  }
  return esp_camera_fb_get();
}

String newMealId() {
  uint32_t chip = (uint32_t)(ESP.getEfuseMac() & 0xFFFFFF);
  unsigned long nowSec = millis() / 1000UL;
  char buf[40];
  snprintf(buf, sizeof(buf), "meal-%06lx-%lu", (unsigned long)chip, nowSec);
  return String(buf);
}

String uploadPremeal(camera_fb_t* fb) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      return "{\"success\":false,\"error\":\"wifi_not_connected\"}";
    }
  }

  String mealId = newMealId();
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
    "Content-Disposition: form-data; name=\"stage\"\r\n\r\npremeal";

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

  HTTPClient http;
  WiFiClient client;
  String url = String(SERVER_BASE_URL) + "/api/premeal";
  if (!http.begin(client, url)) {
    free(body);
    return "{\"success\":false,\"error\":\"http_begin_failed\"}";
  }

  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  http.setTimeout(30000);

  Serial.printf("[HTTP] uploading to %s\n", url.c_str());
  int httpCode = http.POST(body, totalLen);
  free(body);

  String response;
  if (httpCode > 0) {
    response = http.getString();
    Serial.printf("[HTTP] status=%d\n", httpCode);
  } else {
    response = "{\"success\":false,\"error\":\"post_failed\"}";
    Serial.printf("[HTTP] error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
  return response;
}

void captureAndUpload() {
  setStatusLed(true);
  camera_fb_t* fb = getFreshFrame();
  if (!fb) {
    Serial.println("[Camera] capture failed");
    setStatusLed(false);
    return;
  }

  Serial.printf("[Camera] captured %u bytes\n", (unsigned int)fb->len);
  String response = uploadPremeal(fb);
  esp_camera_fb_return(fb);
  setStatusLed(false);

  Serial.println("[Server] response:");
  Serial.println(response);
}

void printHelp() {
  Serial.println();
  Serial.println("=== Upload Test Demo ===");
  Serial.println("c : capture one frame and upload");
  Serial.println("h : help");
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(2500);

  if (STATUS_LED_PIN >= 0) {
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);
  }

  Serial.println("\n=== XIAO ESP32S3 Sense Upload Demo ===");
  connectWiFi();

  if (!initCamera()) {
    Serial.println("[Fatal] camera init failed");
    while (true) {
      delay(1000);
    }
  }

  printHelp();
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    if (cmd == 'c') {
      captureAndUpload();
    } else if (cmd == 'h') {
      printHelp();
    }
  }
  delay(20);
}
