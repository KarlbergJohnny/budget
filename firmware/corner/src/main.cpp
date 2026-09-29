// Hörnenhet för vagnvåg.
//
// Varje uppvaknande: mät avståndet till målplåten (laser och/eller ultraljud),
// slå ihop värdena, sänd resultatet som BLE advertising i VAGN_ADV_MS och gå
// sedan till djupsömn i VAGN_SLEEP_S sekunder.
//
// Utan givare skickas simulerade värden med flaggan FLAG_SIMULATED.

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <esp_sleep.h>
#include <math.h>

#include "config.h"
#include "vagn_filter.h"
#include "vagn_protocol.h"

#if VAGN_USE_VL53L4CD
#include <Wire.h>
#include <vl53l4cd_class.h>
#endif

// Överlever djupsömn.
RTC_DATA_ATTR static uint16_t g_seq = 0;
RTC_DATA_ATTR static float g_prev_mm = NAN;

static float g_samples[VAGN_SAMPLES];

#if VAGN_USE_VL53L4CD
static VL53L4CD g_vl53(&Wire, VAGN_VL53_XSHUT_PIN);

static bool measure_laser(vagn::Stats& out) {
  Wire.begin();
  g_vl53.begin();
  g_vl53.VL53L4CD_Off();
  if (g_vl53.InitSensor() != 0) {
    Serial.println("VL53L4CD: hittas inte");
    return false;
  }
  // 50 ms per mätning, kontinuerligt.
  g_vl53.VL53L4CD_SetRangeTiming(50, 0);
  g_vl53.VL53L4CD_StartRanging();

  size_t n = 0;
  for (int i = 0; i < VAGN_SAMPLES; ++i) {
    uint8_t ready = 0;
    uint32_t t0 = millis();
    while (!ready && millis() - t0 < 200) {
      g_vl53.VL53L4CD_CheckForDataReady(&ready);
      if (!ready) delay(2);
    }
    if (!ready) continue;
    g_vl53.VL53L4CD_ClearInterrupt();
    VL53L4CD_Result_t r;
    g_vl53.VL53L4CD_GetResult(&r);
    if (r.range_status == 0) g_samples[n++] = static_cast<float>(r.distance_mm);
  }
  g_vl53.VL53L4CD_StopRanging();
  g_vl53.VL53L4CD_Off();
  out = vagn::robust_stats(g_samples, n);
  return out.n > 0;
}
#endif

#if VAGN_USE_HCSR04
static bool measure_ultrasonic(vagn::Stats& out, float temp_c) {
  pinMode(VAGN_HCSR04_TRIG_PIN, OUTPUT);
  pinMode(VAGN_HCSR04_ECHO_PIN, INPUT);
  digitalWrite(VAGN_HCSR04_TRIG_PIN, LOW);
  size_t n = 0;
  for (int i = 0; i < VAGN_SAMPLES; ++i) {
    delayMicroseconds(4);
    digitalWrite(VAGN_HCSR04_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(VAGN_HCSR04_TRIG_PIN, LOW);
    unsigned long us = pulseIn(VAGN_HCSR04_ECHO_PIN, HIGH, 30000UL);
    if (us > 0) g_samples[n++] = vagn::echo_us_to_mm(static_cast<float>(us), temp_c);
    delay(60);  // låt ekot dö ut innan nästa mätning
  }
  out = vagn::robust_stats(g_samples, n);
  return out.n > 0;
}
#endif

static float simulated_mm() {
  // Långsam "lastning" fram och tillbaka mellan cirka 130 och 170 mm.
  float base = 150.0f + 20.0f * sinf(static_cast<float>(g_seq) / 20.0f);
  float noise = static_cast<float>(esp_random() % 100) / 100.0f - 0.5f;
  return base + noise;
}

static uint16_t read_battery_mv() {
#if VAGN_BATT_ADC_PIN >= 0
  uint32_t sum = 0;
  for (int i = 0; i < 8; ++i) sum += analogReadMilliVolts(VAGN_BATT_ADC_PIN);
  return static_cast<uint16_t>((sum / 8) * VAGN_BATT_DIVIDER);
#else
  return 0;
#endif
}

static vagn::Measurement take_measurement() {
  vagn::Measurement m;
  m.corner = VAGN_CORNER;
  m.seq = g_seq;
  m.temp_c = VAGN_DEFAULT_TEMP_C;
  m.battery_mv = read_battery_mv();
  if (m.battery_mv > 0 && m.battery_mv < VAGN_LOW_BATTERY_MV) m.flags |= vagn::FLAG_LOW_BATTERY;

  vagn::Stats laser, ultra;
  bool have_laser = false, have_ultra = false;
#if VAGN_USE_VL53L4CD
  have_laser = measure_laser(laser);
  if (have_laser) m.flags |= vagn::FLAG_LASER_OK;
#endif
#if VAGN_USE_HCSR04
  have_ultra = measure_ultrasonic(ultra, static_cast<float>(m.temp_c));
  if (have_ultra) m.flags |= vagn::FLAG_ULTRASONIC_OK;
#endif

  float mm;
  if (!VAGN_USE_VL53L4CD && !VAGN_USE_HCSR04) {
    mm = simulated_mm();
    m.flags |= vagn::FLAG_SIMULATED;
  } else {
    vagn::Fused f = vagn::fuse(have_laser ? &laser : nullptr, have_ultra ? &ultra : nullptr, g_prev_mm);
    if (!f.laser_used && !f.ultrasonic_used) {
      m.flags |= vagn::FLAG_SENSOR_FAULT;
      mm = 0.0f;
    } else {
      mm = f.distance_mm;
      if (f.disagree) m.flags |= vagn::FLAG_SENSOR_FAULT;
      g_prev_mm = mm;
    }
    Serial.printf("laser: n=%u medel=%.1f sd=%.2f | ultraljud: n=%u medel=%.1f sd=%.2f\n",
                  (unsigned)laser.n, laser.mean, laser.stddev, (unsigned)ultra.n, ultra.mean,
                  ultra.stddev);
  }
  m.distance_dmm = vagn::mm_to_dmm(mm);
  return m;
}

static void advertise(const vagn::Measurement& m) {
  uint8_t payload[vagn::kPayloadLen];
  size_t len = vagn::encode(m, payload);

  NimBLEDevice::init("");
  NimBLEDevice::setPower(VAGN_BLE_POWER);
  Serial.printf("sander som %s i %d ms\n", NimBLEDevice::getAddress().toString().c_str(), VAGN_ADV_MS);
  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();

  NimBLEAdvertisementData data;
  data.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  data.setManufacturerData(std::string(reinterpret_cast<const char*>(payload), len));
  adv->setAdvertisementData(data);
  adv->setScanResponse(false);
  adv->setMinInterval(160);  // 100 ms (enhet 0,625 ms)
  adv->setMaxInterval(160);
  adv->start();
  delay(VAGN_ADV_MS);
  adv->stop();
  NimBLEDevice::deinit(true);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  vagn::Measurement m = take_measurement();
  Serial.printf("vagnvag horn fw %s seq %u avstand %.1f mm batt %u mV flaggor 0x%02X\n",
                VAGN_FW_VERSION, m.seq, m.distance_dmm / 10.0f, m.battery_mv, m.flags);

  advertise(m);
  ++g_seq;

  Serial.printf("sover %d s\n", VAGN_SLEEP_S);
  Serial.flush();
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(VAGN_SLEEP_S) * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {}
