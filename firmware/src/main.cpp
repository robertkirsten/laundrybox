#include <Arduino.h>
#include "UHF_RFID.h"

UHF_RFID reader;

#define RFID_SERIAL Serial1

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) {}

    reader.begin(RFID_SERIAL, 115200);

    Serial.println();
    Serial.println(F("LaundryBox UHF RFID reader"));

    reader.setTxPower(2000);

    Serial.println(F("Scanning for tags..."));
}

void loop() {
    UHF_RFID::Tag tag;

    if (reader.pollOnce(tag)) {
        char epc[UHF_RFID::kMaxEpc * 2 + 1];
        tag.epcToHex(epc, sizeof(epc));

        Serial.print(F("EPC: "));
        Serial.print(epc);
        Serial.print(F("  RSSI: "));
        Serial.println(tag.rssi);
    }

    delay(200);
}
