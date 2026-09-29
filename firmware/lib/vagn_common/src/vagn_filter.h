// Mätbehandling som delas av hörnenheterna: robust medelvärde, temperatur-
// kompensering av ultraljud och viktad sammanslagning av laser och ultraljud.
// Ren C++ utan Arduino-beroenden så att det går att testa på datorn.
#pragma once

#include <math.h>
#include <stddef.h>

namespace vagn {

struct Stats {
  float mean = 0.0f;
  float stddev = 0.0f;
  size_t n = 0;  // antal värden som återstod efter filtrering
};

inline void sort_floats(float* v, size_t n) {
  for (size_t i = 1; i < n; ++i) {
    float x = v[i];
    size_t j = i;
    while (j > 0 && v[j - 1] > x) {
      v[j] = v[j - 1];
      --j;
    }
    v[j] = x;
  }
}

inline float quantile_sorted(const float* v, size_t n, float q) {
  if (n == 0) return 0.0f;
  float pos = q * static_cast<float>(n - 1);
  size_t lo = static_cast<size_t>(pos);
  size_t hi = lo + 1 < n ? lo + 1 : lo;
  float frac = pos - static_cast<float>(lo);
  return v[lo] + (v[hi] - v[lo]) * frac;
}

// Tar bort extremvärden utanför [Q1 - 1,5·IQR, Q3 + 1,5·IQR] och räknar
// medelvärde och standardavvikelse på resten. Sorterar v på plats.
inline Stats robust_stats(float* v, size_t n) {
  Stats s;
  if (n == 0) return s;
  sort_floats(v, n);
  float q1 = quantile_sorted(v, n, 0.25f);
  float q3 = quantile_sorted(v, n, 0.75f);
  float iqr = q3 - q1;
  float lo = q1 - 1.5f * iqr;
  float hi = q3 + 1.5f * iqr;
  double sum = 0.0;
  size_t k = 0;
  for (size_t i = 0; i < n; ++i) {
    if (v[i] >= lo && v[i] <= hi) {
      sum += v[i];
      ++k;
    }
  }
  if (k == 0) return s;
  double mean = sum / static_cast<double>(k);
  double var = 0.0;
  for (size_t i = 0; i < n; ++i) {
    if (v[i] >= lo && v[i] <= hi) {
      double d = v[i] - mean;
      var += d * d;
    }
  }
  s.mean = static_cast<float>(mean);
  s.stddev = k > 1 ? static_cast<float>(sqrt(var / static_cast<double>(k - 1))) : 0.0f;
  s.n = k;
  return s;
}

// Ljudets hastighet i luft, m/s.
inline float speed_of_sound(float temp_c) { return 331.3f + 0.606f * temp_c; }

// Ekotid (µs, fram och tillbaka) till avstånd i mm.
inline float echo_us_to_mm(float echo_us, float temp_c) {
  return echo_us * speed_of_sound(temp_c) / 2000.0f;
}

struct Fused {
  float distance_mm = 0.0f;
  float sigma_mm = 0.0f;
  bool laser_used = false;
  bool ultrasonic_used = false;
  bool disagree = false;
};

// Inversvariansviktning av två mätningar. Om de skiljer sig mer än
// k·sqrt(σu² + σl²) används bara den som ligger närmast previous_mm
// (senaste giltiga värde, eller NAN om inget finns) och disagree sätts.
inline Fused fuse(const Stats* laser, const Stats* ultra, float previous_mm, float k = 3.0f,
                  float min_sigma_mm = 0.5f) {
  Fused f;
  bool have_l = laser && laser->n > 0;
  bool have_u = ultra && ultra->n > 0;
  if (!have_l && !have_u) return f;
  if (have_l && !have_u) {
    f.distance_mm = laser->mean;
    f.sigma_mm = laser->stddev;
    f.laser_used = true;
    return f;
  }
  if (!have_l && have_u) {
    f.distance_mm = ultra->mean;
    f.sigma_mm = ultra->stddev;
    f.ultrasonic_used = true;
    return f;
  }
  float sl = laser->stddev > min_sigma_mm ? laser->stddev : min_sigma_mm;
  float su = ultra->stddev > min_sigma_mm ? ultra->stddev : min_sigma_mm;
  float diff = fabsf(laser->mean - ultra->mean);
  if (diff > k * sqrtf(sl * sl + su * su)) {
    f.disagree = true;
    bool pick_laser = true;
    if (!isnan(previous_mm)) {
      pick_laser = fabsf(laser->mean - previous_mm) <= fabsf(ultra->mean - previous_mm);
    }
    f.distance_mm = pick_laser ? laser->mean : ultra->mean;
    f.sigma_mm = pick_laser ? sl : su;
    f.laser_used = pick_laser;
    f.ultrasonic_used = !pick_laser;
    return f;
  }
  float wl = 1.0f / (sl * sl);
  float wu = 1.0f / (su * su);
  f.distance_mm = (wl * laser->mean + wu * ultra->mean) / (wl + wu);
  f.sigma_mm = sqrtf(1.0f / (wl + wu));
  f.laser_used = true;
  f.ultrasonic_used = true;
  return f;
}

}  // namespace vagn
