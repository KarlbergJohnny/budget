# Överlämning – så långt har vi kommit

Skriven 2026-09-29 för att fortsätta arbetet i Claude CLI. Läs även
`VAGNVAG.md` (projektbeskrivning, patentgränser, arkitektur) och
`docs/kom-igang.md` (hur allt startas).

## Vad projektet är

Ett eftermonterat lastviktsystem för godsvagnar (Y25-boggier):

- **4 hörnenheter** med magnetfäste på boggiramen. Varje enhet mäter avståndet
  ner till en målplåt på axelboxen med **laser (VL53L4CD)** och
  **ultraljud**, och sänder värdet som **BLE advertising**.
- **1 gateway** på vagnens sida (LilyGO T-SIM7080G-S3: ESP32-S3, LTE-M, GPS,
  solcell) som tar emot hörnens värden och skickar dem till servern.
- **Server och app** som räknar ut vikt och snedlastning och visar dem i mobilen.
- Affärsmodell: abonnemang per vagn och månad.

## Patentgränser (viktigast)

- RMD:s patent **SE2350203-2** (US 12522265) kräver **radiovågor (radar)** mot
  **räls eller mark**, med minst fyra detektorer. Vi har läst beskrivningen och
  sammandraget från ansökan (22 februari 2023), men **inte de beviljade kraven**.
- Använd därför **aldrig radar för att mäta avstånd eller vikt**. Mät **internt**
  (boggiram ↔ axelbox) med laser och ultraljud. RMD skriver själva att radar är
  bättre än lidar och ultraljud, så de har avgränsat sig mot dem.
- RMD har också **SE2250761-0** (radar för hjulens status) och produkten ATD
  (automatisk tågavgång). RMD:s "Weight Sensor" på deras webbsida ser ut att
  använda givare på boggiramens sida (troligen töjning i ramen), vilket kan vara
  det nya patentet för vagnvikt från 2026. **Det patentet har vi inte hittat än.**
- RMD:s temperaturgivare är smarta bultar från **Strainlabs**. Tänk på deras
  patent om temperatur i axelboxen byggs.

## Klart och verifierat

| Del | Var | Verifierat |
|---|---|---|
| Radioprotokoll (14 byte med kontrollsumma) | `firmware/lib/vagn_common/src/vagn_protocol.h` | Enhetstester på datorn |
| Mätfilter: robust medelvärde, temperaturkompensering av ultraljud, viktad sammanslagning av laser och ultraljud | `firmware/lib/vagn_common/src/vagn_filter.h` | Enhetstester på datorn |
| Server: mottagning, registrering, vikt, snedlastning, nollställning med rimlighetskontroll, historik, händelselogg | `server/vagnvag/` | 21 pytest-tester |
| Webbapp: vagnar, hörn, enheter, gateways, tom vagn, inställningar | `app/app.html`, `app.js`, `style.css` | Körd mot simulatorn i Chromium, 360 och 390 px utan horisontell scroll |
| Startsida med 3D-scen och lysande menyer | `app/index.html`, `landing.css`, `landing.js` | Skärmbilder på dator och mobil, inga konsolfel |
| Simulator (gateway med 4 hörn) | `tools/simulate.py` | Hela kedjan gav 76,2 t med förväntad snedlast |

Kör testerna:

```sh
./firmware/test_native/run.sh
cd server && pip install -r requirements.txt && python3 -m pytest -q
```

## Skrivet men INTE kompilerat

PlatformIO:s paketregister var blockerat i miljön där koden skrevs, så detta är
aldrig byggt. Räkna med kompileringsfel att rätta första gången.

- `firmware/corner/` – hörnenhet: mäter (eller simulerar), sänder BLE i 2 s,
  djupsömn i 10 s. Miljöer: `olimex_c3`, `olimex_c3_vl53l4cd`, `nano_esp32`, `d1r32`.
- `firmware/gateway/` – skannar BLE, skickar JSON via wifi. Miljöer:
  `nano_esp32`, `d1r32`, `lilygo_sim7080g_s3`. Kopiera
  `include/secrets.example.h` till `include/secrets.h` först.
- Beroenden: NimBLE-Arduino 1.4.x (API:t skiljer sig i 2.x), ArduinoJson 7,
  STM32duino VL53L4CD.

Saker att kontrollera när det byggs:

- `NimBLEAdvertisedDeviceCallbacks` och `scan->start(0, nullptr, false)`
  förutsätter NimBLE 1.4.
- VL53L4CD-biblioteket med `XSHUT = -1`: kontrollera att det tillåts.
- Olimex C3: `ARDUINO_USB_CDC_ON_BOOT=1` antas ge seriell utskrift via USB-C.

## Nästa steg

1. **Kompilera och flasha** hörnet (`olimex_c3`) och gatewayen (`nano_esp32`),
   och se att enheten dyker upp under Enheter i appen.
2. **Publicera startsidan.** Frågor som behöver svar:
   - Domän: `railplatform.karlberg.nu`? (Användaren skrev "karlbegr".)
   - Hosting: GitHub Pages (kräver att repot är publikt eller ett betalt konto,
     plus en CNAME-post i DNS) eller eget webbhotell.
   - Kontaktadressen på knappen "Bli pilotkund" är platshållaren
     `kontakt@example.com` i `app/index.html` och måste bytas.
   - Bara startsidan är statisk. `app.html` behöver servern och ska **inte**
     publiceras öppet förrän det finns inloggning.
3. **LTE-M och GPS** på LilyGO-kortet (SIM7080G via AT-kommandon, strömhantering
   med AXP2101). Kräver ett IoT-SIM med LTE-M.
4. **Djupsömn med väckning via IMU** (LSM6DSO INT1 till GPIO 0–5 på C3).
5. **Batterimätning** på Olimex-kortet: kontrollera stiftet i schemat för Rev B
   och Rev C och sätt `VAGN_BATT_ADC_PIN`.
6. **Inloggning** i appen och API:t.
7. **Hitta RMD:s patent från 2026** och läs de beviljade kraven för SE2350203-2.

## Hårdvara som är beställd eller finns

- 4 × Olimex ESP32-C3-DevKit-Lipo (2 Rev B, 2 nya) – hörnenheter
- 2 × LilyGO T-SIM7080G-S3 – gateway på bänken och gateway i bil för tester
- Arduino Nano ESP32 och Wemos D1 R32 – bänk och reserv
- 2 × VL53L4CD Qwiic, 2 × HC-SR04, HW-123 (MPU-6050)
- 2 × LG MH1 18650 (till LilyGO), 2 × 18650 med JST (till C3, kontrollera polariteten)
- Qwiic-kablar (100 mm och till Dupont-hylsor)
- Saknas eller planeras: LSM6DSO Qwiic (5–6 st), fler lasrar (VL53L1X Qwiic),
  vattentät ultraljudsgivare (A02YYUW eller motsvarande), IP67-lådor,
  gummiklädda magneter, målplåtar, IoT-SIM med LTE-M.

## Tips

- HC-SR04 behöver 5 V och ger en ekosignal på 5 V. Använd en spänningsdelare mot
  ESP32:ns 3,3 V-stift. Olimex C3 har 5 V bara när USB är inkopplat.
- Välj "By Arduino pin" i Arduino IDE för Nano ESP32. PlatformIO använder GPIO-nummer.
- Qwiic-kablarna med Dupont-hylsor passar direkt på C3-kortets hanstift (UEXT och EXT).
