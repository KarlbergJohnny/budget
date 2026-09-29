// Radioprotokoll mellan hörnenhet och gateway.
//
// Hörnenheten sänder sin mätning som BLE manufacturer data i ett vanligt
// advertising-paket. Gatewayen lyssnar passivt och avkodar. Ingen anslutning
// eller parning behövs.
//
// Layout (14 byte, little endian):
//   [0..1]  company id 0xFFFF (reserverat för test och internt bruk)
//   [2]     magic 'V' (0x56)
//   [3]     protokollversion
//   [4]     hörn (Corner), 0xFF om okänt – servern mappar MAC -> hörn
//   [5..6]  sekvensnummer
//   [7..8]  avstånd i 0,1 mm
//   [9..10] batterispänning i mV
//   [11]    temperatur i °C (int8)
//   [12]    flaggor (Flags)
//   [13]    kontrollsumma: XOR av byte 2..12
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace vagn {

constexpr uint16_t kCompanyId = 0xFFFF;
constexpr uint8_t kMagic = 0x56;
constexpr uint8_t kVersion = 1;
constexpr size_t kPayloadLen = 14;

enum Corner : uint8_t { VL = 0, VR = 1, HL = 2, HR = 3, CORNER_UNKNOWN = 0xFF };

enum Flags : uint8_t {
  FLAG_SENSOR_FAULT = 1 << 0,
  FLAG_LASER_OK = 1 << 1,
  FLAG_ULTRASONIC_OK = 1 << 2,
  FLAG_MOVING = 1 << 3,
  FLAG_SIMULATED = 1 << 4,
  FLAG_LOW_BATTERY = 1 << 5,
};

struct Measurement {
  uint8_t corner = CORNER_UNKNOWN;
  uint16_t seq = 0;
  uint16_t distance_dmm = 0;  // 0,1 mm
  uint16_t battery_mv = 0;
  int8_t temp_c = 0;
  uint8_t flags = 0;
};

inline void put_u16(uint8_t* p, uint16_t v) {
  p[0] = static_cast<uint8_t>(v & 0xFF);
  p[1] = static_cast<uint8_t>(v >> 8);
}

inline uint16_t get_u16(const uint8_t* p) {
  return static_cast<uint16_t>(p[0] | (p[1] << 8));
}

inline uint8_t checksum(const uint8_t* buf) {
  uint8_t x = 0;
  for (size_t i = 2; i < kPayloadLen - 1; ++i) x ^= buf[i];
  return x;
}

// Skriver kPayloadLen byte till out.
inline size_t encode(const Measurement& m, uint8_t* out) {
  put_u16(out, kCompanyId);
  out[2] = kMagic;
  out[3] = kVersion;
  out[4] = m.corner;
  put_u16(out + 5, m.seq);
  put_u16(out + 7, m.distance_dmm);
  put_u16(out + 9, m.battery_mv);
  out[11] = static_cast<uint8_t>(m.temp_c);
  out[12] = m.flags;
  out[13] = checksum(out);
  return kPayloadLen;
}

// Returnerar false om paketet inte är ett giltigt vagnvåg-paket.
inline bool decode(const uint8_t* buf, size_t len, Measurement& m) {
  if (len != kPayloadLen) return false;
  if (get_u16(buf) != kCompanyId) return false;
  if (buf[2] != kMagic || buf[3] != kVersion) return false;
  if (buf[13] != checksum(buf)) return false;
  m.corner = buf[4];
  m.seq = get_u16(buf + 5);
  m.distance_dmm = get_u16(buf + 7);
  m.battery_mv = get_u16(buf + 9);
  m.temp_c = static_cast<int8_t>(buf[11]);
  m.flags = buf[12];
  return true;
}

inline uint16_t mm_to_dmm(float mm) {
  if (mm <= 0.0f) return 0;
  float d = mm * 10.0f + 0.5f;
  return d >= 65535.0f ? 65535 : static_cast<uint16_t>(d);
}

}  // namespace vagn
