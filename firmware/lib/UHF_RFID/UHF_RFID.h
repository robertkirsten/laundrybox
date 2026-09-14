#pragma once

#include <Arduino.h>

class UHF_RFID {
public:
    // Longest EPC we bother to store (96-bit EPC = 12 bytes is by far the most
    // common; 32 leaves headroom for longer memory banks).
    static constexpr uint8_t kMaxEpc = 32;

    struct Tag {
        uint8_t  rssi = 0;         // raw signal strength byte (larger = stronger)
        uint8_t  pc[2] = {0, 0};   // Protocol Control word
        uint8_t  epc[kMaxEpc];     // Electronic Product Code (the tag's ID)
        uint8_t  epcLen = 0;       // number of valid bytes in epc[]
        uint16_t crc = 0;          // tag CRC as reported by the reader

        // Format the EPC as an uppercase hex string (e.g. "E280110520..").
        // `out` must hold at least epcLen*2 + 1 bytes.
        void epcToHex(char *out, size_t outSize) const;
    };

    // Bind the driver to an already-selected hardware serial port.
    // On a Teensy 4.1 use Serial1 (RX1 = pin 0, TX1 = pin 1) by default.
    void begin(HardwareSerial &serial, unsigned long baud = 115200);

    // Perform a single inventory round. Returns true and fills `tag` if a tag
    // was read; false on timeout or "no tag found".
    bool pollOnce(Tag &tag, uint32_t timeoutMs = 200);

    // Ask the module for its firmware/hardware info string. Handy as a quick
    // "is the wiring correct?" check. Returns false on timeout.
    bool getVersion(String &out, uint32_t timeoutMs = 200);

    // Set transmit power in dBm*100 (e.g. 2000 = 20.00 dBm). Range is roughly
    // 15.00-26.00 dBm depending on the module/antenna. Returns false on timeout.
    bool setTxPower(uint16_t dBm_x100, uint32_t timeoutMs = 200);

private:
    static constexpr uint8_t kHeader = 0xBB;
    static constexpr uint8_t kEnd    = 0x7E;

    HardwareSerial *_serial = nullptr;

    void sendFrame(uint8_t type, uint8_t cmd, const uint8_t *data, uint16_t len);

    // Read one complete frame into `buf`. Uses the length field so payload bytes
    // that happen to equal 0x7E/0xBB don't confuse it. Returns frame length in
    // bytes, or -1 on timeout / malformed frame.
    int readFrame(uint8_t *buf, size_t bufSize, uint32_t timeoutMs);
};
