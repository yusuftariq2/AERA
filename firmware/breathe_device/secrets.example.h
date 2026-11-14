// Copy this file to secrets.h (same folder) and fill it in.
// secrets.h is in .gitignore so your WiFi password and AWS keys never reach GitHub.
#pragma once

// WiFi: the ESP32 only connects to 2.4 GHz networks with a normal password.
// Venue WiFi with a login page won't work, so use a phone hotspot
// (iPhone: Settings > Personal Hotspot > turn on "Maximize Compatibility").
#define WIFI_SSID     "your-hotspot-name"
#define WIFI_PASSWORD "your-hotspot-password"

// Must match the Thing name you created in AWS IoT Core
#define DEVICE_ID "kid-001"

// AWS IoT Core > Settings > Device data endpoint
#define AWS_IOT_ENDPOINT "xxxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com"

// Paste the full contents of AmazonRootCA1.pem between the lines
static const char AWS_CERT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PASTE AmazonRootCA1.pem HERE
-----END CERTIFICATE-----
)EOF";

// Paste the full contents of xxxx-certificate.pem.crt
static const char AWS_CERT_CRT[] PROGMEM = R"KEY(
-----BEGIN CERTIFICATE-----
PASTE DEVICE CERTIFICATE HERE
-----END CERTIFICATE-----
)KEY";

// Paste the full contents of xxxx-private.pem.key
static const char AWS_CERT_PRIVATE[] PROGMEM = R"KEY(
-----BEGIN RSA PRIVATE KEY-----
PASTE PRIVATE KEY HERE
-----END RSA PRIVATE KEY-----
)KEY";
