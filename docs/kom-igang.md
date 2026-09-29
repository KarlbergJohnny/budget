# Kom igång: hörn → gateway → server → app

Så här får du hela kedjan att fungera på bänken, först utan hårdvara och sedan
med dina kort.

```
[Hörnenhet ESP32-C3]  --BLE advertising-->  [Gateway ESP32-S3]  --wifi/HTTP-->  [Server + app]
```

## 1. Starta servern (på datorn)

Kräver Python 3.10 eller senare.

```sh
cd server
pip install -r requirements.txt
VAGNVAG_INGEST_KEY=dev-key uvicorn vagnvag.main:app --host 0.0.0.0 --port 8000
```

- Startsidan finns nu på `http://localhost:8000` och själva appen på
  `http://localhost:8000/app.html`. I mobilen: `http://<datorns-ip>:8000`
  om mobilen är på samma wifi.
- Datan sparas i `vagnvag.db` i mappen där du startar servern.
- Välj en egen nyckel i stället för `dev-key` om servern syns utanför ditt nät.
  API:t för appen har ännu **ingen inloggning**. Kör den bara i ditt eget nät
  tills inloggning finns.

## 2. Testa utan hårdvara

I ett nytt terminalfönster:

```sh
python3 tools/simulate.py --url http://localhost:8000 --key dev-key
```

Simulatorn låtsas vara en gateway med fyra hörn. Vagnen är tom i 30 s och
lastas sedan under 2 minuter, lite snett fram till vänster.

I appen:
1. **Enheter** → registrera de fyra MAC-adresserna (`aa:bb:cc:dd:ee:01`–`04`)
   på samma vagnsnummer, en per hörn (VL, VR, HL, HR).
2. Öppna vagnen → **Inställningar** → skriv in tomvikten, t.ex. 20000 kg.
3. Medan vagnen fortfarande är tom: **Bekräfta tom vagn**. Då sätts nollpunkterna.
4. Se vikten stiga när simulatorn "lastar".

## 3. Hörnenheten (Olimex ESP32-C3-DevKit-Lipo)

Installera [PlatformIO](https://platformio.org/install/cli) (eller
PlatformIO-tillägget i VS Code).

```sh
cd firmware/corner
pio run -e olimex_c3 -t upload
pio device monitor -e olimex_c3
```

Utan givare skickar enheten **simulerade** värden (flaggan "Simulerade värden"
syns i appen). I serieterminalen ser du MAC-adressen den sänder med. Den
behöver du när du registrerar enheten.

När VL53L4CD är inkopplad (Qwiic-kabel till UEXT-kontaktens 3,3 V, GND, SDA och SCL):

```sh
pio run -e olimex_c3_vl53l4cd -t upload
```

Inställningar som sömntid, antal mätningar och stift finns i
`firmware/corner/include/config.h` och kan ändras med `-D` i `platformio.ini`.

## 4. Gatewayen (Arduino Nano ESP32, senare LilyGO)

```sh
cd firmware/gateway
cp include/secrets.example.h include/secrets.h   # fyll i wifi, serverns IP och nyckel
pio run -e nano_esp32 -t upload
pio device monitor -e nano_esp32
```

`SERVER_URL` ska vara datorns IP-adress i ditt nät, till exempel
`http://192.168.1.20:8000`, inte `localhost`.

Serieterminalen visar hur många paket som tagits emot och när de skickas till
servern. I appen syns gatewayen under **Gateways** och hörnen under **Enheter**.

Andra kort: `-e d1r32` (Wemos D1 R32) eller `-e lilygo_sim7080g_s3` (wifi
tills LTE-M är klart).

## 5. Tester

```sh
./firmware/test_native/run.sh        # protokoll och mätfilter, körs på datorn
cd server && python3 -m pytest -q    # server: vikt, nollställning, API
```

## Känt läge

- Firmwaren är skriven men har **inte kompilerats** ännu, eftersom
  PlatformIO:s paketregister inte gick att nå i miljön där den skrevs. Räkna med
  att du kan behöva rätta några kompileringsfel första gången.
- Stödet för VL53L4CD och HC-SR04 är oprövat mot riktiga givare.
- Batterimätningen på Olimex-kortet är avstängd (`VAGN_BATT_ADC_PIN -1`) tills
  vi har kontrollerat stiftet i schemat för din revision.
- LTE-M och GPS på LilyGO-kortet kommer i nästa steg.
- Standardkalibreringen 350 kg/mm är en grov gissning för Y25. Den måste
  ersättas med en kalibrering mot spårvåg.

## Radioprotokollet

Hörnet sänder 14 byte som BLE manufacturer data (company id `0xFFFF`), se
`firmware/lib/vagn_common/src/vagn_protocol.h`: hörn, sekvensnummer, avstånd i
0,1 mm, batteri i mV, temperatur, flaggor och en kontrollsumma. Gatewayen
avkodar paketet och skickar det som JSON till `POST /api/v1/ingest` med
huvudet `X-API-Key`.
