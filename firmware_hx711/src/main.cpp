#include <Arduino.h>
#include <math.h>
#include <stdlib.h>

#include "HX711.h"
#include <config.h>

static_assert(sizeof(kLoadcellDoutPins) / sizeof(kLoadcellDoutPins[0]) == kNumLoadCells,
              "kLoadcellDoutPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellSckPins) / sizeof(kLoadcellSckPins[0]) == kNumLoadCells,
              "kLoadcellSckPins must have exactly kNumLoadCells entries");
static_assert(sizeof(kLoadcellPolarities) / sizeof(kLoadcellPolarities[0]) == kNumLoadCells,
              "kLoadcellPolarities must have exactly kNumLoadCells entries");

namespace {

HX711 gCells[kNumLoadCells];

// The reference mass is placed at each of these positions in turn. We need at
// least kNumLoadCells independent placements to solve for every corner factor;
// the four corners give that, and the extra centre placement makes the fit
// better conditioned and yields a residual we can report as a quality check.
constexpr uint8_t kNumPlacements = 5;  // 4 corners + centre
const char *const kPlacementNames[kNumPlacements] = {
    "the FRONT-LEFT corner",
    "the FRONT-RIGHT corner",
    "the BACK-RIGHT corner",
    "the BACK-LEFT corner",
    "the CENTRE",
};
static_assert(sizeof(kPlacementNames) / sizeof(kPlacementNames[0]) == kNumPlacements,
              "kPlacementNames must have exactly kNumPlacements entries");
static_assert(kNumPlacements >= kNumLoadCells,
              "need at least kNumLoadCells placements to solve for every corner");
static_assert(kNumLoadCells == 4,
              "placement prompts assume a 4-corner plate; update kPlacementNames "
              "and kNumPlacements for a different geometry");

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

// Solve the n×n system A·x = b in place (Gaussian elimination with partial
// pivoting), where n == kNumLoadCells. A and b are overwritten. Returns false if
// the matrix is singular, i.e. the placements were not independent enough.
bool solveLinearSystem(double A[kNumLoadCells][kNumLoadCells],
                       double b[kNumLoadCells],
                       double x[kNumLoadCells]) {
  constexpr uint8_t n = kNumLoadCells;

  for (uint8_t col = 0; col < n; col++) {
    uint8_t pivot = col;
    double best = fabs(A[col][col]);
    for (uint8_t row = col + 1; row < n; row++) {
      const double magnitude = fabs(A[row][col]);
      if (magnitude > best) {
        best = magnitude;
        pivot = row;
      }
    }
    if (best <= 0.0) {
      return false;
    }

    if (pivot != col) {
      for (uint8_t c = 0; c < n; c++) {
        const double tmp = A[col][c];
        A[col][c] = A[pivot][c];
        A[pivot][c] = tmp;
      }
      const double tmp = b[col];
      b[col] = b[pivot];
      b[pivot] = tmp;
    }

    for (uint8_t row = col + 1; row < n; row++) {
      const double factor = A[row][col] / A[col][col];
      for (uint8_t c = col; c < n; c++) {
        A[row][c] -= factor * A[col][c];
      }
      b[row] -= factor * b[col];
    }
  }

  for (int8_t row = static_cast<int8_t>(n) - 1; row >= 0; row--) {
    if (A[row][row] == 0.0) {
      return false;
    }
    double sum = b[row];
    for (uint8_t c = row + 1; c < n; c++) {
      sum -= A[row][c] * x[c];
    }
    x[row] = sum / A[row][row];
  }

  return true;
}

void runCalibration(float calibrationMassG) {
  Serial.println();
  Serial.println("Step 1/3: Prepare the empty scale");
  Serial.println("Leave the plate/box installed and remove every loose object.");
  Serial.println("Press Enter when the scale is empty and stable.");
  waitForEnter();

  // Tare every cell. A scale factor of 1 makes get_value() return tared raw
  // ADC counts.
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    gCells[i].set_scale(1.0f);

    if (!gCells[i].wait_ready_timeout(3000)) {
      Serial.print("ERROR: HX711 cell ");
      Serial.print(i);
      Serial.println(" not ready. Calibration cancelled.");
      return;
    }

    Serial.print("Taring cell ");
    Serial.print(i);
    Serial.print(" ... ");
    gCells[i].tare(kTareSamples);
    Serial.println("done");
  }

  // response[p][i] = tared counts of cell i with the mass at placement p.
  double response[kNumPlacements][kNumLoadCells];

  Serial.println();
  Serial.println("Step 2/3: Measure the reference object at each position");
  Serial.print("Place the ");
  Serial.print(calibrationMassG, 3);
  Serial.println(" g object at each position below, one at a time.");

  for (uint8_t p = 0; p < kNumPlacements; p++) {
    Serial.println();
    Serial.print("Placement ");
    Serial.print(p + 1);
    Serial.print('/');
    Serial.print(kNumPlacements);
    Serial.print(": place the object over ");
    Serial.print(kPlacementNames[p]);
    Serial.println(", keep it still, then press Enter.");
    waitForEnter();

    double placementTotal = 0.0;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
      if (!gCells[i].wait_ready_timeout(3000)) {
        Serial.print("ERROR: HX711 cell ");
        Serial.print(i);
        Serial.println(" not ready. Calibration cancelled.");
        return;
      }

      const double counts =
          static_cast<double>(gCells[i].get_value(kCalibrationSamples)) *
          kLoadcellPolarities[i];
      response[p][i] = counts;
      placementTotal += counts;

      Serial.print("  cell ");
      Serial.print(i);
      Serial.print(": ");
      Serial.println(counts, 1);
    }

    Serial.print("  total: ");
    Serial.println(placementTotal, 1);

    if (!isfinite(placementTotal) || placementTotal < kMinReferenceSignalCounts) {
      Serial.println(
          "ERROR: signal at this placement is too small. Is the object on the "
          "scale? Calibration cancelled.");
      return;
    }
  }

  // Step 3: solve for the per-corner factors.
  //
  // For a rigid plate the four reaction forces always sum to the applied weight,
  // so with x[i] = 1 / factor[i] (grams per count) every placement must satisfy
  //   sum_i response[p][i] * x[i] = calibrationMassG.
  // That is kNumPlacements equations in kNumLoadCells unknowns; solve it in the
  // least-squares sense via the normal equations (AtA) x = (Atb).
  double AtA[kNumLoadCells][kNumLoadCells] = {};
  double Atb[kNumLoadCells] = {};
  for (uint8_t p = 0; p < kNumPlacements; p++) {
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
      Atb[i] += response[p][i] * calibrationMassG;
      for (uint8_t j = 0; j < kNumLoadCells; j++) {
        AtA[i][j] += response[p][i] * response[p][j];
      }
    }
  }

  double x[kNumLoadCells] = {};
  if (!solveLinearSystem(AtA, Atb, x)) {
    Serial.println(
        "ERROR: could not solve the calibration system. The placements were not "
        "independent enough; repeat with the mass clearly over each corner.");
    return;
  }

  float factors[kNumLoadCells];
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    if (!isfinite(x[i]) || x[i] <= 0.0) {
      Serial.print("ERROR: cell ");
      Serial.print(i);
      Serial.println(
          " produced a non-physical factor (<= 0). Check its wiring, polarity, "
          "and that the mass was placed correctly. Calibration cancelled.");
      return;
    }
    factors[i] = static_cast<float>(1.0 / x[i]);
  }

  // Residual: how well each placement reproduces the known mass with the fitted
  // factors. A large value means a bad placement or a mechanical problem.
  double maxAbsResidualG = 0.0;
  for (uint8_t p = 0; p < kNumPlacements; p++) {
    double predictedG = 0.0;
    for (uint8_t i = 0; i < kNumLoadCells; i++) {
      predictedG += response[p][i] * x[i];
    }
    const double residualG = fabs(predictedG - calibrationMassG);
    if (residualG > maxAbsResidualG) {
      maxAbsResidualG = residualG;
    }
  }

  Serial.println();
  Serial.println("Calibration complete");
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    Serial.print("  cell ");
    Serial.print(i);
    Serial.print(" factor: ");
    Serial.print(factors[i], 6);
    Serial.println(" raw counts/gram");
  }
  Serial.print("  max placement residual: ");
  Serial.print(maxAbsResidualG, 2);
  Serial.print(" g (");
  Serial.print(100.0 * maxAbsResidualG / calibrationMassG, 2);
  Serial.println("% of the reference mass)");

  Serial.println();
  Serial.println("Copy this into firmware/include/config.h:");
  Serial.print("  constexpr float kCalibrationFactors[kNumLoadCells] = {");
  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    if (i > 0) {
      Serial.print(", ");
    }
    Serial.print(factors[i], 6);
    Serial.print('f');
  }
  Serial.println("};");

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
  Serial.print("HX711 4-corner gain calibration firmware (");
  Serial.print(kNumLoadCells);
  Serial.println(" load cells)");
  Serial.println("Serial speed: 57600 baud");
  Serial.println("Configure the serial monitor to send a line ending.");

  for (uint8_t i = 0; i < kNumLoadCells; i++) {
    gCells[i].begin(kLoadcellDoutPins[i], kLoadcellSckPins[i]);
    if (!gCells[i].wait_ready_timeout(3000)) {
      Serial.print("HX711 cell ");
      Serial.print(i);
      Serial.print(" not found (DOUT=");
      Serial.print(kLoadcellDoutPins[i]);
      Serial.print(", SCK=");
      Serial.print(kLoadcellSckPins[i]);
      Serial.println("). Check power and wiring.");
      haltWithError("HX711 initialisation failed.");
    }
    Serial.print("Cell ");
    Serial.print(i);
    Serial.println(" ready");
  }
}

void loop() {
  const float calibrationMassG = readCalibrationMassG();
  runCalibration(calibrationMassG);
}
