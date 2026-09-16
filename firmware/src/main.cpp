#include <Arduino.h>
#include <string.h>
#include "HX711.h"
#include "UHF_RFID.h"
#include <config.h>

// Message format
//   {"v":1,"t":12345,"raw":8342133,"weight_g":601.2,"metal":false,
//    "tags":[{"epc":"E280..","rssi":210}]}
//   - raw       : summed HX711 counts across all cells (null if any ADC isn't ready)
//   - weight_g  : grams, only if kCalibrationFactor is set, else null
//   - metal     : true if the ferrous-metal detector (A0) is above threshold
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

void emitReport(bool weightAllowed = true) {
    long rawSum    = 0;
    long offsetSum = 0;
    bool ready     = weightAllowed;
    if (weightAllowed) {
        for (uint8_t i = 0; i < kNumLoadCells; i++) {
            if (!gCells[i].wait_ready_timeout(kAdcReadyMs)) {
                ready = false;
                break;
            }
            rawSum    += gCells[i].read_average(kWeightSamples) * kLoadcellPolarities[i];
            offsetSum += gCells[i].get_offset() * kLoadcellPolarities[i];
        }
    }

    HOST_SERIAL.print("{\"v\":1,\"t\":");
    HOST_SERIAL.print(millis());

    HOST_SERIAL.print(",\"raw\":");
    if (ready) HOST_SERIAL.print(rawSum);
    else       HOST_SERIAL.print("null");

    HOST_SERIAL.print(",\"weight_g\":");
    if (ready && kCalibrationFactor > 0.0f) {
        HOST_SERIAL.print((rawSum - offsetSum) / kCalibrationFactor, 1);
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
    emitReport(scaleSettled);
    gTagCount = 0;

    // ── Pace: enforce minimum cycle time ──
    const unsigned long elapsed = millis() - cycleStart;
    if (elapsed < kMinCyclePeriodMs) {
        delay(kMinCyclePeriodMs - elapsed);
    }
}
