// Inställningar för hörnenheten. Allt kan skrivas över med -D i platformio.ini.
#pragma once

// Hörn som sänds i paketet. Lämna CORNER_UNKNOWN (0xFF) och registrera enheten
// i appen i stället: servern kopplar MAC-adressen till vagn och hörn.
#ifndef VAGN_CORNER
#define VAGN_CORNER 0xFF
#endif

// Hur länge enheten sänder efter varje mätning.
#ifndef VAGN_ADV_MS
#define VAGN_ADV_MS 2000
#endif

// Sömn mellan mätningarna. Kort på bänken, längre ute (t.ex. 600 s).
#ifndef VAGN_SLEEP_S
#define VAGN_SLEEP_S 10
#endif

// Antal mätningar per tillfälle innan robust medelvärde.
#ifndef VAGN_SAMPLES
#define VAGN_SAMPLES 25
#endif

// Sändarstyrka för BLE (ESP_PWR_LVL_N0 .. ESP_PWR_LVL_P9).
#ifndef VAGN_BLE_POWER
#define VAGN_BLE_POWER ESP_PWR_LVL_P9
#endif

// ---- Givare ----

#ifndef VAGN_USE_VL53L4CD
#define VAGN_USE_VL53L4CD 0
#endif
// XSHUT-stift för VL53L4CD, -1 om det inte är kopplat.
#ifndef VAGN_VL53_XSHUT_PIN
#define VAGN_VL53_XSHUT_PIN -1
#endif

#ifndef VAGN_USE_HCSR04
#define VAGN_USE_HCSR04 0
#endif
#ifndef VAGN_HCSR04_TRIG_PIN
#define VAGN_HCSR04_TRIG_PIN 4
#endif
// Ekosignalen är 5 V på HC-SR04: använd spänningsdelare (1 kΩ / 2 kΩ).
#ifndef VAGN_HCSR04_ECHO_PIN
#define VAGN_HCSR04_ECHO_PIN 5
#endif

// ADC-stift för batterispänning via spänningsdelare, -1 om inget finns.
// Kontrollera Olimex schema för din revision (Rev B/C) innan du sätter det.
#ifndef VAGN_BATT_ADC_PIN
#define VAGN_BATT_ADC_PIN -1
#endif
// Faktor från stiftets spänning till batteriets (t.ex. 2.0 för delare 1:1).
#ifndef VAGN_BATT_DIVIDER
#define VAGN_BATT_DIVIDER 2.0f
#endif

#ifndef VAGN_LOW_BATTERY_MV
#define VAGN_LOW_BATTERY_MV 3450
#endif

// Temperatur som används för ultraljudet tills en temperaturgivare finns.
#ifndef VAGN_DEFAULT_TEMP_C
#define VAGN_DEFAULT_TEMP_C 20
#endif
