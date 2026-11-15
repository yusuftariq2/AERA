// BreatheDetroit bedside monitor
// ESP32 + CCS811 (VOCs) + DHT11 (temp/humidity) + TTP223B touch pad (inhaler) + 3 LEDs
//
// Board:     Tools > Board > esp32 > ESP32 Dev Module
// Libraries: Adafruit CCS811, DHT sensor library (Adafruit), Adafruit Unified Sensor,
//            PubSubClient (Nick O'Leary), ArduinoJson (Benoit Blanchon, v7)
//            (click "Install All" when the Library Manager asks about dependencies)
//
// Before uploading: copy secrets.example.h to secrets.h in this folder and fill it in.
// NEVER commit secrets.h to GitHub (it's in .gitignore).

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_CCS811.h>
#include <DHT.h>
#include <time.h>
#include "secrets.h"

// ---------------- Settings ----------------
// true  = connect to WiFi + AWS IoT Core (normal mode)
// false = no WiFi/AWS. JSON lines only go to USB Serial; run tools/serial_bridge.py on a laptop
#define USE_AWS true

#define I2C_SDA     21
#define I2C_SCL     22
#define DHT_PIN     4
#define TOUCH_PIN   15
#define LED_GREEN   18
#define LED_YELLOW  19
#define LED_RED     23

const unsigned long PUBLISH_EVERY_MS = 2000;  // one reading every 5 s
const unsigned long PUFF_COOLDOWN_MS = 2000;  // ignore repeat touches for 2 s
const int   TVOC_YELLOW   = 220;              // ppb, keep in sync with the Risk Lambda
const int   TVOC_RED      = 661;              // ppb (red = above 660)
const float HUMIDITY_BUMP = 60.0;             // % humidity that bumps risk up one level

// ---------------- Globals ----------------
WiFiClientSecure net;
PubSubClient mqtt(net);
Adafruit_CCS811 ccs;
DHT dht(DHT_PIN, DHT11);

String telemetryTopic;
String puffTopic;

bool ccsReady = false;
uint16_t lastTvoc = 0;
uint16_t lastEco2 = 400;
float lastTemp = NAN;
float lastHum  = NAN;

unsigned long lastPublish = 0;
unsigned long lastPuff = 0;
unsigned long lastAwsAttempt = 0;
int lastTouch = LOW;
int currentRisk = 0;

// ---------------- LEDs ----------------
void showRisk(int level) {
  digitalWrite(LED_GREEN,  level == 0 ? HIGH : LOW);
  digitalWrite(LED_YELLOW, level == 1 ? HIGH : LOW);
  digitalWrite(LED_RED,    level == 2 ? HIGH : LOW);
}

void allLeds(int value) {
  digitalWrite(LED_GREEN, value);
  digitalWrite(LED_YELLOW, value);
  digitalWrite(LED_RED, value);
}

void flashLeds() {  // quick "puff logged" feedback
  for (int i = 0; i < 2; i++) {
    allLeds(HIGH); delay(120);
    allLeds(LOW);  delay(120);
  }
  showRisk(currentRisk);
}

// ---------------- Sensors ----------------
bool startCCS811() {
  if (ccs.begin(0x5A)) { Serial.println("CCS811 found at 0x5A"); return true; }
  if (ccs.begin(0x5B)) { Serial.println("CCS811 found at 0x5B"); return true; }
  Serial.println("CCS811 NOT found. Check: VCC->3.3V, GND->GND, SDA->21, SCL->22, WAKE->GND");
  return false;
}

void readCCS() {
  if (!ccsReady || !ccs.available()) return;
  if (!ccs.readData()) {          // readData() returns 0 when OK
    lastTvoc = ccs.getTVOC();
    lastEco2 = ccs.geteCO2();
  } else {
    Serial.println("CCS811 read error (check wiring, or lower the I2C speed)");
  }
}

void readDHT() {
  float h = dht.readHumidity();
  float t = dht.readTemperature();  // Celsius
  if (isnan(h) || isnan(t)) {
    Serial.println("DHT11 read failed (check S->GPIO 4, V->3.3V, G->GND)");
    return;
  }
  lastHum = h;
  lastTemp = t;
  if (ccsReady) ccs.setEnvironmentalData(h, t);  // makes CCS811 readings more accurate
}

int localRisk() {  // same rule as the cloud, minus the puff count
  int level = 0;
  if (lastTvoc >= TVOC_RED) level = 2;
  else if (lastTvoc >= TVOC_YELLOW) level = 1;
  if (!isnan(lastHum) && lastHum > HUMIDITY_BUMP && level < 2) level++;
  return level;
}

// ---------------- WiFi / time / AWS ----------------
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to WiFi '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - start > 20000) {
      Serial.println("\nWiFi failed. The ESP32 only works on 2.4 GHz WiFi with a normal password");
      Serial.println("(phone hotspot: turn on 'Maximize Compatibility'). Retrying...");
      WiFi.disconnect();
      delay(1000);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      start = millis();
    }
  }
  Serial.printf("\nWiFi connected, IP %s\n", WiFi.localIP().toString().c_str());
}

void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("Syncing time");
  time_t now = time(nullptr);
  unsigned long start = millis();
  while (now < 1700000000 && millis() - start < 15000) {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
  }
  Serial.println(now >= 1700000000 ? " ok" : " failed (continuing anyway)");
}

bool reconnectAws() {
  if (mqtt.connected()) return true;
  Serial.print("Connecting to AWS IoT... ");
  if (mqtt.connect(DEVICE_ID)) {
    Serial.println("connected");
    return true;
  }
  Serial.printf("failed, state=%d\n", mqtt.state());
    char tlsErr[120]; int tlsCode = net.lastError(tlsErr, sizeof(tlsErr));
  Serial.printf("  TLS error %d: %s\n", tlsCode, tlsErr);
  Serial.println("  -2 = network/TLS: check AWS_IOT_ENDPOINT, the 3 certificates, and that the policy is attached");
  Serial.println("   5 = not authorized: check the IoT policy allows iot:Connect");
  return false;
}

void setupAws() {
  net.setCACert(AWS_CERT_CA);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);
  mqtt.setServer(AWS_IOT_ENDPOINT, 8883);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  reconnectAws();
}

// ---------------- Publishing ----------------
void sendJson(JsonDocument &doc, const String &topic) {
  char buf[256];
  serializeJson(doc, buf, sizeof(buf));
  Serial.println(buf);  // always print: the serial bridge fallback reads these lines
  if (USE_AWS && mqtt.connected()) {
    if (!mqtt.publish(topic.c_str(), buf)) Serial.println("MQTT publish failed");
  }
}

void publishTelemetry() {
  JsonDocument doc;
  doc["deviceId"] = DEVICE_ID;
  doc["ts"] = (long)time(nullptr);
  doc["tvoc"] = lastTvoc;
  doc["eco2"] = lastEco2;
  if (!isnan(lastTemp)) doc["tempC"] = round(lastTemp * 10) / 10.0;
  if (!isnan(lastHum))  doc["humidity"] = round(lastHum);
  sendJson(doc, telemetryTopic);
}

void publishPuff() {
  JsonDocument doc;
  doc["deviceId"] = DEVICE_ID;
  doc["ts"] = (long)time(nullptr);
  doc["event"] = "puff";
  doc["source"] = "touchpad";
  sendJson(doc, puffTopic);
}

// ---------------- Setup / loop ----------------
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== BreatheDetroit device starting ===");

  pinMode(TOUCH_PIN, INPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  allLeds(HIGH);  // LED self-test: all 3 should light for 1 second
  delay(1000);
  allLeds(LOW);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(10000);   // slow I2C: the CCS811 is picky on ESP32
  ccsReady = startCCS811();
  Wire.setClock(10000);   // set again in case the library reset it
  dht.begin();

  telemetryTopic = String("breathe/") + DEVICE_ID + "/telemetry";
  puffTopic      = String("breathe/") + DEVICE_ID + "/puff";

  if (USE_AWS) {
    connectWiFi();
    syncTime();
    setupAws();
  } else {
    Serial.println("USE_AWS is false: printing JSON only (use tools/serial_bridge.py)");
  }
  Serial.println("Note: the CCS811 needs ~20 minutes after power-up before readings settle.");
}

void loop() {
  if (USE_AWS) {
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
    if (!mqtt.connected() && millis() - lastAwsAttempt > 5000) {
      lastAwsAttempt = millis();
      reconnectAws();
    }
    mqtt.loop();
  }

  readCCS();

  // Inhaler touch pad: count one puff on each LOW -> HIGH change, then wait 2 s
  int touch = digitalRead(TOUCH_PIN);
  if (touch == HIGH && lastTouch == LOW && millis() - lastPuff > PUFF_COOLDOWN_MS) {
    lastPuff = millis();
    Serial.println("Puff logged");
    publishPuff();
    flashLeds();
  }
  lastTouch = touch;

  if (millis() - lastPublish >= PUBLISH_EVERY_MS) {
    lastPublish = millis();
    readDHT();
    currentRisk = localRisk();
    showRisk(currentRisk);
    publishTelemetry();
  }

  delay(20);
}
