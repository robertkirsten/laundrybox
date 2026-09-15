#include <Arduino.h>
#include <string.h>
#include "HX711.h"
#include "UHF_RFID.h"
#include <config.h>

// Message format
//   {"v":1,"t":12345,"raw":8342133,"weight_g":601.2,
//    "tags":[{"epc":"E280..","rssi":210}]}
//   - raw       : averaged HX711 counts (null if the ADC isn't ready)
//   - weight_g  : grams, only if kCalibrationFactor is set, else null
//   - tags      : every distinct tag seen since the last message ([] if none)
// + boot line on reset: {"v":1,"event":"boot"}

// Runtime state — defined here, in one translation unit. Only constants live in
// config.h; putting these globals in a header would multiply-define them if a
// second .cpp ever included it.
HX711    scale;
UHF_RFID reader;

struct TagObs {
    char    epc[UHF_RFID::kMaxEpc * 2 + 1];
    uint8_t rssi;
};
TagObs        gTags[kMaxTagsPerReport];
uint8_t       gTagCount = 0;
unsigned long gLastReportMs = 0;

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

void emitReport() {
    const bool ready = scale.wait_ready_timeout(kAdcReadyMs);
    const long raw   = ready ? scale.read_average(kWeightSamples) : 0;

    HOST_SERIAL.print("{\"v\":1,\"t\":");
    HOST_SERIAL.print(millis());

    HOST_SERIAL.print(",\"raw\":");
    if (ready) HOST_SERIAL.print(raw);
    else       HOST_SERIAL.print("null");

    HOST_SERIAL.print(",\"weight_g\":");
    if (ready && kCalibrationFactor > 0.0f) {
        HOST_SERIAL.print((raw - scale.get_offset()) / scale.get_scale(), 1);
    } else {
        HOST_SERIAL.print("null");
    }

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
    reader.setTxPower(kRfidTxPower);

    scale.begin(kLoadcellDoutPin, kLoadcellSckPin);
    if (kCalibrationFactor > 0.0f && scale.wait_ready_timeout(1000)) {
        scale.set_scale(kCalibrationFactor);
        scale.tare(kTareSamples);
    }

    HOST_SERIAL.println(R"({"v":1,"event":"boot"})");
}

void loop() {
    UHF_RFID::Tag tag;
    if (reader.pollOnce(tag)) {
        recordTag(tag);
    }

    const unsigned long now = millis();
    if (now - gLastReportMs >= kReportPeriodMs) {
        gLastReportMs = now;
        emitReport();
        gTagCount = 0;
    }
}
