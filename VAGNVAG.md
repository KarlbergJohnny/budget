# Vagnvåg – lastviktsystem för godsvagnar

Projektbeskrivning och instruktioner för utveckling. Läs hela filen innan du börjar koda.

## Mål

Ett billigt system som eftermonteras på godsvagnar och mäter **vagnens vikt och
snedlastning under lastning**. Det monteras med magneter, utan borrning eller
svetsning. Kunden betalar ett abonnemang per vagn och månad, och vi äger
hårdvaran. Byts en box ut, byts hela boxen.

Första versionen mäter **bara när vagnen står still under lastning**. Övervakning
under färd är ett senare tillval.

## Patentgränser, som aldrig får brytas

Railway Metrics and Dynamics (RMD) har patentet SE2350203-2 (US 12522265),
"System and method for determining a weight status of a railway vehicle".
Deras krav 1 kräver **radiovågor (radar)** som reflekteras mot
**räls eller mark**, **minst fyra detektorer** och en beräkningsenhet som
räknar fram vikten.

Därför gäller:

- **Använd ALDRIG radar eller andra radiovågor för att mäta avstånd eller vikt.**
  Radiovågor är bara tillåtna för kommunikation (BLE, ESP-NOW, wifi, LTE).
- Använd **ultraljud** och **laser** (ToF eller triangulering) för att mäta avstånd.
- Mät helst **internt i fjädringen**, alltså boggiram ↔ axelbox eller
  lastyta ↔ axelbox, inte mot räls eller mark.
- RMD har också SE2250761-0 (radar för att bedöma hjulets status). Bygg ingen
  analys av hjul eller vibrationer utan att först ha kontrollerat det patentet.
- Dokumentera designbeslut med datum i `docs/beslut.md`.

Vi har ännu inte kontrollerat de slutliga, beviljade kraven för SE2350203-2.
Det är en öppen punkt, se nedan.

## Hårdvara

### Per vagn

| Del | Antal | Kommentar |
|---|---|---|
| ESP32-S3 | 2 | En per boggi. Nod A är huvudenhet, nod B är slav. |
| Ultraljudsgivare, IP67, 1 mm upplösning (t.ex. MaxBotix) | 4 | En per boggisida |
| Lasergivare för avstånd (VL53L1X för prototyp, industriell triangulering senare) | 4 | Bredvid respektive ultraljudsgivare |
| IMU (BNO085 eller MPU6050) | 1 | På nod A: väckning, lutning i sidled och längsled |
| Temperaturgivare (DS18B20) | 2 | En per nod, för att kompensera ultraljudet |
| 1-Wire EEPROM (DS2431 eller liknande) | 2 | I kabelstammen som sitter kvar på vagnen: vagnsnummer och kalibrering |
| MOSFET-brytare för ström till givarna | 2+ | Givarna får bara ström när de mäter |
| Solcell + laddkrets med temperaturspärr | 2 | Ingen laddning under 0 °C, eller använd LTO-celler |
| Batteri (2× 18650, eller LTO) | 2 | Dimensioneras för en vinter utan sol |
| M12 A-kodade kontakter | – | Mellan givare och box |
| Gummiklädda magneter (värmeklass SH), säkringsvajer | – | Minst 5–10 cm från Hall- och magnetgivare |

### Montering
- Givarna mäter lodrätt avstånd mellan en punkt på den fjädrade delen
  (boggiram eller lastyta) och en punkt på den ofjädrade delen (axelboxens
  ovansida, inte själva axeln).
- Ultraljudsgivaren och lasergivaren mäter mot samma plana målyta, en liten
  stålplåt med magnetfäste på axelboxen.
- Använd en monteringsmall med mått från fasta referenspunkter på Y25-boggin,
  så att geometrin blir densamma på alla vagnar av samma typ.

## Arkitektur

```
[Ultraljud+laser VL] ─┐                      ┌─ [Ultraljud+laser VR]
                      ├─ Nod A (boggi 1) ────┤   IMU, temp, EEPROM
                      │        ▲             │
                      │     ESP-NOW          │
                      │        ▼             │
[Ultraljud+laser HL] ─┴─ Nod B (boggi 2) ────┴─ [Ultraljud+laser HR]
                               temp, EEPROM

Nod A ── BLE ──> mobil/webbapp   (senare: LTE-M via SIM7080G)
```

- Nod B mäter på kommando från nod A och skickar resultatet via ESP-NOW.
- Nod A slår ihop värdena, räknar ut vikten och publicerar via BLE.

## Firmware

Använd **PlatformIO** med ramverket Arduino, eller ESP-IDF om det behövs.
Skriv i C++.

### Tillstånd
1. **DEEP_SLEEP**: allt avstängt. IMU:ns avbrott för rörelse eller stöt är
   konfigurerat som väckningskälla. Sätt också en timer som väcker enheten
   var 10:e minut.
2. **IDLE_CHECK**: vakna, gör en snabb mätning, somna igen om ingenting har
   ändrats.
3. **LOADING**: startar när IMU:n känner stötar i följd eller vikten ändras.
   Mät var 10:e–30:e sekund.
4. **SETTLED**: vikten har varit stabil i X minuter (konfigurerbart). Spara
   slutvärdet, publicera det och gå till DEEP_SLEEP.

Om vagnen rör sig (IMU:n ser ihållande acceleration eller rotation), gör inga
nya mätningar av vikten. Använd det senaste värdet från SETTLED.

### Mätning per givarpunkt
1. Slå på givarna via MOSFET och vänta tills de är klara att mäta.
2. Ta **N = 50–100** mätningar från vardera givaren.
3. Ta bort extremvärden: använd medianen, eller mått baserade på IQR.
4. Kompensera ultraljudet för temperaturen:
   `c = 331.3 + 0.606 * T` (m/s, T i °C).
   `avstånd = tid * c / 2`.
5. Räkna ut medelvärde μ och standardavvikelse σ för varje givare.
6. Slå ihop givarna med **inversvariansviktning**:
   `w_i = 1/σ_i²`, `d = Σ(w_i·d_i) / Σw_i`.
7. Kontrollera att de stämmer överens: om `|d_ultraljud − d_laser| > k·sqrt(σ_u² + σ_l²)`
   (börja med k = 3), räkna den givaren som mest avviker från den senaste
   giltiga mätningen som felaktig. Använd då bara den andra givaren och sätt
   en flagga (`sensor_fault`).
8. Stäng av strömmen till givarna.

### Från avstånd till vikt
- Varje hörn har en egen kalibreringskurva som omvandlar fjädringens
  hoptryckning (mm) till last (kN). Kurvan är styckvis linjär med minst
  3–4 punkter, eftersom förhållandet inte är linjärt (Y25 har två fjäderstadier).
- **Nollpunkt:** tarvikten, alltså den tomvikt som står målad på vagnen.
  Mät med tom vagn och spara det som hoptryckning = 0.
- Hörnlast `F_i` → totalvikt `Σ F_i / g`.
- Snedlastning:
  - fram–bak: `(F_VL+F_VR) − (F_HL+F_HR)`
  - vänster–höger: `(F_VL+F_HL) − (F_VR+F_HR)`, korrigerat för spårets
    lutning i sidled från IMU:n
  - diagonalt: `(F_VL+F_HR) − (F_VR+F_HL)`
- Friktionen i Y25-boggin ger hysteres. Använd värdet efter att vikten har
  stabiliserats, och spara hela kurvan från lastningen för analys.

### Kalibrering och identitet
- EEPROM:et i kabelstammen innehåller: UIC-vagnsnummer (12 siffror), vagnstyp,
  tarvikt, kalibreringskurvor per hörn och datum för kalibreringen.
- En ny box läser EEPROM:et vid start och fungerar direkt.
- Kalibreringen går att skriva via BLE från appen, i ett serviceläge med PIN-kod.

### Gränssnitt ut (BLE)
Publicera JSON i en GATT-characteristic, eller via en enkel BLE UART-tjänst:

```json
{
  "wagon": "318045671234",
  "ts": 1790000000,
  "state": "SETTLED",
  "total_kg": 64850,
  "corners_kg": {"VL": 16300, "VR": 16100, "HL": 16250, "HR": 16200},
  "imbalance": {"long_pct": 0.2, "lat_pct": 0.3, "diag_pct": 0.1},
  "track_cant_deg": 0.4,
  "temp_c": 12.5,
  "battery_v": 3.92,
  "flags": []
}
```

Flaggor: `sensor_fault`, `overload`, `imbalance_long`, `imbalance_lat`,
`low_battery`, `not_calibrated`.

### Strömbudget
- Genomsnittet ska vara **≤ 1 mW per nod** när vagnen står still och ingen
  lastning pågår.
- Mät förbrukningen och dokumentera den i `docs/strom.md`.

## Mappstruktur (förslag)

```
firmware/
  common/        # delade headers: meddelanden (ESP-NOW), kalibrering, JSON
  node_a/        # huvudenhet: IMU, BLE, ihopslagning av data
  node_b/        # slav
  test/          # enhetstester: fusion, kalibrering, snedlastning
app/             # enkel webbapp (Web Bluetooth) för att läsa av och kalibrera
docs/
  beslut.md      # designbeslut med datum (även patentskäl)
  strom.md
  pilot.md
hardware/        # kopplingsschema, BOM, skisser på fästen
```

## Etapper

1. **Bänkprototyp:** en nod, en ultraljudsgivare och en lasergivare mot en
   rörlig plåt. Verifiera upplösning, fusion och temperaturkompensering.
2. **Två noder:** ESP-NOW, sömn och väckning via IMU, BLE-utdata till webbappen.
3. **Kalibrering:** EEPROM i kabelstammen, kalibreringskurvor, serviceläge.
4. **Pilot:** 1–5 vagnar. Jämför med en spårvåg under minst en vinter.
5. **Produkt:** välj den givartyp som fungerade bäst, lägg till LTE-M och ett
   backend för abonnemang.

## Öppna frågor

- [ ] Hämta de **beviljade** kraven för SE2350203-2 från PRV och bekräfta att
      krav 1 fortfarande kräver radiovågor mot räls eller mark.
- [ ] Kontrollera om RMD har nyare ansökningar från 2024–2025 (patentet för
      vagnvikt som beviljades 2026).
- [ ] Mät den faktiska fjäderrörelsen på Y25 mellan tom och full vagn på
      pilotvagnen.
- [ ] Välj lasergivare med tillräcklig upplösning (< 1 mm efter medelvärdesbildning).
- [ ] Stäm av montering utan ingrepp med vagnägarens underhållsansvariga (ECM).
