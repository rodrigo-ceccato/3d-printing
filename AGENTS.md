# Agent Notes

This repository contains Marlin firmware and OrcaSlicer presets for a DIY Graber i3 style printer named `StarGraber`.

## Printer Context

- Board: MKS TinyBee
- Firmware constraint: do not recommend `LIN_ADVANCE`; this board/setup does not support it in the user's environment.
- The repo owner is the only user of this repository, so tracking live OrcaSlicer user presets is intentional.
- `mks_tinybee` builds with `ESP3D_WIFISUPPORT` should keep `AsyncTCP` pinned to `me-no-dev/AsyncTCP@3.3.2` and `ESP Async WebServer` pinned to `sbkila/ESP Async WebServer@1.2.3`; newer unpinned packages can break against the old ESP32 Arduino core with missing watchdog config symbols such as `CONFIG_ESP_TASK_WDT_TIMEOUT_S`.

## Orca / Preset Context

- Track both `orca/OrcaSlicer/system/Custom/` and `orca/OrcaSlicer/user/default/` because they contain the real working machine, filament, and process presets.
- Keep bundled stock Orca filament library content ignored unless there is a specific reason to version it.
- For Orca's native `ESP3D` print host, set `print_host` to the bare host or IP without `http://`; use `print_host_webui` for the full browser URL if you want one-click access to the web interface as well.
- Current `StarGraber` ESP3D workflow assumes web authentication is disabled; Orca's ESP3D integration may not work correctly if the web UI requires login.
- Tested on 2026-03-29: Orca's built-in `ESP3D` `Upload and Print` path reached the printer but did not leave the uploaded file visible on the Marlin SD card. Marlin then failed `M23` with `open failed` for the expected 8.3 filename, and `M20 L` over ESP3D websocket confirmed the file was not present in the SD listing afterward.
- Live ESP3D probing on 2026-03-29 showed this TinyBee setup is using ESP3D's direct-SD `/upload` route, not the `/upload_serial` route that Orca hardcodes for `ESP3D`. The working browser UI creates directories and uploads to SD through `/upload`, and its print button sends `M23 <current_path><filename>` followed by `M24`.
- `StarGraber` now uses a local helper, [`tools/orca_esp3d_up_and_p_proxy.py`](/home/fopor/Software/marlin/Marlin-2.1.3-b2/tools/orca_esp3d_up_and_p_proxy.py), with Orca `print_host` set to `127.0.0.1:18889`. The helper accepts Orca's `/upload_serial` request, forwards the file to ESP3D's direct-SD `/upload` endpoint, forces uploads into `/up_and_p/`, and rewrites Orca's later `M23` to `/up_and_p/<filename>` before letting `M24` start the print.
- Local desktop startup now goes through [`tools/start_orca_with_esp3d_proxy.py`](/home/fopor/Software/marlin/Marlin-2.1.3-b2/tools/start_orca_with_esp3d_proxy.py), and the user launcher at `~/.local/share/applications/orca.desktop` points to that wrapper instead of directly to the AppImage. The wrapper auto-starts the local proxy when Orca opens and also exposes `--ensure-proxy-only` and `--stop-proxy` management commands.
- During helper verification on 2026-03-29, the live ESP3D direct-SD endpoint later started returning `{"status":"No SD Card"}` on `/upload?path=/up_and_p/`, and `M21` did not immediately recover it. End-to-end helper verification was therefore blocked by printer SD availability, not by a local Python startup failure.

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
