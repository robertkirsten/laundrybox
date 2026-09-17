#include "UHF_RFID.h"

void UHF_RFID::Tag::epcToHex(char *out, size_t outSize) const {
    static const char *hex = "0123456789ABCDEF";
    size_t o = 0;
    for (uint8_t i = 0; i < epcLen && o + 2 < outSize; i++) {
        out[o++] = hex[(epc[i] >> 4) & 0x0F];
        out[o++] = hex[epc[i] & 0x0F];
    }
    if (outSize > 0) out[o < outSize ? o : outSize - 1] = '\0';
}

void UHF_RFID::begin(HardwareSerial &serial, unsigned long baud) {
    _serial = &serial;
    _serial->begin(baud);
}

void UHF_RFID::sendFrame(uint8_t type, uint8_t cmd, const uint8_t *data, uint16_t len) {
    if (!_serial) return;

    uint8_t frame[64];
    size_t i = 0;
    frame[i++] = kHeader;
    frame[i++] = type;
    frame[i++] = cmd;
    frame[i++] = (len >> 8) & 0xFF;   // length MSB
    frame[i++] = len & 0xFF;          // length LSB
    for (uint16_t k = 0; k < len && i < sizeof(frame) - 2; k++) {
        frame[i++] = data[k];
    }

    // Checksum: sum of Type .. last Data byte (indices 1 .. i-1).
    uint32_t sum = 0;
    for (size_t k = 1; k < i; k++) sum += frame[k];
    frame[i++] = sum & 0xFF;
    frame[i++] = kEnd;

    _serial->write(frame, i);
    _serial->flush();
}

int UHF_RFID::readFrame(uint8_t *buf, size_t bufSize, uint32_t timeoutMs) {
    if (!_serial) return -1;
    const uint32_t start = millis();

    // Blocking read of a single byte, honouring the overall timeout.
    auto readByte = [&](uint8_t &out) -> bool {
        while ((uint32_t)(millis() - start) < timeoutMs) {
            if (_serial->available()) { out = (uint8_t)_serial->read(); return true; }
        }
        return false;
    };

    uint8_t b;
    size_t idx = 0;

    // 1. Sync to the header byte.
    do {
        if (!readByte(b)) return -1;
    } while (b != kHeader);
    buf[idx++] = b;

    // 2. Read Type, Cmd, Len MSB, Len LSB.
    for (int k = 0; k < 4; k++) {
        if (!readByte(b)) return -1;
        if (idx < bufSize) buf[idx++] = b;
    }
    const uint16_t dataLen = ((uint16_t)buf[3] << 8) | buf[4];

    // 3. Read Data (dataLen bytes) + Checksum (1) + End (1).
    for (uint16_t k = 0; k < (uint16_t)(dataLen + 2); k++) {
        if (!readByte(b)) return -1;
        if (idx < bufSize) buf[idx++] = b;
    }

    if (buf[idx - 1] != kEnd) return -1;   // malformed / truncated
    return (int)idx;
}

bool UHF_RFID::waitForOkResponse(uint8_t expectedCmd, uint32_t timeoutMs) {
    const uint32_t start = millis();

    while ((uint32_t)(millis() - start) < timeoutMs) {
        const uint32_t elapsed = millis() - start;
        uint8_t buf[64];
        const int n = readFrame(buf, sizeof(buf), timeoutMs - elapsed);
        if (n < 0) continue;

        // M100 firmware versions are inconsistent about the Type byte. The
        // command code is the reliable way to associate a non-error response
        // with the command that is currently pending (the same rule used by
        // M5Stack's current UnitJRD4035 driver).
        if (buf[2] == expectedCmd) {
            return true;
        }

        // A single inventory command can produce delayed tag notifications.
        // Ignore those here and continue waiting for the command response.
    }

    return false;
}

bool UHF_RFID::pollOnce(Tag &tag, uint32_t timeoutMs) {
    if (!_serial) return false;

    // Drop anything left in the RX buffer so we parse a fresh reply.
    for (int _f = 0; _f < 10; _f++) {
        while (_serial->available()) _serial->read();
        delay(2);
        if (!_serial->available()) break;
    }

    // Single-polling inventory command: BB 00 22 00 00 22 7E
    sendFrame(0x00, 0x22, nullptr, 0);

    uint8_t buf[64];
    int n = readFrame(buf, sizeof(buf), timeoutMs);
    if (n < 0) return false;

    const uint8_t  cmd     = buf[2];
    const uint16_t dataLen = ((uint16_t)buf[3] << 8) | buf[4];

    // 0xFF => reader reports an error, most often "no tag in field" (code 0x15).
    if (cmd == 0xFF) return false;

    // A tag notice is: cmd 0x22, data = RSSI(1) + PC(2) + EPC(N) + CRC(2).
    if (cmd != 0x22 || dataLen < 5) return false;

    const uint8_t *d = &buf[5];
    uint16_t epcLen = dataLen - 5;               // subtract RSSI + PC + CRC
    if (epcLen > kMaxEpc) epcLen = kMaxEpc;

    tag.rssi  = d[0];
    tag.pc[0] = d[1];
    tag.pc[1] = d[2];
    tag.epcLen = (uint8_t)epcLen;
    memcpy(tag.epc, &d[3], epcLen);
    tag.crc = ((uint16_t)d[3 + epcLen] << 8) | d[4 + epcLen];
    return true;
}

bool UHF_RFID::getVersion(String &out, uint32_t timeoutMs) {
    if (!_serial) return false;
    for (int _f = 0; _f < 10; _f++) {
        while (_serial->available()) _serial->read();
        delay(2);
        if (!_serial->available()) break;
    }

    // Info command, data byte 0x00 = hardware version.
    const uint8_t param = 0x00;
    sendFrame(0x00, 0x03, &param, 1);

    uint8_t buf[64];
    int n = readFrame(buf, sizeof(buf), timeoutMs);
    if (n < 0 || buf[2] != 0x03) return false;

    const uint16_t dataLen = ((uint16_t)buf[3] << 8) | buf[4];
    out = "";
    // First data byte echoes the info type; the rest is an ASCII string.
    for (uint16_t k = 1; k < dataLen; k++) out += (char)buf[5 + k];
    return true;
}

bool UHF_RFID::setTxPower(uint16_t dBm_x100, uint32_t timeoutMs) {
    if (!_serial) return false;
    for (int _f = 0; _f < 10; _f++) {
        while (_serial->available()) _serial->read();
        delay(2);
        if (!_serial->available()) break;
    }

    const uint8_t param[2] = { (uint8_t)(dBm_x100 >> 8), (uint8_t)(dBm_x100 & 0xFF) };
    sendFrame(0x00, 0xB6, param, 2);
    return waitForOkResponse(0xB6, timeoutMs);
}

bool UHF_RFID::setIdleMode(bool idle, uint32_t timeoutMs) {
    if (!_serial) return false;

    // IDLE command (0x04):
    //   byte 0: 1 enters IDLE, 0 leaves IDLE
    //   byte 1: reserved, fixed at 1
    //   byte 2: automatic-IDLE timeout in minutes; 0 disables it
    const uint8_t params[3] = {idle ? (uint8_t)0x01 : (uint8_t)0x00,
                               0x01, 0x00};

    // Remove frames already buffered before sending the state-change command.
    // waitForOkResponse() also tolerates a frame that arrives just afterward.
    for (int _f = 0; _f < 10; _f++) {
        while (_serial->available()) _serial->read();
        delay(2);
        if (!_serial->available()) break;
    }
    sendFrame(0x00, 0x04, params, sizeof(params));
    return waitForOkResponse(0x04, timeoutMs);
}
