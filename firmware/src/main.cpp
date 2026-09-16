#include <Arduino.h>
#include <string.h>
#include "HX711.h"
#include "UHF_RFID.h"
#include <config.h>

// Message format
//   {"v":1,"t":12345,"raw":8342133,"weight_g":601.2,"metal":false,
//    "auto_tare":false,"tare_residual_g":null,
//    "tags":[{"epc":"E280..","rssi":210}]}
//   - raw       : summed HX711 counts across all cells (null if any ADC isn't ready)
//   - weight_g  : grams, only if kCalibrationFactor is set, else null
//   - metal     : true if the ferrous-metal detector (A0) is above threshold
//   - auto_tare : true when this report applied a guarded empty-box re-zero
//   - tare_residual_g: stable residual removed by that re-zero, otherwise null
//   - tags      : every distinct tag seen since the last message ([] if none)
// + boot line on reset: {"v":1,"event":"boot","hx711_sps":10.0}

static_assert(sizeof(kLoadcellDoutPins) / sizeof(kLoadcellDoutPins[0]) == kNumLoadCells,
              "kLoadcellDoutPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellSckPins) / sizeof(kLoadcellSckPins[0]) == kNumLoadCells,
              "kLoadcellSckPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellPolarities) / sizeof(kLoadcellPolarities[0]) == kNumLoadCells,
              "kLoadcellPolarities must have exactly kNumLoadCells entries");

// Metal-detector threshold in ADC counts, derived from the volts config.
constexpr int kMetalThresholdCounts =
    static_cast<int>(kMetalThresholdVolts / kMetalVref * ((1 << kMetalAdcBits) - 1));

// Runtime state — defined here, in one translation unit. Only constants live in
// config.h; putting these globals in a header would multiply-define them if a
// second .cpp ever included it.

HX711    gCells[kNumLoadCells];
UHF_RFID reader;

struct TagObs {
    char    epc[UHF_RFID::kMaxEpc * 2 + 1];
    uint8_t rssi;
};
TagObs        gTags[kMaxTagsPerReport];
uint8_t       gTagCount = 0;

struct ScaleReading {
    bool  ready = false;
    long  rawSum = 0;
    long  offsetSum = 0;
    long  cellRaw[kNumLoadCells] = {};
    float weightG = 0.0f;
};

bool    gLoadedSinceAutoTare = false;
uint8_t gAutoTareCandidateCount = 0;
float   gAutoTareCandidateMinG = 0.0f;
float   gAutoTareCandidateMaxG = 0.0f;
float   gAutoTareCandidateWeightSumG = 0.0f;
int64_t gAutoTareCandidateRawSums[kNumLoadCells] = {};

bool setRfidIdleMode(bool idle) {
    for (uint8_t attempt = 0; attempt < kRfidCommandRetries; attempt++) {
        if (reader.setIdleMode(idle, kRfidCommandTimeoutMs)) {
            return true;
        }
        delay(5);
    }
    return false;
}

bool setRfidTxPower() {
    for (uint8_t attempt = 0; attempt < kRfidCommandRetries; attempt++) {
        if (reader.setTxPower(kRfidTxPower, kRfidCommandTimeoutMs)) {
            return true;
        }
        delay(5);
    }
    return false;
}


void recordTag(const UHF_RFID::Tag &tag) {
    char epc[UHF_RFID::kMaxEpc * 2 + 1] = {0};
    tag.epcToHex(epc, sizeof(epc));

    for (uint8_t i = 0; i < gTagCount; i++) {
        if (strcmp(gTags[i].epc, epc) == 0) {
            gTags[i].rssi = tag.rssi;
            return;
        }
    }
    if (gTagCount < kMaxTagsPerReport) {
        memcpy(gTags[gTagCount].epc, epc, sizeof(gTags[gTagCount].epc));
        gTags[gTagCount].rssi = tag.rssi;
        gTagCount++;
    }
}

ScaleReading measureScale(bool weightAllowed) {
    ScaleReading reading;
    reading.ready = weightAllowed;
    if (reading.ready) {
        for (uint8_t i = 0; i < kNumLoadCells; i++) {
            if (!gCells[i].wait_ready_timeout(kAdcReadyMs)) {
                reading.ready = false;
                break;
            }
            reading.cellRaw[i] = gCells[i].read_average(kWeightSamples);
            reading.rawSum += reading.cellRaw[i] * kLoadcellPolarities[i];
            reading.offsetSum += gCells[i].get_offset() * kLoadcellPolarities[i];
        }
    }

    if (reading.ready && kCalibrationFactor > 0.0f) {
        reading.weightG = (reading.rawSum - reading.offsetSum) / kCalibrationFactor;
    }
    return reading;
}

void resetAutoTareCandidate() {
    gAutoTareCandidateCount = 0;
    gAutoTareCandidateMinG = 0.0f;
    gAutoTareCandidateMaxG = 0.0f;
    gAutoTareCandidateWeightSumG = 0.0f;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        gAutoTareCandidateRawSums[i] = 0;
    }
}

void startAutoTareCandidate(const ScaleReading &reading) {
    resetAutoTareCandidate();
    gAutoTareCandidateCount = 1;
    gAutoTareCandidateMinG = reading.weightG;
    gAutoTareCandidateMaxG = reading.weightG;
    gAutoTareCandidateWeightSumG = reading.weightG;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        gAutoTareCandidateRawSums[i] = reading.cellRaw[i];
    }
}

bool maybeAutoTare(ScaleReading &reading, float &residualG) {
    if (!reading.ready || kCalibrationFactor <= 0.0f) {
        resetAutoTareCandidate();
        return false;
    }

    if (reading.weightG >= kAutoTareLoadedMinG) {
        gLoadedSinceAutoTare = true;
        resetAutoTareCandidate();
        return false;
    }

    if (!gLoadedSinceAutoTare || fabsf(reading.weightG) >= kAutoTareMaxResidualG) {
        resetAutoTareCandidate();
        return false;
    }

    if (gAutoTareCandidateCount == 0) {
        startAutoTareCandidate(reading);
        return false;
    }

    const float candidateMin = min(gAutoTareCandidateMinG, reading.weightG);
    const float candidateMax = max(gAutoTareCandidateMaxG, reading.weightG);
    if (candidateMax - candidateMin > kAutoTareStabilityToleranceG) {
        startAutoTareCandidate(reading);
        return false;
    }

    gAutoTareCandidateMinG = candidateMin;
    gAutoTareCandidateMaxG = candidateMax;
    gAutoTareCandidateWeightSumG += reading.weightG;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        gAutoTareCandidateRawSums[i] += reading.cellRaw[i];
    }
    gAutoTareCandidateCount++;
    if (gAutoTareCandidateCount < kAutoTareStableSamples) {
        return false;
    }

    residualG = gAutoTareCandidateWeightSumG / gAutoTareCandidateCount;
    reading.offsetSum = 0;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        const long newOffset =
            static_cast<long>(gAutoTareCandidateRawSums[i] / gAutoTareCandidateCount);
        gCells[i].set_offset(newOffset);
        reading.offsetSum += newOffset * kLoadcellPolarities[i];
    }
    reading.weightG = (reading.rawSum - reading.offsetSum) / kCalibrationFactor;

    gLoadedSinceAutoTare = false;
    resetAutoTareCandidate();
    return true;
}

void emitReport(const ScaleReading &reading, bool autoTared, float tareResidualG) {
    HOST_SERIAL.print("{\"v\":1,\"t\":");
    HOST_SERIAL.print(millis());

    HOST_SERIAL.print(",\"raw\":");
    if (reading.ready) HOST_SERIAL.print(reading.rawSum);
    else       HOST_SERIAL.print("null");

    HOST_SERIAL.print(",\"weight_g\":");
    if (reading.ready && kCalibrationFactor > 0.0f) {
        HOST_SERIAL.print(reading.weightG, 1);
    } else {
        HOST_SERIAL.print("null");
    }

    // average a few A0 reads and threshold
    long metalAcc = 0;
    for (uint8_t i = 0; i < kMetalSamples; i++) {
        metalAcc += analogRead(kMetalPin);
    }
    const bool metal = (metalAcc / kMetalSamples) > kMetalThresholdCounts;
    HOST_SERIAL.print(",\"metal\":");
    HOST_SERIAL.print(metal ? "true" : "false");

    HOST_SERIAL.print(",\"auto_tare\":");
    HOST_SERIAL.print(autoTared ? "true" : "false");
    HOST_SERIAL.print(",\"tare_residual_g\":");
    if (autoTared) HOST_SERIAL.print(tareResidualG, 1);
    else           HOST_SERIAL.print("null");

    HOST_SERIAL.print(",\"tags\":[");
    for (uint8_t i = 0; i < gTagCount; i++) {
        if (i > 0) HOST_SERIAL.print(',');
        HOST_SERIAL.print("{\"epc\":\"");
        HOST_SERIAL.print(gTags[i].epc);
        HOST_SERIAL.print("\",\"rssi\":");
        HOST_SERIAL.print(gTags[i].rssi);
        HOST_SERIAL.print('}');
    }
    HOST_SERIAL.println("]}");
}

void setup() {
    HOST_SERIAL.begin(kHostBaud);
    const unsigned long start = millis();
    while (!HOST_SERIAL && millis() - start < 3000) {}

    reader.begin(RFID_SERIAL, kRfidBaud);
    delay(kRfidStartupDelayMs);

    // Some U107 firmware revisions do not acknowledge the transmit-power
    // command even though inventory remains operational. This setting was
    // historically best-effort, so keep it non-fatal and preserve the value
    // already stored by the module when no acknowledgement arrives.
    if (!setRfidTxPower()) {
        HOST_SERIAL.println(
            "RFID warning: transmit-power command was not acknowledged; using stored power");
    }

    // IDLE acknowledgement is mandatory: do not tare or sample the scale until
    // the reader has confirmed that its analog and RF supplies are off.
    while (!setRfidIdleMode(true)) {
        HOST_SERIAL.println(R"({"v":1,"event":"rfid_config_error"})");
        HOST_SERIAL.println("RFID diagnostic: IDLE command failed");
        delay(1000);
    }

    analogReadResolution(kMetalAdcBits);   // ferrous-metal detector on A0

    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        gCells[i].begin(kLoadcellDoutPins[i], kLoadcellSckPins[i]);
    }

    if (kCalibrationFactor > 0.0f) {
        for (uint8_t i = 0; i < kNumLoadCells; i++) {
            if (gCells[i].wait_ready_timeout(1000)) {
                gCells[i].tare(kTareSamples);
            }
        }
    }

    // Measure actual HX711 sample rate so the operator can verify 10/80 SPS.
    float measuredSps = 0.0f;
    if (gCells[0].wait_ready_timeout(1000)) {
        gCells[0].read();                        // trigger next conversion
        const unsigned long t0 = micros();
        gCells[0].wait_ready_timeout(1000);       // wait for it to finish
        const unsigned long dt = micros() - t0;
        if (dt > 0) measuredSps = 1000000.0f / dt;
    }

    HOST_SERIAL.print(R"({"v":1,"event":"boot","hx711_sps":)");
    HOST_SERIAL.print(measuredSps, 1);
    HOST_SERIAL.println("}");
}

void loop() {
    const unsigned long cycleStart = millis();

    // ── Phase 1: wake the RF circuitry and scan ──
    const bool readerAwake = setRfidIdleMode(false);
    if (readerAwake) {
        delay(kRfidWakeDelayMs);

        const unsigned long rfidStart = millis();
        while (millis() - rfidStart < kRfidWindowMs) {
            UHF_RFID::Tag tag;
            if (reader.pollOnce(tag, kRfidPollTimeoutMs)) {
                recordTag(tag);
            }
        }
    }

    // ── Phase 2: explicitly switch off analog/RF power ──
    // A weight is valid only after the U107 acknowledges IDLE mode. Merely
    // stopping inventory commands does not guarantee that the RF circuitry is
    // powered down.
    const bool readerIdle = setRfidIdleMode(true);

    // ── Phase 3: settle the HX711 digital filter ──
    bool scaleSettled = readerIdle;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
        for (uint8_t s = 0; s < kSettleConversions; s++) {
            if (!scaleSettled) break;
            if (!gCells[i].wait_ready_timeout(kAdcReadyMs)) {
                scaleSettled = false;
                break;
            }
            gCells[i].read();   // discard
        }
    }

    // ── Phase 4: measure while the U107 remains in IDLE ──
    // If either the RF shutdown or HX711 settling failed, emit null weight
    // values rather than presenting contaminated data as a real measurement.
    ScaleReading reading = measureScale(scaleSettled);
    float tareResidualG = 0.0f;
    const bool autoTared = maybeAutoTare(reading, tareResidualG);
    emitReport(reading, autoTared, tareResidualG);
    gTagCount = 0;

    // ── Pace: enforce minimum cycle time ──
    const unsigned long elapsed = millis() - cycleStart;
    if (elapsed < kMinCyclePeriodMs) {
        delay(kMinCyclePeriodMs - elapsed);
    }
}
