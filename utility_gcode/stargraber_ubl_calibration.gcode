; StarGraber full Z alignment and UBL calibration
; Calibrated for PLA with a 60C bed.
; Change both S60 values when calibrating for another bed temperature.
; Clean the nozzle and bed before running. Supervise the first run.

G90
M117 Heating calibration

M104 S160             ; Warm nozzle without excessive oozing
M140 S60              ; Set calibration bed temperature
M190 S60              ; Wait for bed
M109 S160             ; Wait for nozzle

; Five-minute bed soak with display progress
M117 Soak |..........|
G4 S30
M117 Soak |#.........|
G4 S30
M117 Soak |##........|
G4 S30
M117 Soak |###.......|
G4 S30
M117 Soak |####......|
G4 S30
M117 Soak |#####.....|
G4 S30
M117 Soak |######....|
G4 S30
M117 Soak |#######...|
G4 S30
M117 Soak |########..|
G4 S30
M117 Soak |#########.|
G4 S30
M117 Soak |##########|

M117 Homing
M420 S0               ; Disable the old mesh
G28                    ; Home XYZ

M117 Aligning Z motors
G34                    ; Align the two Z motors
                       ; HOME_AFTER_G34 automatically re-homes Z

M117 Creating UBL mesh
G29 P1                 ; Probe every reachable mesh point
G29 P3                 ; Smart-fill unreachable edge points
G29 P3                 ; Continue filling inward
G29 P3                 ; Ensure the 10x10 mesh is complete

M117 Saving UBL slot 0
G29 A                  ; Activate UBL
G29 F5                 ; Set 5mm fade, matching Orca start G-code
G29 S0                 ; Store the mesh explicitly in slot 0
M500                   ; Save UBL state and settings to EEPROM

G29 T                  ; Print the completed mesh map to the console

M104 S0
M140 S0
G27                    ; Park at X10 Y195
M117 Calibration saved
