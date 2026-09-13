# LaundryBox

LaundryBox is a TMS course project at TUM for detecting foreign objects in
garments handled by professional garment-leasing and industrial-laundry
services.

## Project concept

Each garment already carries an RFID tag. LaundryBox combines that identity
with a garment-specific weight comparison to decide whether a returned garment
needs to be inspected manually. A barcode can serve as a documented prototype
fallback if RFID proves technically infeasible.

The return station is envisioned as a box similar to a Decathlon self-checkout
bin. It integrates:

- an RFID reader to identify the garment, with barcode as a fallback;
- a scale to measure its current weight;
- optionally, a DC electromagnetic sensing system for ferromagnetic objects if
  the current feasibility tests succeed; and
- a two-state traffic-light interface that communicates the inspection decision
  to an operator.

## Intended workflow

### 1. Clean garment leaves the laundry

1. The garment's RFID tag is read.
2. The clean garment is weighed.
3. Its measured reference weight is stored or updated in the database and
   associated with the RFID identifier.

The prototype may use the same physical scale for clean reference and return
measurements.

### 2. Dirty garment is returned

1. The RFID tag is read again.
2. The returned garment is weighed in the LaundryBox.
3. The corresponding clean reference weight is retrieved from the database.
4. The prototype applies either no contamination correction or a documented,
   configurable fixed offset.
5. The normalized weight difference is used as evidence for or against the
   presence of a foreign object.
6. If feasible within the prototype period, magnetic sensing provides an
   additional signal for ferromagnetic foreign objects.

A future system may learn the typical contamination of each individual garment
from its return history.

### 3. Operator decision

The system displays a two-state traffic-light result:

- **PASS / green:** no manual inspection indicated.
- **CHECK / red:** manual inspection required because an object is suspected or
  the result is uncertain.

The decision threshold prioritizes sensitivity because missed damaging objects
are considered more costly than unnecessary manual checks.

## Current scope and assumptions

- The target users are professional garment-leasing or industrial-laundry
  operators, not private households.
- Every garment can be identified by RFID or, if necessary for the prototype,
  by a barcode fallback, and has a reference-weight record.
- The outbound clean weight is the garment-specific reference value.
- The prototype evaluates garments from 50 g to 1,000 g and initially targets a
  decision time of at most 10 seconds.
- A learned dirt-normalization model is outside the initial prototype scope.
- Built-in metallic garment components such as zippers, buttons, and fasteners
  are assumed to be non-ferromagnetic. This assumption must be tested against
  the actual garment inventory.
- If included, the magnetic subsystem is intended to detect ferromagnetic
  material; it will not detect every metal or every possible foreign object.
- The system recommends whether a human check is needed; it does not
  automatically remove the object.

## Core project question

Can a garment-specific weight difference identify damaging foreign objects with
very high sensitivity while keeping the number of unnecessary manual checks
manageable, and can magnetic sensing improve that decision within the available
prototype time?

## Status

This README records the team's initial agreed project baseline. Hardware
architecture, sensing method, object classes, performance targets, safety
requirements, and evaluation design remain open for the next project phase.

The consolidated prototype requirements are maintained in
[REQUIREMENTS.md](REQUIREMENTS.md).
