# Vagnvåg – lastviktsystem för godsvagnar

Projektbeskrivning och instruktioner för utveckling. Läs hela filen innan du börjar koda.

## Mål

Ett billigt system som eftermonteras på godsvagnar och mäter **vagnens vikt och
snedlastning under lastning**. Allt monteras med magneter, utan borrning,
svetsning eller kablar. Kunden betalar ett abonnemang per vagn och månad, och
vi äger hårdvaran.

- Version 1 mäter **bara när vagnen står still under lastning**. Ingen lastar
  under färd.
- Varje vagn är **uppkopplad från början**, med LTE-M och GPS.
- Senare: automatisk vagnupptagning och tågsammansättning (se "Framtid").

## Patentgränser, som aldrig får brytas

Railway Metrics and Dynamics (RMD) har patentet **SE2350203-2** (US 12522265),
"System and method for determining a weight status of a railway vehicle",
inlämnat 2023-02-22. Enligt ansökan och det amerikanska kravet 1 kräver det
alla dessa kännetecken samtidigt:

1. minst en sändare av **radiovågor** (3 Hz–3000 GHz enligt beskrivningen)
2. **minst fyra detektorer** på vagnen, som tar emot radiovågorna
3. avstånd eller förskjutning mot **räls, banvall eller mark**
4. en beräkningsenhet som räknar fram en viktstatus

I beskrivningen (s. 5) skriver RMD själva att radiovågor är bättre än
**lidar och ultraljud**. Magnetfäste, IMU, temperaturgivare, friktionsmått,
kurvor mellan fjädring och last samt maskininlärning nämns bara som tillägg
till radarsystemet.

Därför gäller:

- **Använd ALDRIG radar eller andra radiovågor för att mäta avstånd eller vikt,
  oavsett antal givare.** Radio får bara användas för kommunikation (BLE,
  ESP-NOW, LTE) och för GPS.
- Mät avstånd med **ultraljud** och **laser**.
- Mät **internt i fjädringen**, mellan boggiram och axelbox. Mät inte mot räls
  eller mark.
- RMD har också **SE2250761-0** (radar för att bedöma hjulets status) och säljer
  **ATD** (automatisk tågavgång). Bygg ingen analys av hjul eller vibrationer och
  ingen automatisk tågsammansättning för kunder utan att först ha läst de
  relevanta patenten.
- Dokumentera designbeslut med datum i `docs/beslut.md`, inklusive skälen
  kopplade till patenten.

De **beviljade** kraven har vi ännu inte kontrollerat, se "Öppna frågor".

## Systemöversikt

```
          Vagnens sida (sol, fri sikt mot himlen)
        ┌────────────────────────────────────┐
        │ GATEWAY  ESP32-S3 + SIM7080G       │
        │ LTE-M/NB-IoT + GPS, solcell, IMU   │──── LTE-M ───> server/app
        └───────────────▲────────────────────┘
                        │ BLE advertising (ESP-NOW som reserv)
     ┌─────────────┬────┴────────┬─────────────┐
 [Hörn VL]     [Hörn VR]     [Hörn HL]     [Hörn HR]
  boggi 1       boggi 1       boggi 2       boggi 2
  ultraljud + laser + IMU + temperatur, eget batteri
     │             │             │             │
     ▼             ▼             ▼             ▼
  målplåt       målplåt       målplåt       målplåt
  (magnet på axelboxens ovansida)
```

Per vagn: **4 identiska hörnenheter** och **1 gateway**. Inga kablar mellan dem.

## Hårdvara

### Hörnenhet (4 per vagn)

| Del | Prototyp | Produkt |
|---|---|---|
| Processor och BLE | Seeed **XIAO ESP32-S3** (eller Adafruit QT Py ESP32-S3 med inbyggd Qwiic) | Eget kort med **nRF52840** |
| Ultraljud | **DFRobot A02YYUW** (vattentät, UART) | **MaxBotix** IP67, 1 mm upplösning |
| Laser | **VL53L1X** (I2C 0x29), bakom ett fönster | Industriell lasergivare med triangulering, under 1 mm |
| IMU | **LSM6DSO** (I2C 0x6A) eller BMI270, med väckning vid rörelse | Samma |
| Temperatur | Inbyggd i IMU:n, eller DS18B20 | Samma |
| Lastbrytare för ultraljudet | **TPS22918** | Samma |
| Minne | SD-kort (pilot: tät loggning) | Flash på kortet |
| Batteri | LiPo + **Qi-mottagare** (**BQ51050B**, laddning med temperaturspärr) | **Li-SOCl₂** D-cell, 17–19 Ah, räcker i flera år |
| Låda | IP67, gummibussningar, skyddslack, tryckutjämningsventil, fuktabsorberare | Eventuellt ingjuten i mjuk silikongel med givarnas framsidor fria |
| Fäste | 2 gummiklädda magneter (värmeklass SH) och säkringsvajer | Samma |

### Gateway (1 per vagn)

| Del | Val |
|---|---|
| Kort | **LilyGO T-SIM7080G-S3** (ESP32-S3, SIM7080G LTE-M/NB-IoT med GPS, solladdning, 18650-hållare). Alternativ: Walter. |
| Ström | Solcell och 18650, laddning bara över 0 °C. Kondensator vid modemet för sändningstopparna på cirka 0,5 A. |
| IMU | LSM6DSO, för väckning och spårets lutning |
| Antenn | Utanpå vagnens stål, på lådans ovansida |
| Fäste | Magnet på vagnens sida, säkringsvajer |

### Kopplingar i hörnenheten (prototyp)

```
XIAO ESP32-S3
  3V3, GND, D4 (SDA), D5 (SCL) ── Qwiic-kabel ── LSM6DSO ── Qwiic ── VL53L1X
  D0 ◄── INT1 från IMU (väckning, RTC-kapabel pin)
  D1 ──► XSHUT på VL53L1X (av och på)
  D2 ──► EN på TPS22918 ──► VCC till A02YYUW
  D7 (RX) ◄── TX från A02YYUW (RX på givaren lämnas fri)
  BAT+/BAT− ── LiPo, via Qi-mottagaren
```

- Qwiic-kablar (JST-SH 4-pol) för I2C. JST-GH för övriga signaler i den skarpa versionen.
- IMU:n har alltid ström. Lasern stängs av med XSHUT. Ultraljudet stängs av med lastbrytaren.
- Använd **inte** IMU:ns magnetometer, eftersom fästmagneterna stör den.
- Kontrollera kabelfärgerna på A02YYUW mot databladet.

### Mekanisk montering

```
  ┌──────── Hörnenhet (magnet mot boggiramen) ───────┐
  │  [Batteri]          [Kort + IMU]                 │
  │  ┌──────────┐        ┌──────────┐                │
  └──┤Ultraljud ├────────┤ VL53L1X  ├────────────────┘
     │genom vägg│        │bakom glas│
     └────┬─────┘        └────┬─────┘
          ▼                   ▼
   ═══════════════════════════════  målplåt (magnet)
          axelboxens ovansida
```

- Hörnenheten sitter på **boggiramen** (fjädrad del), rakt ovanför axelboxen.
- En plan **målplåt** av stål sitter med magnet på **axelboxens ovansida**
  (ofjädrad del). Mät aldrig mot själva axeln, eftersom den roterar.
- Fästmagneterna ska sitta minst 5–10 cm från givarna och från Qi-spolen.
- Alla hörnenheter monteras **vända utåt** från vagnen, så att de ska kunna
  avgöra om de sitter på vänster eller höger sida (se "Självplacering").
- Använd en monteringsmall med mått från fasta referenspunkter på Y25-boggin.

## Kommunikation och tid

- **Hörn → gateway:** BLE **advertising**. Hörnet vaknar, mäter och sänder
  resultatet som advertising-paket i 2–3 s. Gatewayen skannar. Ingen anslutning
  eller parning behövs. Använd BLE 5 **Coded PHY** om räckvidden under vagnen
  inte räcker. ESP-NOW finns som reserv i firmware (ESP32 i prototypen).
- **Gateway → server:** LTE-M (NB-IoT som reserv), MQTT eller HTTPS, med PSM
  mellan sändningarna.
- **Mobil ↔ hörn eller gateway:** BLE-anslutning för montering, felsökning och
  visning av vikten i realtid under lastning.
- **Väckning:** alla enheter har en IMU och vaknar av samma stötar när lastningen
  börjar. Hörnen sänder upprepade gånger. Gatewayen skannar så länge lastningen
  pågår.
- **Tid:** gatewayen tar tiden från GPS och sänder den i sina svar eller
  advertising-paket. Hörnen tidsstämplar varje mätning. För tester av
  tågsammansättning i piloten används GPS:ens **PPS-signal** för
  millisekundsynk.
- **Buffert:** mätningar som inte har bekräftats sparas i hörnet och skickas
  igen vid nästa kontakt.

## Firmware

Använd **PlatformIO**, Arduino eller ESP-IDF, i C++. Hörnen och gatewayen har
separata byggmål men delar protokoll och beräkningskod.

### Tillstånd (hörnenhet)
1. **DEEP_SLEEP:** bara IMU:n är vaken. Väcks av IMU-avbrott eller en timer var 10:e minut.
2. **IDLE_CHECK:** en snabb mätning. Tillbaka till DEEP_SLEEP om inget har ändrats.
3. **LOADING:** stötar i följd eller en förändrad vikt. Mät var 10:e–30:e sekund.
4. **SETTLED:** vikten är stabil i X minuter. Spara, sänd och gå till DEEP_SLEEP.
5. **MOVING:** ihållande acceleration eller rotation. Mät ingen vikt. (Piloten:
   logga IMU-data i hög takt till SD-kortet.)

### Mätning per hörn
1. Slå på givarna. Vänta tills de är klara att mäta.
2. Ta **N = 50–100** mätningar per givare. Ta bort extremvärden med median eller IQR.
3. Kompensera ultraljudet för temperaturen: `c = 331.3 + 0.606·T` (m/s), `d = t·c/2`.
4. Räkna μ och σ per givare.
5. **Inversvariansviktning:** `w_i = 1/σ_i²`, `d = Σ(w_i·d_i)/Σw_i`.
6. **Stämmer de inte överens?** Om `|d_u − d_l| > k·sqrt(σ_u² + σ_l²)`
   (börja med k = 3): använd den givare som stämmer med den senaste giltiga
   mätningen och sätt flaggan `sensor_fault`.
7. Stäng av givarna.

### Från avstånd till vikt (på servern, med samma kod i gatewayen)
- En kalibreringskurva per hörn, från hoptryckning (mm) till last (kN).
  Styckvis linjär med minst 3–4 punkter (Y25 har två fjäderstadier).
- Nollpunkt: tarvikten, alltså tomvikten som står målad på vagnen.
- Totalvikt `Σ F_i / g`.
- Snedlastning:
  - fram–bak: `(F_VL+F_VR) − (F_HL+F_HR)`
  - vänster–höger: `(F_VL+F_HL) − (F_VR+F_HR)`, korrigerat för spårets lutning från gatewayens IMU
  - diagonalt: `(F_VL+F_HR) − (F_VR+F_HL)`
- Y25:s friktionsdämpare ger hysteres. Använd värdet efter SETTLED och spara
  hela kurvan från lastningen.

### Automatisk nollställning
- Utlöses när vagnen är bekräftat tom (se nedan) **och** mätvärdena ligger
  inom ±2–3 mm (konfigurerbart) från den nuvarande nollpunkten.
- Nollpunkten glider långsamt: medelvärdet av de 5–10 senaste tomma tillfällena.
- Ett stort hopp får **aldrig** ge en ny kalibrering. Sätt i stället flaggan
  `mount_check`, eftersom enheten eller målplåten troligen har flyttat sig.
- Lutningen på kurvan (mm per ton) kontrolleras mot en spårvåg ungefär en gång
  om året.

### Bekräfta att vagnen är tom
1. **I appen** (huvudsätt): skanna vagnens eller enhetens QR-kod och bekräfta.
   Loggas med vem och när.
2. **Magnetkontakt på lådan** (reserv): en reedkontakt eller Hall-givare som
   aktiveras när en magnet hålls mot en markerad punkt. Alternativt tre
   knackningar som IMU:n känner igen. Inget hål i lådan.
3. **Lokföraren bekräftar hela tåget** (tillval): godkänns bara för vagnar vars
   mätvärden också ser tomma ut.

### Identitet och placering
- **V1:** montören registrerar i appen: skannar enhetens QR-kod, anger
  UIC-vagnsnumret och trycker på hörnet på en bild av vagnen. Kalibreringen
  lagras på servern, knuten till vagnsnummer och hörn.
- **V2:** en NFC-tagg vid varje monteringspunkt. Hörnenheten läser den vid
  montering och vet då vagn och hörn.
- **V3:** en BLE-sändare mitt på vagnen (vagnsnummer), för tågsammansättning.
- **Självplacering (kontroll):**
  - vänster eller höger: sidokraften i kurvor får motsatt tecken, eftersom
    enheterna är vända utåt
  - fram eller bak: samma skarvar och växlar syns med en fördröjning av
    boggiavståndet delat med hastigheten
  - stämmer placeringen inte med registreringen: flaggan `placement_mismatch`

### Meddelande ut (från gatewayen till servern och appen)

```json
{
  "wagon": "318045671234",
  "ts": 1790000000,
  "pos": {"lat": 59.3293, "lon": 18.0686},
  "state": "SETTLED",
  "total_kg": 64850,
  "corners_kg": {"VL": 16300, "VR": 16100, "HL": 16250, "HR": 16200},
  "imbalance": {"long_pct": 0.2, "lat_pct": 0.3, "diag_pct": 0.1},
  "track_cant_deg": 0.4,
  "temp_c": 12.5,
  "battery_v": {"GW": 3.95, "VL": 3.61, "VR": 3.60, "HL": 3.62, "HR": 3.61},
  "flags": []
}
```

Flaggor: `sensor_fault`, `overload`, `imbalance_long`, `imbalance_lat`,
`imbalance_diag`, `low_battery`, `not_calibrated`, `mount_check`,
`placement_mismatch`, `corner_missing`.

### Strömbudget
- Hörnenhet i produkt: genomsnitt ≤ 0,1–0,5 mW, så att en Li-SOCl₂-cell räcker i flera år.
- Gateway: täcks av solcell och batteri. Sänd efter SETTLED och en gång om dygnet som livstecken.
- Mät och dokumentera i `docs/strom.md`.

## Pilot

- 1–5 vagnar, helst med en operatör som också gör manuell vagnupptagning och
  kan väga på spårvåg.
- **Pilotavtalet** ska säga att data samlas in för att utveckla systemet
  (position, rörelser, vikt). Vi behöver också deras manuella vagnupptagningar
  att jämföra med. GDPR gäller för loggning av vem som bekräftar i appen.
- **Tät loggning:** varje minut när vagnen står still och IMU-data i hög takt
  när den rör sig, allt till SD-kortet.
- **Byte eller laddning varje månad:** läs ut SD-kortet, ladda med Qi (laddaren
  fästs med magnet över natten) eller byt enhet, och uppdatera firmware.
- För en dagbok över händelser (lastning, lossning, vägning, tågsammansättning) i
  `docs/pilot.md`.

## Framtid: automatisk vagnupptagning (skuggläge i piloten)

Körs i bakgrunden och jämförs med den manuella upptagningen. Ingen kund ska
förlita sig på den förrän den är verifierad och patenten är kontrollerade.

- **Vilka vagnar som hör till samma tåg:** vagnar som rör sig likadant samtidigt (IMU och GPS).
- **Ordning:** startstöten och inbromsningsstöten fortplantar sig vagn för vagn
  (tidsstämplar synkade med GPS PPS), stöttat av GPS (RTK på bangårdar) och
  BLE-signalstyrka mellan grannvagnar.
- **Vilket håll vagnen är vänd:** GPS-kursen jämförd med gatewayens riktning, eller vilken boggi som rör sig först.
- **Lastväxelns läge:** jämför uppmätt last med lastväxelns läge. Kräver en givare på lastväxeln. Det är en stor säkerhetsvinst.
- **Kräver fortfarande en människa:** bromsprov, handbroms, lastsäkring och farligt gods (från fraktsedeln).

## Mappstruktur (förslag)

```
firmware/
  common/        # protokoll (BLE-paket, ESP-NOW), kalibrering, fusion, JSON
  corner/        # hörnenhet
  gateway/       # gateway: BLE-skanning, LTE-M, GPS, beräkningar
  test/          # enhetstester: fusion, kalibrering, snedlastning, nollställning
server/          # mottagning (MQTT/HTTPS), lagring, beräkningar, abonnemang
app/             # webbapp (Web Bluetooth): montering, visning, bekräftelse av tom vagn
docs/
  beslut.md      # designbeslut med datum (även patentskäl)
  strom.md
  pilot.md
hardware/        # kopplingsschema, BOM, lådor, målplåt, monteringsmall
```

## Etapper

1. **Bänkprototyp:** en hörnenhet med ultraljud och laser mot en rörlig plåt.
   Verifiera upplösning, fusion och temperaturkompensering.
2. **Hela vagnen på bänken:** 4 hörn och en gateway. BLE advertising, väckning
   via IMU, GPS-tid, LTE-M till servern, appen visar vikten.
3. **Montering och kalibrering:** registrering via QR-kod i appen,
   kalibreringskurvor, automatisk nollställning, bekräftelse av tom vagn.
4. **Pilot:** 1–5 vagnar under minst en vinter. Jämför med spårvåg. Skuggläge
   för vagnupptagning.
5. **Produkt:** nRF52840 och Li-SOCl₂ i hörnen, eget kretskort, NFC-taggar och
   abonnemangsbackend.

## Öppna frågor

- [ ] Hämta de **beviljade** kraven för SE2350203-2 ("Patentkrav" i akten, den
      senaste versionen) och bekräfta att krav 1 fortfarande kräver radiovågor
      mot räls eller mark.
- [ ] Kontrollera RMD:s nyare ansökningar från 2024–2025 (patentet för vagnvikt
      som beviljades 2026) och deras patent för ATD och tågsammansättning.
- [ ] Läs kraven i SE2250761-0 innan någon analys av hjul eller vibrationer byggs.
- [ ] Mät den faktiska fjäderrörelsen på Y25 mellan tom och full vagn.
- [ ] Testa BLE-räckvidden från axelboxen till vagnens sida på en riktig vagn.
- [ ] Testa LTE- och GPS-täckningen med gatewayen monterad på vagnens sida.
- [ ] Välj lasergivare med tillräcklig upplösning (< 1 mm efter medelvärdesbildning).
- [ ] Stäm av montering utan ingrepp med vagnägarens underhållsansvariga (ECM).
- [ ] Ett patentombud gör en frihetsanalys innan försäljning.
