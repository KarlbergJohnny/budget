// Gateway för vagnvåg.
//
// Skannar passivt efter hörnenheternas BLE advertising, avkodar paketen och
// skickar nya mätningar till servern (POST /api/v1/ingest) via wifi.
// Servern sätter tidsstämpeln; gatewayen skickar hur gammal varje mätning är.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <NimBLEDevice.h>
#include <WiFi.h>

#include <map>
#include <mutex>
#include <string>

#include "vagn_protocol.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "include/secrets.h saknas - använder secrets.example.h"
#include "secrets.example.h"
#endif

#ifndef UPLOAD_INTERVAL_MS
#define UPLOAD_INTERVAL_MS 3000
#endif

// Mätningar äldre än så här skickas inte (hörnet har troligen tystnat).
#ifndef MAX_AGE_MS
#define MAX_AGE_MS 120000
#endif

struct Seen {
  vagn::Measurement m;
  int rssi = 0;
  uint32_t received_ms = 0;
  bool uploaded = false;
};

static std::map<std::string, Seen> g_seen;  // MAC -> senaste mätning
static std::mutex g_mutex;
static uint32_t g_packets = 0;
static uint32_t g_last_upload = 0;
static String g_gateway_id;

class ScanCallbacks : public NimBLEAdvertisedDeviceCallbacks {
  void onResult(NimBLEAdvertisedDevice* dev) override {
    if (!dev->haveManufacturerData()) return;
    std::string data = dev->getManufacturerData();
    vagn::Measurement m;
    if (!vagn::decode(reinterpret_cast<const uint8_t*>(data.data()), data.size(), m)) return;

    std::string mac = dev->getAddress().toString();
    std::lock_guard<std::mutex> lock(g_mutex);
    ++g_packets;
    Seen& s = g_seen[mac];
    bool is_new = s.received_ms == 0 || s.m.seq != m.seq;
    s.rssi = dev->getRSSI();
    if (is_new) {
      s.m = m;
      s.received_ms = millis();
      s.uploaded = false;
    }
  }
};

static void connect_wifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("ansluter till wifi %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(250);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf(" ok, ip %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println(" misslyckades, försöker igen senare");
  }
}

static void start_scan() {
  NimBLEDevice::init("");
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new ScanCallbacks(), true);  // true = ta emot dubletter
  scan->setActiveScan(false);
  scan->setInterval(100);
  scan->setWindow(90);
  scan->setMaxResults(0);  // spara inga resultat, bara callbacks
  scan->start(0, nullptr, false);
}

static void upload() {
  JsonDocument doc;
  doc["gateway"] = g_gateway_id;
  doc["fw"] = VAGN_FW_VERSION;
  doc["uptime_s"] = millis() / 1000;
  doc["wifi_rssi"] = WiFi.RSSI();
  JsonArray readings = doc["readings"].to<JsonArray>();

  std::map<std::string, uint16_t> sent;  // MAC -> seq som skickas nu
  {
    std::lock_guard<std::mutex> lock(g_mutex);
    uint32_t now = millis();
    doc["packets"] = g_packets;
    for (auto& kv : g_seen) {
      Seen& s = kv.second;
      uint32_t age = now - s.received_ms;
      if (s.uploaded || age > MAX_AGE_MS) continue;
      JsonObject r = readings.add<JsonObject>();
      r["mac"] = kv.first;
      if (s.m.corner != vagn::CORNER_UNKNOWN) r["corner"] = s.m.corner;
      r["seq"] = s.m.seq;
      r["distance_mm"] = s.m.distance_dmm / 10.0f;
      r["battery_mv"] = s.m.battery_mv;
      r["temp_c"] = s.m.temp_c;
      r["flags"] = s.m.flags;
      r["rssi"] = s.rssi;
      r["age_ms"] = age;
      sent[kv.first] = s.m.seq;
    }
  }
  if (sent.empty()) return;

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.setTimeout(8000);
  http.begin(String(SERVER_URL) + "/api/v1/ingest");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", INGEST_KEY);
  int code = http.POST(body);
  http.end();

  if (code >= 200 && code < 300) {
    std::lock_guard<std::mutex> lock(g_mutex);
    for (auto& kv : sent) {
      auto it = g_seen.find(kv.first);
      // Markera bara som skickad om ingen nyare mätning hunnit komma in.
      if (it != g_seen.end() && it->second.m.seq == kv.second) it->second.uploaded = true;
    }
    Serial.printf("skickade %u mätningar -> %d\n", (unsigned)sent.size(), code);
  } else {
    Serial.printf("uppladdning misslyckades (%d), försöker igen\n", code);
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  g_gateway_id = "GW-" + WiFi.macAddress();
  g_gateway_id.replace(":", "");
  Serial.printf("vagnvag gateway fw %s id %s server %s\n", VAGN_FW_VERSION, g_gateway_id.c_str(),
                SERVER_URL);
  connect_wifi();
  start_scan();
}

void loop() {
  if (millis() - g_last_upload >= UPLOAD_INTERVAL_MS) {
    g_last_upload = millis();
    connect_wifi();
    if (WiFi.status() == WL_CONNECTED) upload();

    std::lock_guard<std::mutex> lock(g_mutex);
    Serial.printf("paket totalt %u, hörn sedda %u\n", (unsigned)g_packets, (unsigned)g_seen.size());
  }
  delay(50);
}
