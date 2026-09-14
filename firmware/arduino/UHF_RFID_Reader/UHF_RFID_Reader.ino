#define RFID_SERIAL Serial1      // RX1 = pin 0, TX1 = pin 1

static const uint8_t  FRAME_HEADER = 0xBB;
static const uint8_t  FRAME_END    = 0x7E;
static const uint8_t  MAX_EPC      = 32;

// ----- send one command frame -------------------------------------------------
void sendFrame(uint8_t type, uint8_t cmd, const uint8_t *data, uint16_t len) {
    uint8_t frame[64];
    size_t i = 0;
    frame[i++] = FRAME_HEADER;
    frame[i++] = type;
    frame[i++] = cmd;
    frame[i++] = (len >> 8) & 0xFF;
    frame[i++] = len & 0xFF;
    for (uint16_t k = 0; k < len && i < sizeof(frame) - 2; k++) frame[i++] = data[k];

    uint32_t sum = 0;
    for (size_t k = 1; k < i; k++) sum += frame[k];   // Type .. last Data byte
    frame[i++] = sum & 0xFF;
    frame[i++] = FRAME_END;

    RFID_SERIAL.write(frame, i);
    RFID_SERIAL.flush();
}

// ----- read one complete frame (length-aware) ---------------------------------
// Returns frame length, or -1 on timeout / malformed frame.
int readFrame(uint8_t *buf, size_t bufSize, uint32_t timeoutMs) {
    uint32_t start = millis();
    size_t idx = 0;
    uint8_t b;

    // sync to header
    do {
        while (!RFID_SERIAL.available()) {
            if ((uint32_t)(millis() - start) >= timeoutMs) return -1;
        }
        b = RFID_SERIAL.read();
    } while (b != FRAME_HEADER);
    buf[idx++] = b;

    // read Type, Cmd, Len MSB, Len LSB, then Data + Checksum + End
    uint16_t remaining = 4;         // header known; need 4, then top up with dataLen+2
    bool haveLen = false;
    uint16_t dataLen = 0;

    while (remaining > 0) {
        while (!RFID_SERIAL.available()) {
            if ((uint32_t)(millis() - start) >= timeoutMs) return -1;
        }
        b = RFID_SERIAL.read();
        if (idx < bufSize) buf[idx++] = b;
        remaining--;

        if (!haveLen && idx == 5) {           // just read Len LSB
            dataLen = ((uint16_t)buf[3] << 8) | buf[4];
            remaining = dataLen + 2;          // Data + Checksum + End
            haveLen = true;
        }
    }

    if (buf[idx - 1] != FRAME_END) return -1;
    return (int)idx;
}

// ----- single inventory round -------------------------------------------------
struct Tag {
    uint8_t  rssi;
    uint8_t  epc[MAX_EPC];
    uint8_t  epcLen;
};

bool pollOnce(Tag &tag, uint32_t timeoutMs = 200) {
    while (RFID_SERIAL.available()) RFID_SERIAL.read();   // clear stale bytes

    sendFrame(0x00, 0x22, nullptr, 0);                    // single polling

    uint8_t buf[64];
    int n = readFrame(buf, sizeof(buf), timeoutMs);
    if (n < 0) return false;

    uint8_t  cmd     = buf[2];
    uint16_t dataLen = ((uint16_t)buf[3] << 8) | buf[4];

    if (cmd == 0xFF) return false;             // reader error, e.g. no tag found
    if (cmd != 0x22 || dataLen < 5) return false;

    const uint8_t *d = &buf[5];                // RSSI(1) PC(2) EPC(N) CRC(2)
    uint16_t epcLen = dataLen - 5;
    if (epcLen > MAX_EPC) epcLen = MAX_EPC;

    tag.rssi   = d[0];
    tag.epcLen = (uint8_t)epcLen;
    memcpy(tag.epc, &d[3], epcLen);
    return true;
}

void printHex(const uint8_t *data, uint8_t len) {
    static const char *hex = "0123456789ABCDEF";
    for (uint8_t i = 0; i < len; i++) {
        Serial.print(hex[(data[i] >> 4) & 0x0F]);
        Serial.print(hex[data[i] & 0x0F]);
    }
}

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) {}
    RFID_SERIAL.begin(115200);

    Serial.println();
    Serial.println("LaundryBox UHF RFID reader");
    Serial.println("Scanning for tags...");
}

void loop() {
    Tag tag;
    if (pollOnce(tag)) {
        Serial.print("EPC: ");
        printHex(tag.epc, tag.epcLen);
        Serial.print("  RSSI: ");
        Serial.println(tag.rssi);
    }
    delay(200);
}
