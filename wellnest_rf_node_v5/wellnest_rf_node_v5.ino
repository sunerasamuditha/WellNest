/* =============================================================================
 *  WellNest / SilverGrove — Ambient Node  v5.0
 *  ESP32-S3  |  Arduino-ESP32 core 3.x  |  lib: arduinoWebSockets (Links2004)
 *
 *  WHAT IT DOES
 *    - Detects room presence from WiFi RSSI variance (real sensing, always on)
 *    - Prompts on Serial for a scenario: normal / mild / critical
 *    - POSTs the scenario to the WellNest backend, which runs the SAME
 *      health check your dashboard button runs, and broadcasts it to every
 *      connected dashboard (your Mac, a phone, a judge's laptop).
 *
 *  SET THREE THINGS BELOW: BACKEND_URL, RESIDENT_ID, and secrets.h
 *  Works with both  http://192.168.1.x:8180  and  https://...run.app
 * ========================================================================== */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <HTTPClient.h>
#include <math.h>

#include "secrets.h"   // WIFI_SSID, WIFI_PASSWORD

/* ============================ SET THESE ================================= */

// Cloud Run:  "https://your-service-xxxxx.us-central1.run.app"
// Local dev:  "http://192.168.1.157:8180"
static const char* BACKEND_URL = "https://wellnest-a2a-28869653773.us-central1.run.app";

// Must be one of: sriyani_001, kamal_002, nanda_003, ruwan_004
// Check the live list at:  <BACKEND_URL>/api/hw/residents
static const char* RESIDENT_ID = "sriyani_001";
static const char* NODE_ID     = "livingroom_node_01";

/* ============================ BUILD OPTIONS ============================= */
#define FORCE_TRAFFIC    0   // 1 = ~40 Hz RSSI sampling (validate router first)
#define AUTO_THRESHOLD   1   // derive trigger from measured room noise
#define POST_TELEMETRY   0   // 1 = also stream presence to /api/hw/telemetry
#define SHOW_RF_LOG      0   // 1 = print live RSSI lines (noisy during demo)

/* ============================ TIMING =================================== */
#if FORCE_TRAFFIC
  static const uint16_t SAMPLE_INTERVAL_MS = 25;
  static const uint16_t WINDOW_SIZE        = 120;
  static const uint16_t PROBE_INTERVAL_MS  = 22;
#else
  static const uint16_t SAMPLE_INTERVAL_MS = 110;
  static const uint16_t WINDOW_SIZE        = 28;
  static const uint16_t PROBE_INTERVAL_MS  = 0;
#endif

static const uint16_t WINDOW_MAX     = 160;
static const uint16_t WS_PERIOD_MS   = 100;
static const uint32_t POST_PERIOD_MS = 5000;
static const uint32_t HTTP_TIMEOUT_MS = 150000;   // agents can take 30-90 s

/* ============================ DETECTION TUNING ========================= */
static const uint32_t SETTLE_MS     = 20000;   // time to walk out of the room
static const uint32_t CALIB_MS      = 30000;
static const float    K_SIGMA       = 4.0f;
static const float    ABS_MIN_ENTER = 0.80f;
static const float    MANUAL_ENTER  = 2.50f;
static const float    EXIT_RATIO    = 0.60f;
static const float    MOVEMENT_MULT = 2.50f;
static const uint8_t  VOTE_WINDOW   = 5;
static const uint8_t  VOTE_ENTER    = 3;
static const uint32_t HOLD_MS_DEF   = 15000;

static const float BASELINE_ALPHA = 0.0008f;
static const float BASELINE_GATE  = 2.00f;
static const float BASELINE_MIN   = 0.02f;
static const float BASELINE_MAX   = 4.00f;
static const float SPIKE_LIMIT_DB = 15.0f;
static const int8_t RSSI_VALID_HI = -10;
static const int8_t RSSI_VALID_LO = -95;

static const int LED_PIN = 48;   // WS2812 on ESP32-S3 DevKitC-1

/* ============================ STATE ==================================== */
struct Snapshot {
  float rssi, mean, variance, baseline, adjusted, ratio;
  float enterT, exitT, moveT, intensity;
  bool  present, moving, calibrated, linkUp;
  float sampleHz, dupRatio;
  uint32_t samples, uptimeS, calibRemainS;
};

static Snapshot      g_snap = {};
static portMUX_TYPE  g_mux  = portMUX_INITIALIZER_UNLOCKED;
static QueueHandle_t g_postQ = nullptr;
static QueueHandle_t g_scenarioQ = nullptr;

static volatile float    g_enterT = MANUAL_ENTER;
static volatile float    g_exitT  = MANUAL_ENTER * EXIT_RATIO;
static volatile float    g_moveT  = MANUAL_ENTER * MOVEMENT_MULT;
static volatile uint32_t g_holdMs = HOLD_MS_DEF;
static volatile bool     g_recalRequested = false;
static volatile bool     g_busy = false;          // a check is running
static volatile uint32_t g_flashUntil = 0;
static volatile uint8_t  g_flashKind = 0;         // 1 ok, 2 alert

static WebServer        httpServer(80);
static WebSocketsServer wsServer(81);
static uint32_t         g_bootMs = 0;

struct ScenarioMsg { char name[16]; };

/* ============================ LED ====================================== */
static inline void ledRGB(uint8_t r, uint8_t g, uint8_t b) {
#if defined(ESP_ARDUINO_VERSION) && \
    ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 1, 0)
  rgbLedWrite(LED_PIN, r, g, b);
#else
  neopixelWrite(LED_PIN, r, g, b);
#endif
}

static void updateLed(const Snapshot& s) {
  static uint8_t ph = 0;
  ph++;
  if (millis() < g_flashUntil) {
    if (g_flashKind == 2) ledRGB((ph & 2) ? 60 : 0, 0, 0);          // red flash
    else                  ledRGB(0, (ph & 2) ? 50 : 0, 0);          // green flash
    return;
  }
  if (g_busy)         { ledRGB((ph & 2) ? 0 : 30, 0, (ph & 2) ? 50 : 20); return; }  // blue pulse
  if (!s.linkUp)      { ledRGB((ph & 4) ? 40 : 0, 0, 0); return; }
  if (!s.calibrated)  { ledRGB(30, 18, 0);  return; }
  if (s.moving)       { ledRGB(0, 40, 40);  return; }
  if (s.present)      { ledRGB(0, 16, 10);  return; }
  ledRGB(0, 3, 0);
}

/* ============================ SAMPLER ================================== */
static void samplerTask(void*) {
  float win[WINDOW_MAX];
  uint16_t widx = 0, wcount = 0;
  float emaFast = 0; bool emaInit = false;
  int8_t lastRaw = 0; bool haveLast = false;

  double cMean = 0, cM2 = 0; uint32_t cN = 0;
  uint32_t calibStart = millis();
  bool calibrated = false;
  float baseline = 1.0f;

  bool present = false, moving = false;
  uint32_t voteHist = 0;
  const uint32_t voteMask = (1UL << VOTE_WINDOW) - 1UL;
  uint32_t lastActive = millis();

  uint32_t rateBucket = millis(), rateCount = 0, dupCount = 0, readCount = 0;
  float sampleHz = 0, dupRatio = 0;
  uint32_t totalSamples = 0;
  uint32_t lastPost = millis();

  TickType_t lastWake = xTaskGetTickCount();
  const TickType_t period = pdMS_TO_TICKS(SAMPLE_INTERVAL_MS);

  for (;;) {
    vTaskDelayUntil(&lastWake, period);
    uint32_t now = millis();

    if (g_recalRequested) {
      g_recalRequested = false;
      calibrated = false; cMean = cM2 = 0; cN = 0;
      calibStart = now; wcount = widx = 0;
      present = moving = false; voteHist = 0;
      Serial.println(F("\n[CAL] Recalibrating - leave the room."));
    }

    if (WiFi.status() != WL_CONNECTED) {
      portENTER_CRITICAL(&g_mux); g_snap.linkUp = false; portEXIT_CRITICAL(&g_mux);
      haveLast = false; continue;
    }

    int8_t raw = WiFi.RSSI();
    readCount++;
    if (raw >= RSSI_VALID_HI || raw <= RSSI_VALID_LO) continue;
    if (haveLast && raw == lastRaw) dupCount++;
    lastRaw = raw; haveLast = true;

    float x = (float)raw;
    if (!emaInit) { emaFast = x; emaInit = true; }
    else if (fabsf(x - emaFast) > SPIKE_LIMIT_DB) continue;
    emaFast += 0.20f * (x - emaFast);

    win[widx] = x;
    widx = (widx + 1) % WINDOW_SIZE;
    if (wcount < WINDOW_SIZE) wcount++;
    totalSamples++; rateCount++;

    if (now - rateBucket >= 1000) {
      sampleHz = rateCount * 1000.0f / (float)(now - rateBucket);
      dupRatio = readCount ? (float)dupCount / (float)readCount : 0;
      rateBucket = now; rateCount = dupCount = readCount = 0;
    }
    if (wcount < 8) continue;

    float m = 0;
    for (uint16_t i = 0; i < wcount; i++) m += win[i];
    m /= (float)wcount;
    float ss = 0;
    for (uint16_t i = 0; i < wcount; i++) { float d = win[i] - m; ss += d * d; }
    float var = ss / (float)(wcount - 1);

    if (!calibrated) {
      if (now - calibStart < SETTLE_MS) {
        portENTER_CRITICAL(&g_mux);
        g_snap.linkUp = true; g_snap.calibrated = false;
        g_snap.rssi = x; g_snap.variance = var;
        g_snap.calibRemainS = (SETTLE_MS + CALIB_MS - (now - calibStart)) / 1000;
        portEXIT_CRITICAL(&g_mux);
        continue;
      }
      cN++;
      double d1 = (double)var - cMean;
      cMean += d1 / (double)cN;
      cM2   += d1 * ((double)var - cMean);

      if (now - calibStart >= SETTLE_MS + CALIB_MS) {
        baseline = (float)cMean;
        if (baseline < BASELINE_MIN) baseline = BASELINE_MIN;
        float sd = (cN > 1) ? (float)sqrt(cM2 / (double)(cN - 1)) : 0;
#if AUTO_THRESHOLD
        float e = K_SIGMA * sd; if (e < ABS_MIN_ENTER) e = ABS_MIN_ENTER;
#else
        float e = MANUAL_ENTER;
#endif
        g_enterT = e; g_exitT = e * EXIT_RATIO; g_moveT = e * MOVEMENT_MULT;
        calibrated = true;

        Serial.println();
        Serial.println(F("[CAL] ====== CALIBRATION COMPLETE ======"));
        Serial.printf ("[CAL] baseline variance : %.4f\n", baseline);
        Serial.printf ("[CAL] noise sigma       : %.4f\n", sd);
        Serial.printf ("[CAL] enter threshold   : %.3f\n", g_enterT);
        Serial.printf ("[CAL] sample rate       : %.2f Hz\n", sampleHz);
        if (baseline > 0.6f)
          Serial.println(F("[CAL] WARNING: baseline high - something moved.\n"
                           "[CAL]          Type 'recal' and leave the room."));
        Serial.println(F("[CAL] =================================="));
      }
      portENTER_CRITICAL(&g_mux);
      g_snap.linkUp = true; g_snap.calibrated = calibrated;
      g_snap.rssi = x; g_snap.variance = var;
      g_snap.calibRemainS = calibrated ? 0
        : (SETTLE_MS + CALIB_MS - (now - calibStart)) / 1000;
      portEXIT_CRITICAL(&g_mux);
      continue;
    }

    float adj = var - baseline; if (adj < 0) adj = 0;
    float ratio = (baseline > 1e-6f) ? (var / baseline) : 0;

    bool activeNow = present ? (adj > g_exitT) : (adj > g_enterT);
    voteHist = ((voteHist << 1) | (activeNow ? 1UL : 0UL)) & voteMask;
    int votes = __builtin_popcount(voteHist);

    if (!present) {
      if (votes >= VOTE_ENTER) { present = true; lastActive = now; }
    } else {
      if (votes >= 1) lastActive = now;
      if (now - lastActive >= g_holdMs) { present = false; voteHist = 0; }
    }
    moving = (adj > g_moveT);

    if (!present && ratio < BASELINE_GATE) {
      baseline += BASELINE_ALPHA * (var - baseline);
      if (baseline < BASELINE_MIN) baseline = BASELINE_MIN;
      if (baseline > BASELINE_MAX) baseline = BASELINE_MAX;
    }

    float intensity = 0;
    if (adj > 0) {
      float span = log10f(1.0f + g_moveT * 4.0f);
      intensity = (span > 0) ? (log10f(1.0f + adj) / span) : 0;
      if (intensity > 1.0f) intensity = 1.0f;
    }

    Snapshot s;
    s.rssi = x; s.mean = m; s.variance = var; s.baseline = baseline;
    s.adjusted = adj; s.ratio = ratio;
    s.enterT = g_enterT; s.exitT = g_exitT; s.moveT = g_moveT;
    s.intensity = intensity;
    s.present = present; s.moving = moving; s.calibrated = true; s.linkUp = true;
    s.sampleHz = sampleHz; s.dupRatio = dupRatio;
    s.samples = totalSamples; s.uptimeS = (now - g_bootMs) / 1000;
    s.calibRemainS = 0;

    portENTER_CRITICAL(&g_mux); g_snap = s; portEXIT_CRITICAL(&g_mux);

#if SHOW_RF_LOG
    static uint32_t lastLog = 0;
    if (now - lastLog >= 1000 && !g_busy) {
      lastLog = now;
      Serial.printf("[RF] rssi=%.0f  var=%.3f  base=%.3f  adj=%.3f  enter=%.3f  %s\n",
                    x, var, baseline, adj, g_enterT,
                    moving ? "MOVING" : present ? "PRESENT" : "clear");
    }
#endif

#if POST_TELEMETRY
    if (now - lastPost >= POST_PERIOD_MS) {
      lastPost = now;
      if (g_postQ) xQueueOverwrite(g_postQ, &s);
    }
#else
    (void)lastPost;
#endif
  }
}

/* ============================ HTTP HELPER ============================== */
/* Handles both http:// and https:// (Cloud Run) transparently. */
static int httpPostJson(const String& path, const String& body, String& out) {
  String url = String(BACKEND_URL) + path;
  bool secure = url.startsWith("https");
  int code = -1;
  HTTPClient http;

  if (secure) {
    WiFiClientSecure* client = new WiFiClientSecure();
    if (!client) return -1;
    client->setInsecure();          // demo: skip cert pinning
    client->setTimeout(HTTP_TIMEOUT_MS / 1000);
    if (http.begin(*client, url)) {
      http.addHeader("Content-Type", "application/json");
      http.setConnectTimeout(15000);
      http.setTimeout(HTTP_TIMEOUT_MS);
      code = http.POST(body);
      if (code > 0) out = http.getString();
      http.end();
    }
    delete client;
  } else {
    WiFiClient client;
    if (http.begin(client, url)) {
      http.addHeader("Content-Type", "application/json");
      http.setConnectTimeout(8000);
      http.setTimeout(HTTP_TIMEOUT_MS);
      code = http.POST(body);
      if (code > 0) out = http.getString();
      http.end();
    }
  }
  return code;
}

/* ============================ SCENARIO TASK ============================ */
static void printPrompt() {
  Serial.println();
  Serial.println(F("  +--------------------------------------------------+"));
  Serial.println(F("  |  ENTER SCENARIO                                  |"));
  Serial.println(F("  |    normal    all vitals within baseline          |"));
  Serial.println(F("  |    mild      gait speed low                      |"));
  Serial.println(F("  |    critical  heart rate AND gait speed abnormal  |"));
  Serial.println(F("  |                                                  |"));
  Serial.println(F("  |  also: status | recal | help                     |"));
  Serial.println(F("  +--------------------------------------------------+"));
  Serial.print  (F("  scenario > "));
}

static void scenarioTask(void*) {
  ScenarioMsg msg;
  for (;;) {
    if (xQueueReceive(g_scenarioQ, &msg, portMAX_DELAY) != pdTRUE) continue;

    Snapshot s;
    portENTER_CRITICAL(&g_mux); s = g_snap; portEXIT_CRITICAL(&g_mux);

    char body[520];
    snprintf(body, sizeof(body),
      "{\"scenario\":\"%s\",\"resident_id\":\"%s\",\"node_id\":\"%s\","
      "\"source\":\"esp32_hardware\","
      "\"presence\":{\"detected\":%s,\"movement\":%s,\"variance\":%.4f,"
      "\"baseline\":%.4f,\"ratio\":%.2f,\"calibrated\":%s}}",
      msg.name, RESIDENT_ID, NODE_ID,
      s.present ? "true" : "false", s.moving ? "true" : "false",
      s.variance, s.baseline, s.ratio, s.calibrated ? "true" : "false");

    g_busy = true;
    Serial.println();
    Serial.printf("[TRIGGER] scenario '%s' -> %s\n", msg.name, RESIDENT_ID);
    Serial.println(F("[TRIGGER] POST /api/hw/scenario"));
    Serial.println(F("[TRIGGER] Agents are running. Watch your dashboard."));
    Serial.print  (F("[TRIGGER] waiting"));

    String resp;
    uint32_t t0 = millis();
    int code = httpPostJson("/api/hw/scenario", String(body), resp);
    uint32_t took = (millis() - t0) / 1000;
    g_busy = false;

    Serial.println();
    if (code == 200) {
      Serial.printf("[TRIGGER] OK (HTTP 200) in %lu s\n", (unsigned long)took);
      bool injected = (resp.indexOf("\"vitals_injected\":true") >= 0);
      Serial.printf("[TRIGGER] vitals injected : %s\n", injected ? "yes" : "NO - run /api/hw/selftest");
      if (resp.length() > 400) resp = resp.substring(0, 400) + " ...";
      Serial.print(F("[TRIGGER] "));
      Serial.println(resp);
      g_flashKind = (strcmp(msg.name, "normal") == 0) ? 1 : 2;
      g_flashUntil = millis() + 6000;
    } else if (code > 0) {
      Serial.printf("[TRIGGER] backend returned HTTP %d\n", code);
      Serial.println(resp.substring(0, 300));
      g_flashKind = 2; g_flashUntil = millis() + 4000;
    } else {
      Serial.printf("[TRIGGER] FAILED (%d) after %lu s\n", code, (unsigned long)took);
      Serial.println(F("[TRIGGER] Check BACKEND_URL and that the service is awake."));
      g_flashKind = 2; g_flashUntil = millis() + 4000;
    }
    printPrompt();
  }
}

/* ============================ SERIAL CONSOLE =========================== */
static void printStatus() {
  Snapshot s;
  portENTER_CRITICAL(&g_mux); s = g_snap; portEXIT_CRITICAL(&g_mux);
  Serial.println();
  Serial.printf("  node      : %s\n", NODE_ID);
  Serial.printf("  resident  : %s\n", RESIDENT_ID);
  Serial.printf("  backend   : %s\n", BACKEND_URL);
  Serial.printf("  ip        : %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("  calibrated: %s\n", s.calibrated ? "yes" : "no");
  Serial.printf("  presence  : %s\n", s.moving ? "MOVEMENT" : s.present ? "PRESENT" : "clear");
  Serial.printf("  rssi %.0f dBm | var %.4f | base %.4f | ratio %.2fx | enter %.3f\n",
                s.rssi, s.variance, s.baseline, s.ratio, s.enterT);
  Serial.printf("  %.2f Hz | up %lu s | heap %lu\n",
                s.sampleHz, (unsigned long)s.uptimeS, (unsigned long)ESP.getFreeHeap());
}

static void handleLine(String line) {
  line.trim();
  if (!line.length()) { printPrompt(); return; }
  String low = line; low.toLowerCase();

  if (low == "status")            { printStatus(); printPrompt(); return; }
  if (low == "recal")             { g_recalRequested = true; return; }
  if (low == "help" || low == "?"){ printPrompt(); return; }

  if (g_busy) {
    Serial.println(F("\n[TRIGGER] A check is already running. Wait for it to finish."));
    return;
  }

  if (low == "normal" || low == "mild" || low == "critical" ||
      low == "crit"   || low == "warn" || low == "ok") {
    ScenarioMsg m;
    low.toCharArray(m.name, sizeof(m.name));
    if (g_scenarioQ) xQueueSend(g_scenarioQ, &m, 0);
    return;
  }

  Serial.println(F("\n  Unknown. Type: normal | mild | critical | status | recal"));
  printPrompt();
}

static void pollSerial() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { String l = buf; buf = ""; Serial.println(); handleLine(l); }
    else if (buf.length() < 64) { buf += c; Serial.print(c); }
  }
}

/* ============================ TELEMETRY (optional) ===================== */
#if POST_TELEMETRY
static void postTask(void*) {
  Snapshot s;
  for (;;) {
    if (xQueueReceive(g_postQ, &s, portMAX_DELAY) != pdTRUE) continue;
    if (WiFi.status() != WL_CONNECTED || g_busy) continue;
    char body[420];
    snprintf(body, sizeof(body),
      "{\"node_id\":\"%s\",\"resident_id\":\"%s\",\"rssi_dbm\":%.1f,"
      "\"rssi_variance\":%.4f,\"baseline_variance\":%.4f,\"adjusted_variance\":%.4f,"
      "\"variance_ratio\":%.2f,\"presence_detected\":%s,\"movement_detected\":%s,"
      "\"sample_hz\":%.2f,\"uptime_s\":%lu}",
      NODE_ID, RESIDENT_ID, s.mean, s.variance, s.baseline, s.adjusted, s.ratio,
      s.present ? "true" : "false", s.moving ? "true" : "false",
      s.sampleHz, (unsigned long)s.uptimeS);
    String resp;
    httpPostJson("/api/hw/telemetry", String(body), resp);
  }
}
#endif

/* ============================ LOCAL WEB / WS =========================== */
static Snapshot readSnap() {
  Snapshot s; portENTER_CRITICAL(&g_mux); s = g_snap; portEXIT_CRITICAL(&g_mux); return s;
}

static void handleStatusHttp() {
  Snapshot s = readSnap();
  char json[640];
  snprintf(json, sizeof(json),
    "{\"node_id\":\"%s\",\"resident_id\":\"%s\",\"calibrated\":%s,"
    "\"presence\":%s,\"movement\":%s,\"rssi_dbm\":%.1f,\"variance\":%.4f,"
    "\"baseline\":%.4f,\"adjusted\":%.4f,\"ratio\":%.2f,\"enter\":%.3f,"
    "\"sample_hz\":%.2f,\"uptime_s\":%lu,\"busy\":%s}",
    NODE_ID, RESIDENT_ID, s.calibrated ? "true" : "false",
    s.present ? "true" : "false", s.moving ? "true" : "false",
    s.rssi, s.variance, s.baseline, s.adjusted, s.ratio, s.enterT,
    s.sampleHz, (unsigned long)s.uptimeS, g_busy ? "true" : "false");
  httpServer.send(200, "application/json", json);
}

static void handleRecal() {
  g_recalRequested = true;
  httpServer.send(200, "application/json", "{\"ok\":true}");
}

static void handleConfig() {
  if (httpServer.hasArg("enter")) {
    float e = httpServer.arg("enter").toFloat();
    if (e > 0) { g_enterT = e; g_exitT = e * EXIT_RATIO; g_moveT = e * MOVEMENT_MULT; }
  }
  if (httpServer.hasArg("hold")) {
    long v = httpServer.arg("hold").toInt();
    if (v >= 0 && v <= 3600) g_holdMs = (uint32_t)v * 1000UL;
  }
  handleStatusHttp();
}

static void wsEvent(uint8_t num, WStype_t type, uint8_t*, size_t) {
  if (type == WStype_CONNECTED) Serial.printf("\n[WS] client %u connected\n", num);
}

static void broadcastWs() {
  if (wsServer.connectedClients() == 0) return;
  Snapshot s = readSnap();
  char json[560];
  snprintf(json, sizeof(json),
    "{\"rssi\":%.0f,\"variance\":%.4f,\"baseline\":%.4f,\"adjusted\":%.4f,"
    "\"baseline_var\":%.4f,\"adjusted_var\":%.4f,\"ratio\":%.2f,"
    "\"enter\":%.3f,\"exit\":%.3f,\"threshold\":%.3f,"
    "\"presence\":%s,\"movement\":%s,\"intensity\":%.3f,\"calibrated\":%s,"
    "\"calib_remaining_s\":%lu,\"hz\":%.2f,\"uptime_s\":%lu}",
    s.rssi, s.variance, s.baseline, s.adjusted, s.baseline, s.adjusted, s.ratio,
    s.enterT, s.exitT, s.enterT,
    s.present ? "true" : "false", s.moving ? "true" : "false", s.intensity,
    s.calibrated ? "true" : "false", (unsigned long)s.calibRemainS,
    s.sampleHz, (unsigned long)s.uptimeS);
  wsServer.broadcastTXT(json);
}

/* ============================ SETUP ==================================== */
void setup() {
  Serial.begin(115200);
  delay(500);
  g_bootMs = millis();

  pinMode(LED_PIN, OUTPUT);
  ledRGB(0, 0, 30);

  Serial.println();
  Serial.println(F("==============================================="));
  Serial.println(F("  WellNest ambient node  v5.0"));
  Serial.printf ("  node %s | resident %s\n", NODE_ID, RESIDENT_ID);
  Serial.printf ("  backend %s\n", BACKEND_URL);
  Serial.println(F("==============================================="));

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("[WIFI] joining %s", WIFI_SSID);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("\n[WIFI] failed - restarting"));
    ledRGB(60, 0, 0); delay(1000); ESP.restart();
  }
  Serial.printf("\n[WIFI] ip %s | ch %d | rssi %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.channel(), WiFi.RSSI());

  httpServer.on("/status",      handleStatusHttp);
  httpServer.on("/recalibrate", handleRecal);
  httpServer.on("/config",      handleConfig);
  httpServer.begin();
  wsServer.begin();
  wsServer.onEvent(wsEvent);

  g_postQ     = xQueueCreate(1, sizeof(Snapshot));
  g_scenarioQ = xQueueCreate(2, sizeof(ScenarioMsg));

  xTaskCreatePinnedToCore(samplerTask,  "sampler",  5120,  nullptr, 4, nullptr, 1);
  xTaskCreatePinnedToCore(scenarioTask, "scenario", 16384, nullptr, 1, nullptr, 0);
#if POST_TELEMETRY
  xTaskCreatePinnedToCore(postTask,     "post",     12288, nullptr, 1, nullptr, 0);
#endif

  Serial.printf("\n[CAL] Settling %lu s, then baseline for %lu s.\n",
                (unsigned long)(SETTLE_MS / 1000), (unsigned long)(CALIB_MS / 1000));
  Serial.println(F("[CAL] LEAVE THE ROOM NOW. LED is amber while calibrating."));
}

/* ============================ LOOP ===================================== */
void loop() {
  httpServer.handleClient();
  wsServer.loop();
  pollSerial();

  static uint32_t lastWs = 0, lastLed = 0, lastDot = 0;
  static bool promptShown = false, wasBusy = false;
  uint32_t now = millis();

  if (now - lastWs  >= WS_PERIOD_MS) { lastWs  = now; broadcastWs(); }
  if (now - lastLed >= 200)          { lastLed = now; updateLed(readSnap()); }

  // progress dots while the cloud health check runs
  if (g_busy && now - lastDot >= 3000) { lastDot = now; Serial.print("."); }
  wasBusy = g_busy;

  // show the prompt once, right after calibration finishes
  if (!promptShown) {
    Snapshot s = readSnap();
    if (s.calibrated) { promptShown = true; printPrompt(); }
  }

  delay(2);
}
