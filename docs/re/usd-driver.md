# USDdrv / USDtrap V01.02 — NOVA's music driver (core, hardware, INT F4h)

The sound part of AdvBIOS 0.54 (`NV.OV1`, segment 0328, 1C08h bytes): **"USDdrv"**, the INT F4h front end,
and **"USDtrap"**, a YM2203 interrupt driver with a byte-code sequencer ("Copyright (C) K.KONDO 1991 All
rights reserved...V01.02"). This document covers everything except the byte code itself: layout, variables,
start-up and chip detection, register access, the interrupt handler, the two timers and real-time rates, the
INT F4h services, fades, the unused effect-bank path, and what AdvBIOS does with the chip otherwise. The
song format and the sequencer are in [usd-sequencer.md](usd-sequencer.md); the map this work started from
is [advbios.md](advbios.md) §4.6 and §9 (corrections to it: §11 below).

Conventions

* Addresses are offsets in segment 0328 of the unpacked `resources/derived/exe/NV.OV1` at load base 0
  (file offset = 200h + 3280h + offset), as in `resources/derived/listing/advbios.lst`. `D:xxxx` is the
  driver's data segment 2B0F.
* **verified** = read in the code *and* reproduced by the independent model `re-tools/usdmodel.py` against
  the original code running in `re-tools/usdemu.py` (register writes identical, clock for clock; §10);
  **code** = read in the code only; **inferred** = interpretation or hardware knowledge.
  Unless marked otherwise a statement is **verified**.
* fM = 3 993 600 Hz, the OPN master clock of the PC-9801-26K board. "Clock" = 1/fM.
* Reference: Valley Bell's disassembly of the Dengeki Nurse build of the same AdvBIOS
  (`Adv98V/DengekiNurse/ADVBIOS.DEC2.asm`, <https://github.com/ValleyBell/PC98VNResearch>). It labels three
  routines of this segment (`WaitForFM`, `FMDelay`, `ReadFM`) and the two signature strings; nothing else
  of the sound code is annotated there, so everything below was worked out on NOVA's binary.

Tools: `re-tools/usdemu.py` (the original driver under unicorn + fake YM2203 → VGM / register log),
`re-tools/usdmodel.py` (clean-room model, `--check`), `re-tools/usoinfo.py` (file dump).

## 1. The driver in one page

* Hardware: **one YM2203 (OPN) at ports 188h/18Ah, nothing else** — 3 FM channels + 3 SSG channels. No
  OPNA features, no rhythm, no ADPCM, no second address, no beeper fallback. Without the chip every
  service is a harmless no-op (§3.1).
* Six fixed channels, numbered 0–2 = FM 1–3 and 3–5 = SSG 1–3. A song is a set of up to six *tracks*, each
  bound to one channel. There is no channel allocation and no mixing of two tracks on one channel.
* **Two clocks, both OPN timers, one interrupt.**
  **Timer A = note clock** (variable; the tempo command re-programs it): one overflow = one *tick*; a whole
  note is 192 ticks. **Timer B = effect clock**, fixed at 105.05 Hz (9.519 ms): software envelopes of the
  SSG channels, all LFOs, portamento and the master-volume fade advance once per timer-B overflow.
  The two are not synchronised with each other.
* Music is loaded as a whole file into a 12 KB buffer and played in place. Play, stop, fade-out, fade-in
  and "restart with a volume offset" are the only things NOVA uses (§5).
* A *master volume offset* (0 = full … −64) is added to every channel's volume. Fades move it by ±1 every
  7 effect ticks (64 steps = 4.26 s). **A fade does not stop anything**: after a fade-out the song keeps
  running at −64 until the caller stops it (NOVA's scripts do: `sound 2` … `sound 0`).
* Sound effects: the driver has a second buffer and a bank format for effects that would play *over* the
  music on a fixed clock (timer B) with priorities (§7). **NOVA does not use it** — its `NVSE*.USO` files
  are ordinary songs played through the music path, i.e. they replace the music.

## 2. Layout of segment 0328

| range | contents |
|---|---|
| 0000–001B | `usd_install_once` (AL≠0: hook INT F4h even without a chip) |
| 001C–004B | `sound_init` — far, called once by AdvBIOS start-up (§3.1) |
| 004C–008F | built-in init sequence, 68 bytes in `.USO` layout (§3.3) |
| 0090–011C | `usd_remove`, `sound_deinit` (far), `usd_hook_f4`, `usd_unhook_f4`, `usd_is_installed` |
| 011D–012F | INT F4h entry: `jmp short`; `"USDdrv",0` at +2; saved ES +8; data segment (2B0F) +0Ah; old vector +0Ch; `usd_present` 012D; `usd_enable` 012E |
| 0130–0176 | dispatcher; 0177–01B6 jump table (32 words) |
| 01B7–0556 | services, `.USO` binding `usd_bind_and_start` 02FE, `usdtrap_install` 04E9 / `usdtrap_remove` 052F |
| 0557–05B9 | `USDtrap` header: `jmp short`; `"USDtrap"`; chain vector 0560; vector number 0564; `jmp far cs:[0560]` 0566; variables 0570–0582 (§2.1); copyright 0583 |
| 05BA–07B2 | `opn_init` 05BA, `opn_shutdown` 06AE, `opn_irq` 0720, `opn_timer_ack` 0768 |
| 07B3–07BF | 13 zero bytes (unused) |
| 07C0–07D5 | note-length table, 11 words |
| 07D6–0895 | FM pitch table, 96 words |
| 0896–0955 | SSG period table, 96 words |
| 0956–0A5A | FM channel work areas, 3 × 57h |
| 0A5B–0B62 | SSG channel work areas, 3 × 58h |
| 0B63–0B6C | master volume / fade state (§2.1); 0B6D–0B70 zero |
| 0B71–0B72 | `FF FF`: dummy track data used to stop a channel (§5.2) |
| 0B73–0DD9 | far entry points of the core: `opn_reg_access` 0B73, `seq_start` 0BD1, `seq_stop` 0CA0, `seq_reset_channels` 0CE2, `seq_channel_ptr` 0D71, `seq_set_fade` 0D96 |
| 0DDA–0F7C | `seq_tick` — the interrupt-time sequencer (usd-sequencer.md §4) |
| 0F7D–16C7 | portamento, FM level output, SSG envelope, mixer on/off, the five LFO families |
| 16C8–1B8C | track interpreters `fm_row` 16C8 / `ssg_row` 17D2, pitch conversion 18DB, gate 1917, command tables 195E (FM) / 199E (SSG), command handlers 1A0C–1B8C |
| 1B90–1C07 | OPN I/O: `WaitForFM` 1B90, delay vector 1B99, `opn_read_reg` 1B9B, `ReadFM` 1BB0, `opn_write_reg` 1BB5, delay routines 1BD4 / 1BDE / 1BE1, `opn_select_delay` 1BEB (far) |

Names of the routines analysed for this document (not yet in `listing/advbios-names.tsv`; addresses for
whoever merges them):

| address | name | what |
|---|---|---|
| 0C4A | `seq_start_silence` | end whatever plays on the channels of the new song |
| 0C5F | `seq_start_bind` | fill the work areas from the track records |
| 0D18 | `seq_prio_check` | CF if the channel is busy with a higher priority |
| 0D30 | `seq_stop_if_prio` | stop channel if its priority ≤ AL |
| 0D46 | `seq_channel_end` | point the track at `FF FF` (0B71) and run it once |
| 0F7D | `porta_step` | slide `[10]` towards `[12]` |
| 0FA6 | `fm_set_level` | CX = volume → TL of the masked slots |
| 0FFD | `ssg_envelope` | one envelope step + volume register |
| 10A1 / 10CD | `ssg_key_on` / `ssg_key_off` | mixer register |
| 10FB / 1232 | `fm_pitch_lfo` / `fm_vol_lfo` | |
| 1213 | `fm_write_pitch` | CX = pitch → A4h/A0h |
| 1346 / 148F / 1595 | `ssg_pitch_lfo` / `ssg_vol_lfo` / `ssg_noise_lfo` | |
| 145E | `ssg_write_period` | CX → tone period, clamped to 0..FFFh |
| 16A0 | `ssg_write_noise` | |
| 16C8 / 17D2 | `fm_row` / `ssg_row` | execute commands up to the next note |
| 18DB | `pitch_to_fnum` | |
| 1917 | `gate_calc` | |
| 19DE / 19F0 | `fm_command` / `ssg_command` | dispatch of bytes C0h–FFh |
| 1A0C, 1A1C | `cmd_end_fm`, `cmd_end_ssg` | FF |
| 1A2B, 1A49, 1A31, 1A37, 1A50, 1A56, 1A5B, 1A75, 1A7A, 1A99, 1ABA, 1B29 | `cmd_transpose`, `cmd_volume`, `cmd_detune`, `cmd_tempo`, `cmd_gate`, `cmd_tie`, `cmd_porta`, `cmd_jump`, `cmd_loop_exit`, `cmd_loop_back`, `cmd_fm_voice`, `cmd_ssg_voice` | FE FD FC FB F8 F7 F6 F5 F4 F3 E1 E0 |

### 2.1 Variables

In the code segment (the driver runs with DS = 0328 inside the core):

| address | size | init | meaning |
|---|---|---|---|
| 012D | byte | 0 | `usd_present`: FFh if the chip was found, else 0 (returned by AH=21h) |
| 012E | word | 3 | `usd_enable`: bit 0 music, bit 1 effects (AH=06h) |
| 0560 | dword | – | `USDtrap` chain target (= `opn_irq`) |
| 0564 | byte | 0 | vector number the stub was installed on (14h/15h; 0 = none) |
| 0570 | word | 0 | interrupt-nesting counter: +1 on entry, cleared on exit; never tested (**code**) |
| 0572 | byte | BFh | shadow of SSG register 07h (mixer) |
| 0573 | byte | 0Fh | low nibble written to register 27h (load + enable both timers) |
| 0574 | word | 01F7h | timer-A word; **bit 15 = "re-program at the next interrupt"** (§4.2) |
| 0576 | word | 00DFh | written by tempo commands of tracks not clocked by timer A; never read (§4.2) |
| 0578 | byte | 14h | interrupt vector of the board (15h if port A bit 7 is clear) |
| 0579 | byte | 10h | its bit in the slave PIC mask (20h for vector 15h) |
| 057A | word | 0 | 1 once `opn_init` succeeded; every core entry point returns at once while it is 0 |
| 057C | dword | – | previous owner of the interrupt vector (chained to) |
| 0581 | byte | 0 | timer flags of the interrupt being served: bit 0 = A, bit 1 = B |
| 0582 | byte | – | slave PIC mask as found at init (saved, never used again; **code**) |
| 0956 + 57h·n | 57h | 0 | FM channel n work area (usd-sequencer.md §3) |
| 0A5B + 58h·n | 58h | 0 | SSG channel n work area |
| 0B63 | byte | 0 | fade priority threshold: channels with priority below it ignore the master volume |
| 0B65 | word | 0 | **master volume offset**, signed, 0 … −64 |
| 0B67 | word | 0 | fade step (signed) |
| 0B69 | word | 0 | fade period in effect ticks; 0 = no fade running |
| 0B6B | word | 0 | fade countdown |
| 1B99 | word | 1BDEh | pointer to the I/O delay routine |

In the data segment 2B0F (zero-filled in the file):

| address | size | meaning |
|---|---|---|
| D:0000 | 3000h | music file buffer |
| D:3000 | 2000h | effect-bank buffer |
| D:5000 | byte | 1 = a music file has been loaded |
| D:5001 | byte | 1 = an effect bank has been loaded |
| D:5002 | 60 | bound track records of the music (6 × 10 bytes) |
| D:503E | 60 | bound track records of the last effect started |
| D:507A / 507C | words | default FM voice table pointer (offset / segment) = SI / CX at install: garbage, see §3.1 |
| D:507E / 5080 | words | default SSG voice table pointer = DI / DX at install |
| D:5082 | word | joystick state of the previous AH=20h call |

## 3. Start-up, detection, shutdown

### 3.1 `sound_init` 001C (far; AdvBIOS `DoMainInit`, 0000:008F)

1. `opn_select_delay` 1BEB: INT F1h AH=11h (CPU class, advbios.md §4.1) selects the I/O delay routine:
   class < 4 → 1BDE (one `jmp $+2`), class 4 → 1BD4 (six `jmp $+2`), class ≥ 5 → 1BE1 (six `out 5Fh,al`,
   0.6 µs each on such machines) (**code**; the emulation answers class 3).
2. `usd_install_once` with AL = 1: if INT F4h does not already point at a `"USDdrv"` signature, run
   `apiF4_80_Install` and then **hook INT F4h in any case** (AL ≠ 0 forces the hook; only AL = 0 would
   skip it when no chip answers). Verified by emulating an empty port 188h: the vector is installed,
   AH=21h returns 0, load/play return without touching anything.
   `apiF4_80_Install` 03AF stores CX:SI and DX:DI as the default voice-table pointers (D:507A–5080; the
   caller sets none of them, so they are whatever the registers held — they only matter if a track
   loads a voice of a kind for which its file has no block, which no NOVA file does), clears the
   joystick word, calls `opn_init`, then `usdtrap_install`, and sets `usd_present`.
3. `usd_volume_full`, then the built-in sequence at 004C is started like a song (§3.3).
4. Wait 60 vertical syncs by polling port 60h bit 5 (≈ 1.06 s at 56.4 Hz) — the sequence runs meanwhile.
5. `usd_stop` (everything off, volume full).

### 3.2 `opn_init` 05BA (far)

With interrupts disabled:

1. **Detection.** `out 188h,07h; out 18Ah,BFh` (direct port writes, two `jmp $+2` between), then
   `out 188h,07h; in 18Ah`: anything but BFh → no chip, return 0. (So register 07h = BFh — all tone and
   noise off, port A input, port B output — is the first thing written.)
2. Read register 0Eh (I/O port A). **Bit 7 set → vector 14h (IRQ 12, the board's "INT5" setting), mask bit
   10h; bit 7 clear → vector 15h (IRQ 13, "INT6"), mask bit 20h.** No other board setting is supported.
3. Save the old vector to 057C and point it at `opn_irq` 0328:0720.
4. Read register 2Dh (the read is irrelevant; *addressing* 2Dh selects the chip's default prescaler:
   FM fM/6, SSG fM/4 — **inferred** from the YM2203 manual).
5. `28h ← 00h, 01h, 02h` (key off FM 1–3); `24h ← F7h`, `25h ← 01h` (timer A = 3DDh: 0.631 ms);
   `26h ← DFh` (timer B: 9.519 ms); `27h ← 30h` (stop, clear flags) then `27h ← 0Fh` (start both timers,
   both interrupt enables; bits 6–7 = 0: FM channel 3 in normal mode — the driver never uses the CH3
   special mode).
6. Save the slave PIC mask (port 0Ah) and clear the board's bit in it.
7. `[057A] ← 1`; `seq_reset_channels` 0CE2; `seq_set_fade(0, 0, 0)`.

`seq_reset_channels` clears the "active" byte of all six work areas and stores the channel number (0–2
within FM / within SSG) at `[02]`. It also *tries* to give the SSG channels a default mixer mask of
24h / 12h / 09h (tone + noise of channel 3 / 2 / 1), but the value is kept in DL, which the `mul` inside
`seq_channel_ptr` zeroes before first use — **all three get 0**. Consequence: an SSG track that plays a
note before loading a voice enables nothing in the mixer and stays silent (verified with a synthetic
song; every NOVA track loads a voice first).

`usdtrap_install` 04E9 then finds the vector (14h or 15h) whose segment is 0328 and re-points it to the
stub at 0557 (`jmp far cs:[0560]` → `opn_irq`), remembering the number in 0564. Functionally the stub is
only a signature in front of the handler.

Register writes of a complete start-up, as recorded by `usdemu.py` (times in ms after `opn_init`):

```
0.000  07=BF  28=00 28=01 28=02  24=F7 25=01  26=DF  27=30 27=0F
0.631  27=1F  28=00                tick 1 of the init sequence: rest → key off FM1
1.262  24=47 25=03  27=1F          tick 2: tempo word 0347 reaches the chip
1.893, 15.18, 28.47 …  27=1F       timer-A acknowledges (13.287 ms apart from the third on)
9.519, 19.04 …         27=2F       timer-B acknowledges
134.8  27=1F  28=00                tick 13: end of the sequence → key off FM1
```

### 3.3 The built-in init sequence 004C

A one-track `.USO` image: owner 1, 1 track (channel 0 = FM1, priority 10), 1 FM voice block holding one
all-zero voice except volume mask 08h, track data `FE 00  FB 47 03  80  FF` = transpose 0, **tempo word
0347h**, a 12-tick rest, end. The voice is never loaded. Its effect is therefore: FM1 keyed off twice and
**timer A left at 0347h = 13.287 ms per tick**, which is the tempo in force until the first song sets its
own (every NOVA file does so in its first row).

### 3.4 Shutdown

AdvBIOS `DeinitAll` calls INT F4h AH=02h and later `sound_deinit` 00A5 → `usd_remove` 0090: if INT F4h is
ours, AH=02h (stop), AH=81h (`usdtrap_remove` 052F restores the stub's vector; `opn_shutdown` 06AE:
restore the saved vector, `07h ← BFh`, `27h ← 30h`, key off ×3, mask the board's IRQ again), then
`usd_unhook_f4` restores INT F4h (**code**).

## 4. Hardware access

### 4.1 Register write `opn_write_reg` 1BB5 (AL = register, AH = value)

```
wait until (in 188h) bit 7 = 0          ; busy flag, no time-out
out 188h, register
delay; delay                            ; routine selected in §3.1
wait until (in 188h) bit 7 = 0
out 18Ah, value
delay
```

`opn_read_reg` 1B9B: wait, `out 188h`, delay ×2, `in 18Ah`. `ReadFM` 1BB0: `in 188h` (status). The
routines do not disable interrupts themselves; every caller outside the interrupt handler brackets its
work with `pushf / cli … popf`, and the handler runs with its own IRQ masked, so a register access is
never interrupted by another one (**code**). On a real machine one write costs roughly 20–40 µs; a busy
interrupt (three voice loads = 87 writes) therefore takes a few milliseconds (**inferred**; irrelevant to
a re-implementation, the emulation treats the handler as instantaneous).

### 4.2 Timers and real-time rates

| timer | register value | period | use |
|---|---|---|---|
| A | NA = 10 bits: reg 24h = NA >> 2, reg 25h = NA & 3 | 72·(1024 − NA) clocks = (1024 − NA) × 18.029 µs | **tick** (note clock) |
| B | NB = reg 26h = DFh, never changed | 1152·(256 − NB) = 38 016 clocks = **9.5192 ms (105.05 Hz)** | effect clock |

**Tempo.** The byte-code command `FB lo hi` (usd-sequencer.md §6) stores the word `hi:lo | 8000h` in 0574.
At the *next* interrupt `opn_timer_ack` writes **reg 24h ← lo** and **reg 25h ← hi & 3**. Hence

```
NA   = 4·lo + (hi & 3)
tick = 72·(1024 − NA) / 3 993 600 s
```

(The word is *not* NA: its low byte is the chip's high part.) A whole note = 192 ticks, so a quarter note
at word w lasts 48 ticks: 0262h → NA 394 → 11.358 ms/tick → 110.05 bpm. The tempo words of NOVA's files
are 0184 0208 0227 023F 0254 0262 0276 028C 02A2 0352 035F 036F 0380 039F (tick 8.92 … 17.85 ms); they
fit NA = round(1024 − 69 337 / bpm) for whole bpm values (**inferred**: how the compiler chose them).

**Latency of a tempo change.** The chip loads a timer from its register only when the timer overflows.
A tempo command executed in tick n is written to the chip in the interrupt of tick n+1 — after that
overflow has already re-loaded the old value — so the intervals n→n+1 and n+1→n+2 still have the old
length; the new length applies from the interval n+2→n+3 on. For a song this means: **the first tick comes
0…1 old periods after the start call, the second one old period later, and only from the third tick on the
song's own tempo applies** ("old" = the previous song's tempo, or 13.287 ms after start-up).

Only tracks whose *owner* has bit 0 set (music; usd-sequencer.md §2.1) can change timer A. A tempo
command of any other track goes to 0576, which nothing reads: effects clocked by timer B always run at
105.05 ticks/s.

Both timers are started together in `opn_init` and never stopped or re-synchronised, so the phase of
the tick clock against the effect clock, and of both against a "play" call, is arbitrary.

### 4.3 Interrupt handler `opn_irq` 0720

```
push everything; DS = ES = 0328
mask the board's IRQ in the slave PIC (port 0Ah |= [0579])
pushf; call far [057C]            ; the previous handler — the driver sends no EOI itself;
                                  ; it relies on the chained default handler to do so (inferred)
sti
[0570]++
flags = opn_timer_ack()           ; below
[0581] = flags
seq_tick()                        ; usd-sequencer.md §4
cli; [0570] = 0
unmask the board's IRQ; pop; iret
```

`opn_timer_ack` 0768:

```
if [0574] & 8000h:  [0574] &= 03FFh;  reg 24h ← low byte;  reg 25h ← high byte
seen = 0
loop:  s = (in 188h) & 3                      ; bit 0 = timer A flag, bit 1 = timer B flag
       if s == 0: return seen
       seen |= s
       reg 27h ← (s << 4) | [0573]            ; 1Fh, 2Fh or 3Fh: clear exactly the flags seen
```

So per interrupt the chip sees: (new timer-A value, if requested), `27h ← 1F/2F/3F`, then whatever the
sequencer writes. If both timers overflow before the handler reads the status, one interrupt serves both
(flags = 3): the note clock is processed first, then the effect clock.

Because the handler re-enables interrupts while its own line is masked, a slow handler delays its next
invocation but never nests; a timer flag raised meanwhile produces a new interrupt as soon as the line is
unmasked (**inferred** from the 8259 and OPN behaviour).

## 5. INT F4h

Entry 011D → dispatcher 0130: `sti`, save BP ES DS DI SI DX CX, then with f = AH: table index =
(f & 7) + 0 / 8 / 16 / 24 for f < 10h / < 20h / < 30h / ≥ 30h (so AH = 80h–87h are the "internal" entries).
On return the function's carry is copied into the caller's flags; **AX and BX are returned as the
function left them**, the other registers are preserved. Unused slots are a bare `ret`.

State involved: *loaded* (D:5000), *enable* mask (012E), master volume M (0B65), fade (period P 0B69,
countdown 0B6B, step S 0B67, threshold 0B63), the six channels.

| AH | entry | in | effect | NOVA |
|---|---|---|---|---|
| 00 | 01E0 | DS:BX = file name | `usd_stop(0)` (below), then read the file to D:0000 with INT F2h AH=00h (no size check; 3000h bytes are reserved, NOVA's largest file is 3620 bytes). Success: loaded ← 1, CF = 0. Failure: CF = 1, loaded unchanged. **Does not start anything.** | `sound "file"` (after AH=02h) |
| 01 | 0216 | – | if enable bit 0: M ← 0 and any fade cancelled; if loaded: **start** the song from its beginning (§5.1), else CF = 1. Enable bit 0 clear: nothing, CF = 0 | `sound 1` |
| 02 | 0277 | – | `usd_stop(0)`: every active channel ended (§5.2), then M ← 0, fade cancelled | `sound 0` |
| 03 | 027D | – | **fade out**: M ← 0 at once (fade cancelled), then fade P = 7, S = −1, threshold 0. No register of the caller is read: the speed is fixed (the interpreter's speed argument is ignored) | `sound 2` |
| 04 | 028E | – | **fade in**: if enable bit 0: M ← −64, start the song (as AH=01h, result ignored), then fade P = 7, S = +1, threshold 0 | `sound 3` |
| 05 | 0427 | BX = P, CX = S, DX = threshold | `seq_set_fade` (§6): P ≠ 0 → start a fade; P = 0 → M ← CX | – |
| 06 | 01B7 | AL, CX | AL = 0: enable ← CX & 3, AX ← old mask; if the new mask has bit 0 clear, `usd_stop(0)`. AL ≠ 0: AX ← mask | – |
| 07 | 0236 | CX = volume offset | if enable bit 0: fade cancelled, **M ← CX** (0 = full … −64; not range-checked), then start the song if loaded (else CF = 1) | `sound 1 m` (the form exists in the interpreter; no NOVA script uses it) |
| 10 | 01FB | DS:BX = file name | `usd_stop(0)`, read an effect bank to D:3000, bank-loaded ← 1 (§7) | – |
| 11 | 025A | BX = index | start entry BX of the bank (§7) | – |
| 20 | 0445 | – | joysticks through the OPN's I/O ports → AX, BX (advbios.md §9.5; **code**). Uses `opn_reg_access` (writes register 0Fh, reads 0Eh) | – |
| 21 | 04C9 | – | AL ← `usd_present` (FFh / 0) | – |
| 80 | 03AF | CX:SI, DX:DI | install the core (§3.1); CF = 1 if no chip | start-up |
| 81 | 03ED | – | remove the core (§3.4) | shutdown |
| 82 | 02F5 | DS:SI = song image | bind and start as music (track table D:5002) | internal |
| 83 | 02DD | DS:SI = bank, BX = index | start a bank entry (track table D:503E) | internal |
| 84 | 0408 | DX = limit | `usd_stop(DX)`: 0 = everything, else only channels whose priority ≤ DX; then M ← 0, fade cancelled | internal |
| 85 | 0427 | as 05 | same routine | internal |
| 86 | 04CE | CX = mode, BX | raw chip access `opn_reg_access` 0B73: mode 0: mixer shadow ← (shadow AND BL) OR BH → reg 07h; mode 1: reg BL ← BH; mode 2: AL ← reg BL (**code**) | internal |

How the scripts map to these calls (interpreter.md §8, mes-format.md opcode D0): `sound "file"` =
AH=02h + AH=00h; `sound 1` = AH=01h; `sound 2` = AH=03h; `sound 3` = AH=04h; `sound 0` (and any other
number) = AH=02h. Use in the 119 scripts: `sound "…"` 159×, `sound 1` 143×, `sound 0` 138×, `sound 2`
106×, `sound 3` 16×; `sound 1 m` (AH=07h) never.

### 5.1 Starting a song: `usd_bind_and_start` 02FE → `seq_start` 0BD1

Binding (file layout: usd-sequencer.md §2): refuse (CF = 1) if the track count is 0 or > 6. Copy the 10-byte
track records to the track table (music D:5002). Walk the K blocks: a block of type 0 becomes the FM voice
table, any other type the SSG voice table (the last block of a kind wins; a missing kind leaves the
install-time default pointer). In each copied record the data offset is made absolute and the far pointer
of the matching voice table (FM for channel bytes 0–2, SSG otherwise) is stored. The file itself is not
modified. Then `seq_start(owner = file word 0, count, table)`:

1. *Priority check* — for every record with priority p ≠ 0: if its channel is active and p is **lower**
   than the priority of what plays there, the whole start is abandoned (nothing changes; the service
   still returns CF = 0). Priority 0 never loses. (All NOVA tracks have priority 0.)
2. *Silence* — for every record, in file order: if its channel is active, end it exactly like an
   end-of-track command (§5.2). Channels the new song does not use keep playing their old track.
3. *Bind* — for every record: channel number, priority, data pointer, voice-table pointer; **length
   counter ← 1** (so the first row is executed at the next tick); all flags cleared (key state,
   portamento, tie, LFO enables); detune ← 0; loop counters 0–3 ← 0; active ← owner (low byte).

**Not reset by a start:** transpose, volume, gate mode, portamento step, current pitch, the copy of the
last voice loaded, LFO and envelope state. A track that omitted one of these commands would inherit the
value from the previous song on its channel (verified in the "chain" scenario; NOVA's tracks set
transpose, volume, gate mode and voice before their first note).

The start writes no register unless a channel had to be silenced. The first row of every track is
executed in the first timer-A interrupt after the call.

### 5.2 Stopping: `usd_stop` 0408 → `seq_stop` 0CA0

For channel 5 down to 0 (SSG3, SSG2, SSG1, FM3, FM2, FM1), each *active* one (with DX ≠ 0: only if its
priority ≤ DL) is ended by pointing its track at the bytes `FF FF` and running the row interpreter once,
i.e. by the end-of-track command:

* FM: `28h ← channel` (key off), then the level routine with volume −1024: **TL ← 7Fh on every slot
  selected by the voice's volume mask** (so the release tail is cut; slots outside the mask are left).
* SSG: mixer register `07h ← shadow | voice mask` (tone/noise off), `08h+n ← 0`.
* flags ← 0, active ← 0, portamento target ← 0.

Then M ← 0 and the fade is cancelled. Register log of `sound 0` two seconds into NV01 (SSG3, SSG2, SSG1,
FM3 with a one-slot volume mask, FM2 and FM1 with two-slot masks):

```
07=B5 0A=00   07=B7 09=00   07=BF 08=00   28=02 4E=7F   28=01 49=7F 4D=7F   28=00 48=7F 4C=7F
```

Nothing is written for channels that are already idle, so a second stop is silent.

## 6. Master volume and fades (`seq_set_fade` 0D96, fade step in `seq_tick` 0F2E)

`seq_set_fade(P, S, T)`:

```
period = countdown = P
if P != 0:  step = S;  threshold = T (low byte)       ; M unchanged
else:       M = S                                       ; step and threshold unchanged
```

Once per **effect tick** (timer B), after all channel work:

```
if period != 0:
    if --countdown == 0:
        countdown = period
        if   step > 0:  M += step;  if M >= 0:   M = 0;   period = 0
        elif step < 0:  M += step;  if M <= -64: M = -64; period = 0
        else:           period = 0
```

So the service fades take 64 steps × 7 effect ticks = 448 × 9.519 ms = **4.26 s** (the first step comes
with the 7th effect tick after the call).

How M reaches the chip (usd-sequencer.md §8.3, §8.2) — only for channels whose priority ≥ threshold:

* **FM**: TL of the masked slots = clamp(voice TL − (volume + M), 0, 127), i.e. 0.75 dB per step, −48 dB at
  −64. **It is only written when the channel starts a note or its volume LFO steps** — a note already
  sounding keeps its level during a fade; the fade is heard note by note.
* **SSG**: the 4-bit volume = clamp((envelope + volume + volume LFO + **2·M**) >> 4, 0, 15), rewritten
  every effect tick, so SSG follows the fade smoothly: −8 volume steps at −64, which leaves only the top
  of a loud SSG envelope faintly audible.

A fade never stops the sequencer and does not reset anything when it ends. AH=03h jumps to full volume
before fading out (audible if it is called during a fade-in), AH=04h restarts the song.

## 7. Effect bank (AH=10h / 11h) — present, unused by NOVA

**verified** with synthetic banks in the emulation (`usdmodel.py --check`, scenario *synthetic*); no file
on NOVA's disks has this layout (with `NVSE01.USO` loaded as a bank AH=11h returns CF = 1, nothing plays).

Bank file, loaded to D:3000 (2000h bytes reserved, no size check):

| offset | size | meaning |
|---|---|---|
| 0 | word | number of entries N |
| 2 | N words | offset of entry i, **relative to offset 2** (the start of this table) |
| … | | entries: each a complete song image in `.USO` layout (header, track records, voice blocks, data) |

AH=11h, BX = i: if enable bit 1 is clear: return (CF = 0, nothing done); no bank loaded or i ≥ N: CF = 1;
else bind entry i with the *effect* track table D:503E and `seq_start` it (CF = 1 only if its track count
is 0 or > 6).

What makes an entry an "effect" is only its content:

* **Owner word (file word 0).** Its low byte becomes the channel's *active* byte, and a channel is
  clocked when `active AND timer flags ≠ 0`: **bit 0 = advance on timer A (music tempo), bit 1 = advance
  on timer B (fixed 105.05 ticks/s)**; 3 = on every interrupt. Music files have 1. An effect would use 2:
  constant speed whatever the music's tempo, and its tempo commands are ignored (§4.2).
* **Priority (track record byte 1).** An effect track with priority p > 0 takes its channel from the
  music (priority 0), cannot be displaced by a later effect of lower priority, and *is* displaced by any
  later start with priority 0 or ≥ p — in particular by a music restart. The displaced music track is
  ended, not suspended: it stays silent until the song is started again.
* `usd_stop(n)` (AH=84h) ends only channels with priority ≤ n, and a fade with threshold T (AH=05h)
  leaves channels with priority < T alone — the hooks for "stop/fade the music, keep the effects".

An engine for NOVA does not need any of this.

## 8. What else touches the chip

* Nothing in AdvBIOS writes to ports 188h/18Ah outside segment 0328 (**code**: port scan of the image).
  The text beep (INT F1h AH=04h–06h) is the system beeper (port 37h and PIT counter 1), not the OPN.
* INT F4h AH=20h (joystick) writes register 0Fh and reads 0Eh between interrupts, under `cli`. No caller
  in NOVA.
* `.TCM` plug-ins and `NV.OVL` call only INT F4h (interpreter.md §8).

## 9. Notes for a re-implementation

1. Two independent clocks are needed: ticks of 72·(1024 − NA)/3 993 600 s (NA from the tempo word, §4.2)
   and effect ticks of exactly 38 016/3 993 600 s. Process, per effect tick: portamento, pitch LFO, volume
   LFO, noise LFO, SSG envelope for every active channel, then the fade. When both fall on the same
   instant do the note tick first.
2. Tempo changes take effect two ticks late (§4.2); the first two ticks of a song run at the previous
   tempo. For NOVA this only shifts the start of a song by a few milliseconds; a port may apply the
   tempo at once, but then it will not match the reference logs clock for clock.
3. Phase: the reference recordings start the song wherever the free-running timers happen to be
   (`usdemu.py` start-up leaves 1.48 ms to the next tick and 2.76 ms to the next effect tick). Any phase
   is legitimate; `usdmodel.Model(phase=…)` reproduces a given one.
4. `sound 2` (fade-out) must leave the song running at −64; `sound 0` silences it (§5.2). Scripts issue
   `sound 2`, wait, `sound 0` — and the usual wait is `delay 100` (2 s) or `delay 50` (1 s), shorter than
   the 4.26 s the fade needs: most fade-outs in the game are cut off by the stop at about −30 or −15
   (from the script listings; the delay unit is AdvBIOS's 20 ms tick, advbios.md §7).
5. FM levels during a fade change only at note starts (§6). Reproduce this — a smooth fade sounds
   different on held notes.
6. Channels keep transpose / volume / gate / voice across songs (§5.1). NOVA's data does not depend on
   it, a faithful port keeps the state anyway.
7. Loading (`AH=00h`) stops the music immediately; the script-level `sound "file"` therefore cuts the old
   song at once and the new one starts with the following `sound 1`/`sound 3`.
8. No chip: every call succeeds and does nothing (§3.1) — the game runs silently.

## 10. Emulation harness and verification

`re-tools/usdemu.py` loads `NV.OV1` at segment 1000h (71 relocations applied) in unicorn and calls the
driver's own `sound_init`, with:

* a fake YM2203: address/status at 188h (busy never set, bits 0/1 = timer flags), data at 18Ah; register
  0Eh reads FFh (bit 7 set → vector 14h; joystick idle); timers simulated in master clocks from registers
  24h–27h, a new value taking effect at the next overflow; the interrupt handler is called at each
  overflow whose enable bit is set while the board's bit in the slave PIC mask (port 0Ah) is clear;
* INT F1h AH=11h answered with 3; INT F2h AH=00h answered from `MUS/`; the chained old interrupt
  handler is an `iret`; port 60h delivers a 56.42 Hz VSYNC flag and advances time (≈10 µs per poll) so
  that the 60-frame wait of `sound_init` elapses while timer interrupts are delivered;
* INT F4h issued through the vector the driver installed, exactly like the interpreter.

It records `(clock, kind, interrupt number, tick number, register, value)` for every data-port write and
writes VGM 1.51 (YM2203 at 3 993 600 Hz) with a loop point for looping songs (intro + N passes, loop =
last pass) and a TSV log. `--all` renders the 28 files to `resources/derived/music/vgm/`.

`re-tools/usdmodel.py` is an independent implementation written from this document and
usd-sequencer.md. `--check` drives both with the same calls and compares the complete write streams
(clock, register, value):

| scenario | what | result |
|---|---|---|
| play | all 28 files: `sound "file"`, `sound 1`; intro + 3 loop passes (≤ 420 s; free-running effect files 120 s; ending files to the end + 0.5 s) | 28 × identical, 2 455 485 writes |
| fade | all 28 files: fade-in, fade-out, fade-in during the fade-out, fade-out to the end, stop, restart at offset −20 and −64, raw fades (+2 per 3 effect ticks, −5 per tick), restart over the playing song, stop | 28 × identical, 782 302 writes |
| chain | 56 starts on one driver instance without resetting anything (state inherited between songs, restarts over active channels, fade-in starts) | identical, 233 187 writes |
| phase | 4 files × 4 phases of the two timers at the start call, one with both timers overflowing together | 16 × identical, 589 099 writes |
| synthetic | generated songs (our own data) using every command incl. `F4`, all gate modes, all four shapes of all five LFOs, odd parameter values (zero speeds/counts, TL ≥ 80h, empty mixer masks, clamped notes, tracks without transpose or voice), track priorities, owners 1/2/3, effect banks started over music, `usd_stop(n)`, fades with a threshold | 400 songs (default seed) identical, 1 684 614 writes; seeds 1, 2, 3 × 600 songs identical (7.2 M writes) |

Total of the default run (`usdmodel.py --check`, about two minutes): **5 744 687 register writes compared,
none different.** The first complete run of the model against the files was already identical; the
synthetic songs then exposed one error of this document's first draft (the default SSG mixer mask, §3.2).

Sensitivity of the comparison was checked by breaking single details of the model (gate formulas, LFO
shapes, signedness of TL, unsigned portamento compare, stop order, state kept across starts, …): see
usd-sequencer.md §12.

Not covered by emulation (read in the code only): joystick service, AH=86h, the delay routines, removal
(§3.4), the behaviour of real hardware timing inside one interrupt.

## 11. Corrections to advbios.md (for the coordinator)

1. §4.6 / §9.2: INT F4h **is installed even when no YM2203 answers** (`usd_install_once` is called with
   AL = 1, which forces the hook; verified by emulation). All services then return without effect and
   AH=21h returns 0 — so open question 3 ("what NV.OVL does when INT F4h is not installed") does not arise.
2. §9.2: the delay for CPU class 4 is six `jmp $+2` (1BD4 falls through into 1BDE), not five.
3. §4.6 AH=11h: with the effect bit of the enable mask clear the call returns CF = 0 (nothing done), not
   CF = 1. Same for AH=01h/04h/07h with the music bit clear.
4. §9.3: confirmed — timer A = note clock, timer B = effect clock; the tempo word maps to the chip as
   reg 24h = low byte, reg 25h = high byte (the init value 01F7h is NA = 3DDh, as §9.3 computed).
5. §9.4: the voice blocks are confirmed as 39-byte FM voices (type 0) and 30-byte SSG voices (type 3);
   file word 0 is the owner/clock mask (§7), which is why it is 1 in every music file.
6. §9.4 sound effects / §11.2: NOVA plays `NVSE*.USO` through AH=00h/01h (they are complete songs with
   owner 1); nothing on the disks has the bank layout.

## 12. Open questions

1. Who sends the EOI for the board's interrupt: the driver chains to the previous vector and sends none
   itself. On a real PC-98 the default handler of an unused IRQ does; not traced in the BIOS.
2. Real-hardware duration of a busy interrupt and whether it ever delays the next tick audibly (a
   three-voice row is 87+ register writes with busy-waits). Emulation treats handlers as instantaneous.
3. The I/O delay classes (`out 5Fh` count on 486+) were not checked against the chip's timing
   requirements.
4. The compiler that produced `.USO` files (and its MML dialect) is unknown; command names in
   usd-sequencer.md are ours.
