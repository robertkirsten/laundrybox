#include <Arduino.h>
#include <math.h>
#include <stdlib.h>

#include "HX711.h"

namespace {

constexpr uint8_t LOADCELL_DOUT_PIN = 2;
constexpr uint8_t LOADCELL_SCK_PIN = 3;

constexpr uint8_t TARE_SAMPLES = 20;
constexpr uint8_t CALIBRATION_SAMPLES = 20;
constexpr float MIN_REFERENCE_SIGNAL_COUNTS = 100.0f;

HX711 scale;

void haltWithError(const char *message) {
  Serial.print("ERROR: ");
  Serial.println(message);

  while (true) {
    delay(1000);
  }
}

String readSerialLine() {
  String line;

  while (true) {
    while (Serial.available() > 0) {
      const char character = static_cast<char>(Serial.read());

      if (character == '\r' || character == '\n') {
        // A serial monitor commonly sends CR+LF. Consume the second line-ending
        // character so it cannot accidentally acknowledge the next prompt.
        delay(2);
        while (Serial.available() > 0) {
          const int nextCharacter = Serial.peek();
          if (nextCharacter != '\r' && nextCharacter != '\n') {
            break;
          }
          Serial.read();
        }
        return line;
      }

      line += character;
    }

    delay(1);
  }
}

void waitForEnter() {
  readSerialLine();
}

float readCalibrationMassG() {
  while (true) {
    Serial.println();
    Serial.println("Enter the calibration object's mass in grams, then press Enter:");

    String input = readSerialLine();
    input.trim();

    char *end = nullptr;
    const float massG = strtof(input.c_str(), &end);
    const bool parsedEntireInput =
        end != input.c_str() && end != nullptr && *end == '\0';

    if (parsedEntireInput && isfinite(massG) && massG > 0.0f) {
      Serial.print("Calibration mass: ");
      Serial.print(massG, 3);
      Serial.println(" g");
      return massG;
    }

    Serial.println("Invalid mass. Enter a positive number, for example: 557.4");
  }
}

void runCalibration(float calibrationMassG) {
  // A scale factor of 1 makes get_value() return tared raw ADC counts.
  scale.set_scale(1.0f);

  Serial.println();
  Serial.println("Step 1/2: Prepare the empty scale");
  Serial.println("Leave the plate/box installed and remove every loose object.");
  Serial.println("Press Enter when the scale is empty and stable.");
  waitForEnter();

  if (!scale.wait_ready_timeout(3000)) {
    Serial.println("ERROR: HX711 not ready. Calibration cancelled.");
    return;
  }

  Serial.println("Taring...");
  scale.tare(TARE_SAMPLES);

  Serial.println();
  Serial.println("Step 2/2: Measure the reference object");
  Serial.print("Place the ");
  Serial.print(calibrationMassG, 3);
  Serial.println(" g object on the scale and keep it still.");
  Serial.println("Press Enter when the reading is stable.");
  waitForEnter();

  if (!scale.wait_ready_timeout(3000)) {
    Serial.println("ERROR: HX711 not ready. Calibration cancelled.");
    return;
  }

  Serial.println("Sampling...");
  const float rawReferenceCounts = scale.get_value(CALIBRATION_SAMPLES);

  if (!isfinite(rawReferenceCounts) ||
      fabsf(rawReferenceCounts) < MIN_REFERENCE_SIGNAL_COUNTS) {
    Serial.println(
        "ERROR: Reference signal is too small. Check the wiring, mounting, and sequence.");
    return;
  }

  const float calibrationFactor = rawReferenceCounts / calibrationMassG;

  Serial.println();
  Serial.println("Calibration complete");
  Serial.print("Tared raw reading: ");
  Serial.println(rawReferenceCounts, 3);
  Serial.print("Calibration factor: ");
  Serial.print(calibrationFactor, 6);
  Serial.println(" raw counts/gram");
  Serial.println();
  Serial.println("Use this value with the HX711 library:");
  Serial.print("scale.set_scale(");
  Serial.print(calibrationFactor, 6);
  Serial.println("f);");
  Serial.println("After calling scale.tare(), scale.get_units() will return grams.");
  Serial.println();
  Serial.println("Remove the object. A new calibration can now be started.");
}

}  // namespace

void setup() {
  Serial.begin(57600);

  const unsigned long serialWaitStartedMs = millis();
  while (!Serial && millis() - serialWaitStartedMs < 3000) {
    // Give the USB serial monitor a short opportunity to connect.
  }

  Serial.println();
  Serial.println("HX711 calibration firmware");
  Serial.println("Serial speed: 57600 baud");
  Serial.println("Configure the serial monitor to send a line ending.");

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  if (!scale.wait_ready_timeout(3000)) {
    haltWithError("HX711 not found. Check power and wiring.");
  }
}

void loop() {
  const float calibrationMassG = readCalibrationMassG();
  runCalibration(calibrationMassG);
}
