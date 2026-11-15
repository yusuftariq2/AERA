// BreatheDetroit wireless watch: the BottleNose (ESP32-C6) plugged into the FREE-WILi
// gets live data from AWS over WiFi and drives the watch's LEDs and screen.
// No laptop needed.
//
// How it talks to the watch: FREE-WILi "UART API mode" (io > UART > t, turned ON once)
// using the official OneWili wire format: 0x02 + "g\s 0 0 60 0 8000 0" + "\n".
// Commands are spaced out (the watch drops bytes if they arrive back-to-back), and the
// LEDs are only re-sent when the data changes or every 20 s.
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
const int WATCH_RX_PIN = 17;           // verified tonight: BottleNose <-> FREE-WILi works on 16/17
const int WATCH_TX_PIN = 16;
const uint32_t POLL_MS = 3000;         // fetch from AWS
const uint32_t TEXT_MS = 500;          // send a burst of the risk word twice a second
const int BURST = 6;                   // text only rendered when commands arrived back-to-back
const bool USE_LEDS = false;          // LED commands come back "Invalid" over the wire on OG fw 024, so text only
const int NUM_LEDS = 7;
const int LED_HOLD_MS = 8000;          // LEDs stay lit this long (8000 is known to work; 60000 was rejected)
const uint32_t LED_REFRESH_MS = 6000;  // re-send before the 8 s hold runs out
const int CMD_GAP_MS = 30;             // pause between commands so the watch can keep up
const uint32_t LED_STEP_MS = 400;      // send one LED at a time, this far apart

HardwareSerial Watch(1);

// latest data
int g_risk = 3;          // 0 green, 1 yellow, 2 red, 3 unknown
int g_tvoc = 0;
int g_puffs = 0;
bool g_haveData = false;
String g_status = "WIFI..";
uint32_t lastPoll = 0, lastPage = 0, lastText = 0, lastLedStep = 0;
int page = 0;

// ---------- watch commands (OneWili wire format) ----------
// The watch drops characters when a long line arrives all at once (short lines worked,
// 20-char LED lines came back "Invalid"), so send ONE character at a time with a pause.
const int CHAR_GAP_US = 2000;
void watchByte(uint8_t c) {
  Watch.write(c);
  Watch.flush();
  delayMicroseconds(CHAR_GAP_US);
}

void watchCmd(const String& pathAndArgs) {
  watchByte(0x02);
  for (size_t i = 0; i < pathAndArgs.length(); i++) watchByte((uint8_t)pathAndArgs[i]);
  watchByte('\n');
  delay(CMD_GAP_MS);
  Serial.println("-> watch: " + pathAndArgs);
}

void watchLed(int i, int r, int g, int b) {
  watchCmd("g\\s " + String(i) + " " + String(r) + " " + String(g) + " " + String(b) + " " + String(LED_HOLD_MS) + " 0");
}

void watchText(const String& text) {
  // Over the wire the watch only takes ONE word of at most ~6 characters
  // (longer text shows as "p"), so no spaces and cut to 6.
  String t = text;
  t.replace(" ", "");
  if (t.length() > 6) t = t.substring(0, 6);
  watchCmd("g\\p " + t);
}

// Same as watchText but with no pause after the command (for bursts).
void watchTextFast(const String& text) {
  String t = text;
  t.replace(" ", "");
  if (t.length() > 6) t = t.substring(0, 6);
  String line = "g\\p " + t;
  watchByte(0x02);
  for (size_t i = 0; i < line.length(); i++) watchByte((uint8_t)line[i]);
  watchByte('\n');
}

void riskRgb(int risk, int& r, int& g, int& b) {
  if (risk == 0)      { r = 0;  g = 60; b = 0;  }
  else if (risk == 1) { r = 60; g = 30; b = 0;  }
  else if (risk == 2) { r = 60; g = 0;  b = 0;  }
  else                { r = 0;  g = 0;  b = 40; }
}

int lastLedRisk = -1, lastLedLit = -1;
uint32_t lastLedSent = 0;
int ledQueue = NUM_LEDS;          // next LED to send; NUM_LEDS = nothing queued
int qR, qG, qB, qLit;

// Called after each AWS poll: queue an LED refresh if something changed (or it's time).
void showLeds() {
  int r, g, b;
  riskRgb(g_risk, r, g, b);
  int lit = constrain((g_tvoc * NUM_LEDS + 500) / 1000, 1, NUM_LEDS);
  if (g_risk == 3) lit = 1;
  bool changed = (g_risk != lastLedRisk || lit != lastLedLit);
  if (!USE_LEDS) return;
  if (!changed && millis() - lastLedSent < LED_REFRESH_MS) return;
  lastLedRisk = g_risk; lastLedLit = lit; lastLedSent = millis();
  qR = r; qG = g; qB = b; qLit = lit;
  ledQueue = 0;                   // loop() sends them one at a time
}

void showPage(bool force);   // defined below

// Called from loop(): send at most one queued LED.
void stepLeds() {
  if (ledQueue >= NUM_LEDS || millis() - lastLedStep < LED_STEP_MS) return;
  lastLedStep = millis();
  if (ledQueue < qLit) watchLed(ledQueue, qR, qG, qB);
  else watchLed(ledQueue, 0, 0, 0);
  ledQueue++;
  // Each LED command flips the screen to "s", so put the word back after the last LED.
  if (ledQueue >= NUM_LEDS) showPage(true);
}

// The LEDs are the main display (they work reliably). The screen just shows one word for
// the risk, sent only when it changes (or every TEXT_MS), so the watch isn't flooded.
int lastTextRisk = -1;
void showPage(bool force) {
  if (!g_haveData) { if (force) watchText(g_status); return; }
  if (!force && g_risk == lastTextRisk) return;
  lastTextRisk = g_risk;
  const char* air = g_risk == 0 ? "GOOD" : g_risk == 1 ? "FAIR" : g_risk == 2 ? "BAD!" : "WAIT";
  // Text only stays up when commands arrive back-to-back, so send the same word in a burst.
  for (int i = 0; i < BURST; i++) watchTextFast(air);
}

// ---------- WiFi + AWS ----------
void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  g_status = "WIFI..";
  watchText(g_status);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) delay(250);
  g_status = WiFi.status() == WL_CONNECTED ? "ONLINE" : "NOWIFI";
  watchText(g_status);
  Serial.println("WiFi: " + g_status);
}

int riskCode(const char* risk, bool online) {
  if (!online || !risk) return 3;
  if (!strcmp(risk, "green")) return 0;
  if (!strcmp(risk, "yellow")) return 1;
  if (!strcmp(risk, "red")) return 2;
  return 3;
}

void pollStatus() {
  WiFiClientSecure https;
  https.setInsecure();  // read-only public API
  HTTPClient http;
  if (!http.begin(https, String(API_URL) + "/status/" + DEVICE_ID)) return;
  http.setTimeout(5000);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("API HTTP %d\n", code);
    g_status = code == 404 ? "WAIT" : "API" + String(code);
    http.end();
    return;
  }
  JsonDocument filter;
  filter["risk"] = true;
  filter["online"] = true;
  filter["puffs24h"] = true;
  filter["latest"]["tvoc"] = true;
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (err) { Serial.printf("JSON: %s\n", err.c_str()); return; }

  bool online = doc["online"] | true;
  g_risk = riskCode(doc["risk"] | "", online);
  g_tvoc = doc["latest"]["tvoc"] | 0;
  g_puffs = doc["puffs24h"] | 0;
  g_haveData = true;
  Serial.printf("risk=%d tvoc=%d puffs=%d\n", g_risk, g_tvoc, g_puffs);
  showLeds();
  if (ledQueue >= NUM_LEDS) showPage(false);   // risk changed? update the word (not mid-LED-update)
}

void setup() {
  Serial.begin(115200);
  Watch.begin(115200, SERIAL_8N1, WATCH_RX_PIN, WATCH_TX_PIN);
  delay(500);
  Serial.println("BreatheDetroit wireless watch");
  Watch.print("\n");        // clear any half line on the wire
  watchText("HI");
  if (USE_LEDS) { qR = 0; qG = 0; qB = 30; qLit = NUM_LEDS; ledQueue = 0; }   // blue sweep
  connectWifi();
}

void loop() {
  connectWifi();
  while (Watch.available()) Watch.read();   // ignore anything the watch sends
  if (WiFi.status() == WL_CONNECTED && millis() - lastPoll > POLL_MS) {
    lastPoll = millis();
    pollStatus();
  }
  if (millis() - lastText > TEXT_MS && ledQueue >= NUM_LEDS) {   // re-send the word so it stays up
    lastText = millis();
    showPage(true);
  }
  stepLeds();
  delay(20);
}
