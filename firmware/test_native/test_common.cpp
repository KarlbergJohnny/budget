// Enhetstester för vagn_common som körs på datorn. Kör med:
//   ./firmware/test_native/run.sh
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "vagn_filter.h"
#include "vagn_protocol.h"

static int failures = 0;

#define CHECK(cond)                                               \
  do {                                                            \
    if (!(cond)) {                                                \
      printf("FEL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
      ++failures;                                                 \
    }                                                             \
  } while (0)

#define CHECK_NEAR(a, b, tol) CHECK(fabs((double)(a) - (double)(b)) <= (tol))

static void test_roundtrip() {
  vagn::Measurement m;
  m.corner = vagn::HR;
  m.seq = 54321;
  m.distance_dmm = vagn::mm_to_dmm(123.45f);
  m.battery_mv = 3987;
  m.temp_c = -23;
  m.flags = vagn::FLAG_LASER_OK | vagn::FLAG_SIMULATED;

  uint8_t buf[vagn::kPayloadLen];
  CHECK(vagn::encode(m, buf) == vagn::kPayloadLen);
  CHECK(buf[0] == 0xFF && buf[1] == 0xFF && buf[2] == 'V');

  vagn::Measurement out;
  CHECK(vagn::decode(buf, sizeof(buf), out));
  CHECK(out.corner == vagn::HR);
  CHECK(out.seq == 54321);
  CHECK(out.distance_dmm == 1235);
  CHECK(out.battery_mv == 3987);
  CHECK(out.temp_c == -23);
  CHECK(out.flags == m.flags);
}

static void test_decode_rejects() {
  vagn::Measurement m;
  uint8_t buf[vagn::kPayloadLen];
  vagn::encode(m, buf);
  vagn::Measurement out;

  CHECK(!vagn::decode(buf, sizeof(buf) - 1, out));

  uint8_t bad[vagn::kPayloadLen];
  memcpy(bad, buf, sizeof(buf));
  bad[8] ^= 0x01;  // ändra avståndet utan att uppdatera kontrollsumman
  CHECK(!vagn::decode(bad, sizeof(bad), out));

  memcpy(bad, buf, sizeof(buf));
  bad[0] = 0x4C;  // annat företags-id (Apple)
  CHECK(!vagn::decode(bad, sizeof(bad), out));

  memcpy(bad, buf, sizeof(buf));
  bad[3] = 99;  // okänd version
  bad[13] = vagn::checksum(bad);
  CHECK(!vagn::decode(bad, sizeof(bad), out));
}

static void test_mm_to_dmm_limits() {
  CHECK(vagn::mm_to_dmm(-5.0f) == 0);
  CHECK(vagn::mm_to_dmm(0.04f) == 0);
  CHECK(vagn::mm_to_dmm(0.05f) == 1);
  CHECK(vagn::mm_to_dmm(99999.0f) == 65535);
}

static void test_robust_stats_removes_outlier() {
  float v[] = {100.1f, 99.9f, 100.0f, 100.2f, 99.8f, 100.0f, 250.0f, 100.1f};
  vagn::Stats s = vagn::robust_stats(v, sizeof(v) / sizeof(v[0]));
  CHECK(s.n == 7);
  CHECK_NEAR(s.mean, 100.014, 0.01);
  CHECK(s.stddev < 0.2f);
}

static void test_robust_stats_edge_cases() {
  vagn::Stats empty = vagn::robust_stats(nullptr, 0);
  CHECK(empty.n == 0);
  float one[] = {42.0f};
  vagn::Stats s1 = vagn::robust_stats(one, 1);
  CHECK(s1.n == 1);
  CHECK_NEAR(s1.mean, 42.0, 1e-6);
  CHECK_NEAR(s1.stddev, 0.0, 1e-6);
}

static void test_ultrasonic_temperature() {
  CHECK_NEAR(vagn::speed_of_sound(0.0f), 331.3, 1e-3);
  CHECK_NEAR(vagn::speed_of_sound(20.0f), 343.42, 1e-3);
  // 1000 µs vid 20 °C => 171,71 mm
  CHECK_NEAR(vagn::echo_us_to_mm(1000.0f, 20.0f), 171.71, 0.01);
  // Samma ekotid i -20 °C ger kortare avstånd
  CHECK(vagn::echo_us_to_mm(1000.0f, -20.0f) < vagn::echo_us_to_mm(1000.0f, 20.0f));
}

static vagn::Stats mk(float mean, float sd) {
  vagn::Stats s;
  s.mean = mean;
  s.stddev = sd;
  s.n = 20;
  return s;
}

static void test_fuse_weights_by_variance() {
  vagn::Stats l = mk(100.0f, 1.0f);
  vagn::Stats u = mk(102.0f, 2.0f);
  vagn::Fused f = vagn::fuse(&l, &u, NAN);
  CHECK(!f.disagree);
  CHECK(f.laser_used && f.ultrasonic_used);
  // w_l = 1, w_u = 0,25 => (100 + 0,25*102)/1,25 = 100,4
  CHECK_NEAR(f.distance_mm, 100.4, 1e-3);
  CHECK(f.sigma_mm < 1.0f);
}

static void test_fuse_disagreement_uses_previous() {
  vagn::Stats l = mk(100.0f, 0.5f);
  vagn::Stats u = mk(140.0f, 1.0f);  // t.ex. is på ultraljudet
  vagn::Fused f = vagn::fuse(&l, &u, 139.0f);
  CHECK(f.disagree);
  CHECK(f.ultrasonic_used && !f.laser_used);
  CHECK_NEAR(f.distance_mm, 140.0, 1e-3);

  vagn::Fused g = vagn::fuse(&l, &u, NAN);
  CHECK(g.disagree);
  CHECK(g.laser_used);  // utan historik litar vi på lasern
}

static void test_fuse_single_sensor() {
  vagn::Stats l = mk(80.0f, 0.3f);
  vagn::Fused f = vagn::fuse(&l, nullptr, NAN);
  CHECK(f.laser_used && !f.ultrasonic_used);
  CHECK_NEAR(f.distance_mm, 80.0, 1e-6);

  vagn::Fused none = vagn::fuse(nullptr, nullptr, NAN);
  CHECK(!none.laser_used && !none.ultrasonic_used);
}

int main() {
  test_roundtrip();
  test_decode_rejects();
  test_mm_to_dmm_limits();
  test_robust_stats_removes_outlier();
  test_robust_stats_edge_cases();
  test_ultrasonic_temperature();
  test_fuse_weights_by_variance();
  test_fuse_disagreement_uses_previous();
  test_fuse_single_sensor();
  if (failures) {
    printf("%d test(er) misslyckades\n", failures);
    return 1;
  }
  printf("Alla tester OK\n");
  return 0;
}
