# Agent Notes

This repository contains Marlin firmware and OrcaSlicer presets for a DIY Graber i3 style printer named `StarGraber`.

## Printer Context

- Board: MKS TinyBee
- Firmware constraint: do not recommend `LIN_ADVANCE`; this board/setup does not support it in the user's environment.
- The repo owner is the only user of this repository, so tracking live OrcaSlicer user presets is intentional.

## Orca / Preset Context

- Track both `orca/OrcaSlicer/system/Custom/` and `orca/OrcaSlicer/user/default/` because they contain the real working machine, filament, and process presets.
- Keep bundled stock Orca filament library content ignored unless there is a specific reason to version it.

## Known Troubleshooting Context

- Current print issue under investigation: strong stringing on every print.
- Lowering nozzle temperature helps, but stringing is still severe even around `180C` with PLA.
- The same filament prints well on another printer.
- The nozzle has already been changed.
- Extruder grip has already been checked and is good.
- Retraction experiments already tried with no meaningful effect: retraction speed, retraction length, and z-hop on/off.
- Overall print quality is otherwise good.
- Hotend heatsink fan is confirmed strong and always on; it is wired directly to the `300W PSU`.
- Measured hotend/heatsink temperatures during troubleshooting: with the nozzle set to `220C`, the heatsink measured about `36C` at the top, `41C` in the middle, and about `73C` near the last fin close to the block.
- External spot measurement near the nozzle showed about `202C` when the printer reported `220C`, but this should be treated cautiously because surface nozzle readings can under-read depending on measurement method and emissivity.

## Maintenance Rule

- Update `AGENTS.md` whenever relevant printer, slicer, hardware, workflow, or troubleshooting information is discovered in chat and is not already represented in the repository.
- Treat this file as the place to preserve important context learned from conversation so future agents do not lose it.
