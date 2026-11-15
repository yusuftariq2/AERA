// BreatheDetroit wireless watch: the BottleNose (ESP32-C6) plugged into the FREE-WILi
// gets live risk from AWS over WiFi and drives the watch's screen and LED bar. No laptop.
//
// How it talks to the watch: FREE-WILi "UART API mode" (io > UART > t, turned on by
// wristband/fw_reboot_api.py) using the OneWili wire format: 0x02 + "g\p FAIR" + "\n".
// What we learned on OG firmware 024:
//   - text/LED commands only stick when they arrive back-to-back (a steady stream),
//   - any pause lets the screen fall back to white / "p" / "s",
// so the AWS fetch runs in its own background task and the main loop streams the
// screen word continuously, refreshing the LED bar in bursts.
//
// Arduino IDE: Board "ESP32C6 Dev Module", Tools > USB CDC On Boot: Enabled.
// secrets.h: copy firmware/breathe_device/secrets.h into this folder (never commit it).
// Uses WIFI_SSID, WIFI_PASSWORD and DEVICE_ID from it.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

const char* API_URL = "https://7xd4mqiish.execute-api.us-east-2.amazonaws.com";
const int WATCH_RX_PIN = 17;            // BottleNose <-> FREE-WILi Orca UART (verified)
const int WATCH_TX_PIN = 16;
const uint32_t POLL_MS = 2000;          // background AWS fetch interval
const int NUM_LEDS = 7;
const uint32_t LED_REFRESH_MS = 5000;   // re-send the LED bar this often (each LED holds 8 s)
const int CHAR_GAP_US = 1500;           // tiny pause per character
const int BURST = 4;                    // screen commands sent back-to-back...
const int BURST_GAP_MS = 250;           // ...then a pause, so the watch never builds a backlog

HardwareSerial Watch(1);

// Latest data, written by the background fetch task, read by loop().
volatile int g_risk = 3;                // 0 green, 1 yellow, 2 red, 3 unknown
volatile int g_tvoc = 0;
volatile int g_puffs = 0;
volatile bool g_haveData = false;
volatile int g_statusCode = 0;          // 0 = ok/starting, else HTTP error
volatile int g_lastPuffHeldMs = 0;      // hold time of the latest puff
volatile bool g_newPuff = false;        // set when the puff count goes up
uint32_t puffShowUntil = 0, puffStart = 0;

// ---------- sending to the watch (main loop only) ----------
void watchByte(uint8_t c) {
  Watch.write(c);
  Watch.flush();
  delayMicroseconds(CHAR_GAP_US);
}

void watchLine(const String& line) {
  watchByte(0x02);
  for (size_t i = 0; i < line.length(); i++) watchByte((uint8_t)line[i]);
  watchByte('\n');
}

void watchText(const char* word) {      // one word, 6 chars max (longer shows as "p")
  String t = word;
  if (t.length() > 6) t = t.substring(0, 6);
  watchLine("g\\p " + t);
}

void sendLed(int i, bool on, int r, int g, int b, int repeats) {
  String line = "g\\s " + String(i) + " " +
                (on ? String(r) + " " + String(g) + " " + String(b) : String("0 0 0")) + " 8000 0";
  for (int k = 0; k < repeats; k++) watchLine(line);
}

void riskRgb(int risk, int& r, int& g, int& b) {
  if (risk == 0)      { r = 0;  g = 60; b = 0;  }
  else if (risk == 1) { r = 60; g = 30; b = 0;  }
  else if (risk == 2) { r = 60; g = 0;  b = 0;  }
  else                { r = 0;  g = 0;  b = 40; }
}

// While a new puff is showing: "PUFF!" for 2 s, then the hold time (e.g. "1.2S") for 2 s.
char puffText[8];
const char* puffWord() {
  uint32_t t = millis() - puffStart;
  if (t < 2000) return "PUFF!";
  int tenths = (g_lastPuffHeldMs + 50) / 100;
  if (tenths <= 0) return "PUFF!";
  snprintf(puffText, sizeof puffText, "%d.%dS", tenths / 10, tenths % 10);
  return puffText;
}

const char* screenWord() {
  if (puffShowUntil && millis() < puffShowUntil) return puffWord();
  if (WiFi.status() != WL_CONNECTED) return "NOWIFI";
  if (!g_haveData) return g_statusCode ? "API" : "WIFI..";
  int risk = g_risk;
  return risk == 0 ? "GOOD" : risk == 1 ? "FAIR" : risk == 2 ? "BAD!" : "WAIT";
}

int lastLedRisk = -1, lastLedLit = -1;
uint32_t lastLedSent = 0;

void updateLedsIfNeeded() {
  if (!g_haveData) return;
  int risk = g_risk, tvoc = g_tvoc;
  int r, g, b;
  riskRgb(risk, r, g, b);
  int lit = constrain((tvoc * NUM_LEDS + 500) / 1000, 1, NUM_LEDS);
  if (risk == 3) lit = 1;
  if (risk == lastLedRisk && lit == lastLedLit && millis() - lastLedSent < LED_REFRESH_MS) return;
  bool shrinking = lastLedLit > lit;
  lastLedRisk = risk; lastLedLit = lit; lastLedSent = millis();
  const char* word = screenWord();
  // Warm-up: the first commands after a pause get rejected, so lead with a text burst
  // (this is how the LED bar worked earlier: LEDs right after the words).
  for (int i = 0; i < 4; i++) watchText(word);
  for (int i = 0; i < NUM_LEDS; i++) {
    sendLed(i, i < lit, r, g, b, 3);            // 3x each: covers a dropped one
  }
  if (shrinking)                                // make sure old LEDs go dark
    for (int i = lit; i < NUM_LEDS; i++) sendLed(i, false, 0, 0, 0, 3);
  for (int i = 0; i < 2; i++) watchText(word);   // word back on top after the LEDs
}

// ---------- AWS fetch (background task, never touches the watch UART) ----------
int riskCode(const char* risk, bool online) {
  if (!online || !risk) return 3;
  if (!strcmp(risk, "green")) return 0;
  if (!strcmp(risk, "yellow")) return 1;
  if (!strcmp(risk, "red")) return 2;
  return 3;
}

void pollStatus() {
  WiFiClientSecure https;
  https.setInsecure();                          // read-only public API
  HTTPClient http;
  if (!http.begin(https, String(API_URL) + "/status/" + DEVICE_ID)) return;
  http.setTimeout(5000);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("API HTTP %d\n", code);
    if (code != 404) g_statusCode = code;
    http.end();
    return;
  }
  JsonDocument filter;
  filter["risk"] = true;
  filter["online"] = true;
  filter["puffs24h"] = true;
  filter["latest"]["tvoc"] = true;
  filter["lastPuffDurationMs"] = true;
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (err) { Serial.printf("JSON: %s\n", err.c_str()); return; }

  bool online = doc["online"] | true;
  g_risk = riskCode(doc["risk"] | "", online);
  g_tvoc = doc["latest"]["tvoc"] | 0;
  int puffs = doc["puffs24h"] | 0;
  if (g_haveData && puffs > g_puffs) {           // a new puff since last check
    g_lastPuffHeldMs = doc["lastPuffDurationMs"] | 0;
    g_newPuff = true;
  }
  g_puffs = puffs;
  g_statusCode = 0;
  g_haveData = true;
  Serial.printf("risk=%d tvoc=%d puffs=%d\n", (int)g_risk, (int)g_tvoc, (int)g_puffs);
}

void pollTask(void*) {
  for (;;) {
    if (WiFi.status() == WL_CONNECTED) pollStatus();
    vTaskDelay(pdMS_TO_TICKS(POLL_MS));
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  Watch.begin(115200, SERIAL_8N1, WATCH_RX_PIN, WATCH_TX_PIN);
  delay(500);
  Serial.println("BreatheDetroit wireless watch");
  Watch.print("\n");                            // clear any half line on the wire
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  xTaskCreate(pollTask, "poll", 12288, nullptr, 1, nullptr);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {          // reconnect without blocking the stream
    static uint32_t lastTry = 0;
    if (millis() - lastTry > 10000) { lastTry = millis(); WiFi.reconnect(); }
  }
  while (Watch.available()) Watch.read();       // ignore anything the watch sends
  if (g_newPuff) {                              // new puff: flash LEDs white, show PUFF! + hold time
    g_newPuff = false;
    puffStart = millis();
    puffShowUntil = puffStart + 4000;
    const char* w = puffWord();
    for (int i = 0; i < 4; i++) watchText(w);
    for (int i = 0; i < NUM_LEDS; i++) sendLed(i, true, 40, 40, 40, 2);
    lastLedSent = 0;                            // repaint the risk bar right after
    lastLedRisk = -1;
  }
  updateLedsIfNeeded();
  const char* word = screenWord();
  for (int i = 0; i < BURST; i++) watchText(word);   // short burst keeps the text up
  delay(BURST_GAP_MS);                               // pause: no backlog, so no lag
}
