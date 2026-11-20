# USDtrap V01.02 — the `.USO` song format and the sequencer

How NOVA's music driver turns a `.USO` file into YM2203 register writes, precisely enough to re-implement
it and to check the result register for register. The driver around it (start-up, interrupt, timers,
INT F4h, fades, effect bank) is in [usd-driver.md](usd-driver.md).

Conventions: addresses are offsets in segment 0328 of `NV.OV1` (load base 0). `[xx]` = byte/word at offset
xx of the current channel's work area (register BX in the code). All arithmetic is 16-bit two's complement
unless a width is given. *Tick* = one timer-A interrupt (note clock); *effect tick* = one timer-B
interrupt (9.519 ms). **verified** = read in the code *and* reproduced by the clean-room model
`re-tools/usdmodel.py` against the original code under `re-tools/usdemu.py`, write for write
(usd-driver.md §10); *(synthetic)* marks behaviour that no NOVA file exercises and that was verified with
generated test songs only; **code** = read only; **inferred** = interpretation.
**Unless marked otherwise everything below is verified.**

Command and field names are ours (the compiler and its MML are unknown). Dump tool:
`re-tools/usoinfo.py FILE.USO` (structure, voices, disassembly, loop lengths; `--check`, `--tsv`,
`--stats`).

## 1. Key facts

1. A file holds 1–6 **tracks**, each bound to one chip channel (0–2 = FM 1–3, 3–5 = SSG 1–3), an FM voice
   table (39-byte records) and an SSG voice table (30-byte records), and the tracks' byte code.
2. Byte code: bytes below B0h are notes/rests with a table length, B0h–BFh notes/rests with an explicit
   length, C0h–FFh commands (13 defined, the rest no-ops). A note byte's low nibble (1–15) is added to the
   track's *transpose* to give the note number; 0 is a rest. There is no octave command.
3. Length unit = tick; whole note = 192. Each track has a 16-bit down-counter; when it expires the track's
   next *row* (commands up to and including one note or rest) is executed.
4. Note-off is decided by the **gate mode** (0 = hold to the end, 1–7 = sound for n/8 of the length) and
   the **tie** / **portamento** flags (no release at all).
5. FM volume: TL of the slots named by the voice's *volume mask* = voice TL − (track volume + master
   volume), clamped to 0..127. Track volumes are ≤ 0 in NOVA (−3 … −127): they are attenuations in
   0.75 dB steps.
6. SSG volume: a software envelope (attack / decay / sustain / release on a 0..255 scale) stepped every
   effect tick; register value = (envelope + volume + LFO + 2·master) / 16, clamped to 0..15. The chip's
   hardware envelope is never used.
7. Five software LFOs (FM pitch, FM volume, SSG pitch, SSG volume, SSG noise period), parameters in the
   voice record, four shapes, all stepped on the effect clock. Portamento also runs on the effect clock.
8. Tracks loop independently with a jump command; there is no song-level loop point and no "song
   finished" signal. A track ends with FFh, which silences its channel.
9. Pitch is kept as a linear 16-bit *pitch value*: FM 618 units per octave (F-number = 618 + value mod 618,
   block = value div 618), SSG the tone period itself. Detune, LFO depth and portamento speed are in
   these units.

## 2. File layout

All words little-endian. Checked on all 28 files (`usoinfo.py --check`: 27 584 bytes, every byte accounted
for, every jump lands on an instruction of its own track).

| offset | size | meaning |
|---|---|---|
| 0 | word | **owner / clock mask** (§2.1): 1 in every NOVA file |
| 2 | word | number of tracks T, 1..6 (0 or > 6: the driver refuses the file). 6 in all files except NV15 (5) and NVSE02 (1) |
| 4 | word | number of voice blocks K (2; 1 in NVSE02, NVSE07, NVSE11) |
| 6 | 10·T | track records |
| 6 + 10·T | K blocks | voice blocks |
| after the blocks | word | length of the track data that follows (= file size − *base* in every file; not read by the driver) |
| *base* | … | track data |

Track record (10 bytes):

| offset | size | meaning |
|---|---|---|
| 0 | byte | channel: 0, 1, 2 = FM 1–3; 3, 4, 5 = SSG 1–3. Each channel at most once; the order of the records is free (e.g. NV11: SSG1 SSG2 SSG3 FM1 FM2 FM3) and has no effect other than the order in which channels are silenced at a start |
| 1 | byte | priority (0 in all NOVA files; usd-driver.md §5.1, §7) |
| 2 | word | start of the track's byte code, relative to *base* |
| 4 | 6 | filled in at load time (data segment, far pointer to the voice table); the files hold leftovers of the compiler's memory here |

Voice block: word type, word length L, L bytes. Type 0 = FM voice table, L = 39·n; any other type (3 in
the files) = SSG voice table, L = 30·n. The driver does not use L except to find the next block; a voice
number is not range-checked. If two blocks of one kind were present the later would win (**code**).
A file may lack a kind: NVSE02 has no FM block (and no FM track); NVSE07 and NVSE11 have no SSG block
although they have SSG tracks — those tracks consist of a rest and `FF` and never load a voice.

The tracks of a file are stored one after another; every track's region ends with an `FF` byte, also
after a final unconditional jump (unreachable there).

### 2.1 Owner word

The low byte of file word 0 is copied to `[00]` of every channel the file starts; a channel is processed
in an interrupt if `[00] AND timer flags ≠ 0`, where flag bit 0 = timer A and bit 1 = timer B. So 1 =
"clocked by the tempo timer" (music), 2 = "clocked by the fixed 105.05 Hz timer", 3 = by both
*(synthetic)*. `[00] = 0` means the channel is idle. Only tracks with bit 0 set can change the tempo.

## 3. Channel work area

FM: 0956h + 57h·n, SSG: 0A5Bh + 58h·n (n = 0..2). The first 30h bytes are common.

| offset | size | name | meaning |
|---|---|---|---|
| 00 | byte | active | owner mask, 0 = idle |
| 01 | byte | flags | bit 0 **keyed** (note sounding), bit 1 **portamento** on, bit 2 pitch LFO enabled, bit 3 volume LFO enabled, bit 4 **tie** (also set when the gate has released the note), bit 5 noise LFO enabled (SSG) |
| 02 | byte | number | channel number 0–2 within its kind |
| 03 | byte | priority | |
| 04 | byte | note | last note number (nibble + transpose, before clamping); written, never read |
| 05 | byte | gate mode | operand of F8 |
| 06 | byte | transpose | operand of FE |
| 07 | byte | detune | signed, operand of FC |
| 08 | word | portamento step | |
| 0A | word | volume | signed (sign-extended operand of FD) |
| 0C | word | counter | ticks left of the current note/rest |
| 0E | word | gate threshold | the note is released when counter < threshold |
| 10 | word | pitch | current pitch value (FM) / tone period (SSG), detune included |
| 12 | word | target | portamento target; 0 = "none yet" |
| 14 | word | | start of the track data (written, never read) |
| 16, 18 | far ptr | position | next byte of the track |
| 1A, 1C | far ptr | voices | the track's voice table |
| 20–23 | 4 bytes | loop counters 0..3 | cleared at start. The index is not range-checked; 4.. would hit the LFO state (**code**) |
| 24, 25, 26, 27 | bytes | pitch LFO | phase (0 = not started, 1, 2), delay left, speed counter, count counter |
| 28 | word | | pitch LFO accumulator |
| 2A, 2B, 2C, 2D | bytes | volume LFO | phase, delay left, speed counter, count counter |
| 2E | word | | volume LFO accumulator (FM: a complete volume; SSG: an offset) |

FM only:

| offset | size | name | meaning |
|---|---|---|---|
| 30–56 | 39 | voice | copy of the voice record last loaded (§9.1): 30–47 the 24 register bytes (TL at 34–37), 48 FB/ALG, 49 volume mask, 4A key-on mask, 4B–50 pitch LFO parameters, 51–56 volume LFO parameters |

SSG only:

| offset | size | name | meaning |
|---|---|---|---|
| 30 | word | envelope state | 0 attack, 2 decay, 4 sustain, 6 release, 8 off |
| 32 | word | envelope level | 0..255 |
| 34, 35, 36, 37 | bytes | noise LFO | phase, delay left, speed counter, count counter |
| 38 | word | | noise LFO accumulator |
| 3A–57 | 30 | voice | copy of the voice record (§9.2); byte 3A (mixer mask) is shifted left by the channel number after the copy |

Global state used by the sequencer: mixer shadow 0572 (register 07h), pending tempo 0574, master volume
0B65, fade threshold 0B63 (usd-driver.md §2.1).

What a song start resets and what it does not: usd-driver.md §5.1.

## 4. The interrupt: `seq_tick` 0DDA

`flags` = timer flags of this interrupt (bit 0 A, bit 1 B). Register writes happen in exactly this order.

```
(timer acknowledge: pending tempo → reg 24h, 25h; reg 27h ← (flags << 4) | 0Fh)      usd-driver.md §4.3

for ch in FM1, FM2, FM3, SSG1, SSG2, SSG3:                 # note clock
    if (ch.active AND flags) == 0: continue
    ch.counter -= 1
    if ch.counter != 0:
        if ch.keyed and not ch.tie and not ch.portamento and ch.counter < ch.gate (unsigned):
            release(ch);  ch.keyed = false;  ch.tie = true     # gate
    else:
        if ch.keyed and not ch.tie and not ch.portamento:
            release(ch)                                        # end of the note
        ch.keyed = false;  ch.tie = false
        ch.counter = 1
        row(ch)                                                # §5: commands … one note or rest

if flags has bit 1:                                        # effect clock
    for ch in FM1, FM2, FM3, SSG1, SSG2, SSG3:
        if not ch.active: continue                             # any owner
        if ch.portamento:
            slide(ch)                                          # §8.4
            if not ch.pitch_lfo_enabled: write_pitch(ch, ch.pitch)      # every effect tick
        if ch.pitch_lfo_enabled:  step pitch LFO               # §10
        if ch.volume_lfo_enabled: step volume LFO
        if SSG:
            if ch.noise_lfo_enabled: step noise LFO
            envelope(ch)                                       # §8.2, always
    fade step                                                  # usd-driver.md §6
```

`release`: FM → `28h ← n` (key off). SSG → envelope state ← release (no register write).

Notes:

* The `tie = true` after a gate release only prevents a second release at the end of the note; because
  `keyed` is cleared too it has no other effect.
* With gate mode 0 the release of a note and the start of the next happen in the same interrupt
  (key off, …, key on: a re-trigger).
* A track whose counter is loaded with 0 (explicit length 0) waits 65 536 ticks (**code**).
* The effect part looks at `active ≠ 0`, not at the owner mask, and runs after the note part when one
  interrupt serves both timers.

## 5. A row: `fm_row` 16C8 / `ssg_row` 17D2

```
loop:
    b = next byte
    if b >= C0h:  execute command b (§6);  if it was FF: return;  continue
    if b >= B0h:  len = next byte;  if len & 80h: len = ((len & 7Fh) << 8) | next byte
    else:         len = LENGTHS[b >> 4]                      # b >> 4 = 0..10
    if b & 0Fh == 0:  rest(len)   else:  note(b & 0Fh, len)
    return
```

`LENGTHS` (07C0) = 192, 144, 96, 72, 48, 36, 24, 18, 12, 9, 6 — whole, dotted half, half, dotted quarter,
quarter, dotted 8th, 8th, dotted 16th, 16th, dotted 32nd, 32nd. Explicit lengths are 1..127 in one byte or
0..32767 in two (high byte first, bit 7 set as the marker).

**Rest** — `counter ← len`, `keyed ← false`, and unconditionally: FM `28h ← n`; SSG mixer `07h ← shadow |
voice mask` and `08h+n ← 0`. The SSG envelope state is *not* changed by a rest: it keeps running on the
effect clock (and keeps writing the volume register, see §8.2).

**Note** (`k` = low nibble 1..15):

```
N = (k + transpose) as signed byte;  [04] = N
FM:   N = clamp(N, 0, 95);     p = FM_PITCH[N]
SSG:  N = clamp(N, 12, 107);   p = SSG_PERIOD[N - 12]
counter = len
gate    = gate_threshold(gate mode, len)                    # §7.1
p += detune (signed byte)
if portamento:
    if target == 0: pitch = p                               # first note after enabling: no slide
    target = p
else:
    pitch = p
FM:                                                          SSG:
  A4h+n ← hi(pitch), A0h+n ← lo(pitch)        (§8.1)          2n ← pitch & FFh, 2n+1 ← pitch >> 8   (not clamped)
  if pitch LFO enabled:  restart it  (§10)                    if pitch / volume / noise LFO enabled: restart it
  if volume LFO enabled: restart it                           if keyed: key_off (cannot happen, see below)
  if keyed: 28h ← n      (cannot happen)                      volume-LFO accumulator ← 0
  set_level(volume)      (§8.3: TL of the masked slots)       envelope level ← 0, state ← attack
  28h ← (key-on mask & F0h) | n                               envelope()   (first attack step + 08h+n)
  keyed ← true                                                07h ← shadow ← (shadow | 09h << n) & ~voice mask
                                                              keyed ← true
```

("Cannot happen": the note clock always clears `keyed` before it calls `row`.)

Consequences worth knowing:

* An FM note-on always rewrites the TLs of the masked slots, so volume changes, the master volume and a
  finished volume-LFO excursion take effect at note starts.
* A tied or portamento FM note is *not* keyed off before the next key-on: the chip sees a key-on for a
  channel that is already on, which does not restart its envelopes — a slur. On SSG the envelope restarts
  from 0 at every note regardless (tie only suppresses the release phase before it).
* The SSG note-on first disables tone and noise of the channel and then enables what the voice mask
  names; with voice mask 0 (no voice loaded, usd-driver.md §3.2) the channel stays off *(synthetic)*.

## 6. Commands

`b` = unsigned byte, `s` = signed byte, `w` = word, `r` = signed word added to the address of the byte
*after* it. Dispatch: 19DE/19F0, `index = NOT b`, tables 195E (FM) and 199E (SSG) — the two tables are
identical except for FF. Count = occurrences in NOVA's 28 files (files using it).

| byte | operands | name | effect | count |
|---|---|---|---|---|
| 00–AF | – | note / rest, table length | §5 | 4532 notes (27), 165 rests (20) |
| B0–BF | `b` or `b b` | note / rest, explicit length | §5 | 2647 notes (25), 190 rests (25); 106 use the two-byte form, longest 888 |
| FF | – | **end** | FM: `28h ← n`, `set_level(−1024)` (TL 7Fh on the masked slots). SSG: `07h ← shadow OR voice mask`, `08h+n ← 0`. Then flags ← 0, active ← 0, target ← 0; the row ends. The channel stays silent until a new start | 162 (28) |
| FE | `b` | **transpose** | `[06] ← b`. Note number = nibble + this, so it selects the octave and the 15-semitone window | 1653 (28); values −6 … 92 |
| FD | `s` | **volume** | `[0A] ← s` (sign-extended). Heard from the next note-on (FM) / the next effect tick (SSG) | 1009 (28); −127 … −3 |
| FC | `s` | **detune** | `[07] ← s`, added to the pitch value of every following note | 86 (27); −52 … 31 |
| FB | `w` | **tempo** | if active bit 0: `[0574] ← w OR 8000h` → timer A at the next interrupt (usd-driver.md §4.2); else stored in 0576 (no effect) *(synthetic)* | 34 (28) |
| F8 | `b` | **gate** | `[05] ← b`; mode = (b >> 1) & 7 (§7.1). NOVA uses 0, 8, 10, 12, 14 | 199 (28) |
| F7 | – | **tie** | flag bit 4 ← 1: the note of this row is not released, neither by the gate nor at its end. Cleared when that note's length expires | 211 (16) |
| F6 | `b` | **portamento** | b ≠ 0: step ← b, target ← 0, flag on. b = 0: flag off | 97 (13); steps 2–20, 47× off |
| F5 | `r` | **jump** | position += r. The loop of a track: `F5` back to its loop start | 113 (21) |
| F4 | `b b r` | **loop exit** | counter index i, count c: if loopctr[i] = 0: loopctr[i] ← c, continue. Else decrement it; if it became 0: jump by r, else continue. (Placed inside a repeat it leaves the body on pass c+1.) *(synthetic)* | 0 |
| F3 | `b b r` | **repeat** | index i, count c: if loopctr[i] = 0: loopctr[i] ← c and jump by r. Else decrement it; if non-zero jump by r, else continue. With r pointing back the body is played **c + 1** times; c = 0 loops forever | 47 (12); index 0 (45×) and 1 (2×) |
| E1 | `b` | **FM voice** | load FM voice b (§9.1) | 538 (27) |
| E0 | `b` | **SSG voice** | load SSG voice b (§9.2) | 419 (26) |
| C0–DF, E2–F2, F9, FA | – | no-op | one byte, no operand *(synthetic)* | 0 |

Table-length index usage: 0:223 1:86 2:194 3:77 4:414 5:189 6:2060 7:6 8:1392 9:0 A:56.

Details:

* E1 on an SSG track or E0 on an FM track would copy the record into the wrong work area (the tables hold
  both handlers for both kinds); no file does this and the model rejects it (**code**).
* F3/F4 operate on a byte counter; a counter left non-zero by leaving a loop through F4 or F5 makes the
  next encounter decrement instead of initialise *(synthetic)*.
* Two skip stubs at 1A04 (`si += 2`) and 1A08 (`si += 4`) are not referenced by either table.
* Commands take no time; a track that loops without a note or rest would hang the interrupt (**code**).

## 7. Note timing

### 7.1 Gate (`gate_calc` 1917)

`gate_threshold(mode, len)`, mode = (operand >> 1) & 7, shifts are integer:

| operand | mode | threshold | the note sounds for |
|---|---|---|---|
| 0 | 0 | 0 | the whole length (released when the next row starts) |
| 2 | 1 | len − (len >> 3) | 1/8 *(synthetic)* |
| 4 | 2 | len − (len >> 2) | 2/8 *(synthetic)* |
| 6 | 3 | (len >> 1) + (len >> 3) | 3/8 *(synthetic)* |
| 8 | 4 | len >> 1 | 4/8 |
| 10 | 5 | (len >> 2) + (len >> 3) | 5/8 |
| 12 | 6 | len >> 2 | 6/8 |
| 14 | 7 | len >> 3 | 7/8 |

The note starts in the tick that reads it with counter = len. In each later tick the counter is
decremented first; the release happens in the first tick where 0 < counter < threshold. So the key-on to
key-off distance is **len − threshold + 1 ticks** (if that is less than len; otherwise the note is released
when its length expires). Example: len 24, operand 14: threshold 3, released 22 ticks after the key-on.
The threshold is computed at the note-on from the mode then in force.

### 7.2 Tie and portamento

Both flags suppress the gate release and the end-of-note release (§4). Tie applies to one note (F7 in
its row); portamento to every note while it is on. During a rest row a pending tie has no effect.

## 8. Sound generation

### 8.1 FM pitch (`FM_PITCH` 07D6, `pitch_to_fnum` 18DB)

```
FM_PITCH[N] = 618·(N div 12) + S[N mod 12],   S = 0 37 76 117 161 207 256 308 363 422 484 549
pitch value v (after detune / LFO / portamento), clamped (signed) to 0 .. 4943 (134Fh):
    block = v div 618;   fnum = 618 + v mod 618
    A4h+n ← (block << 3) | (fnum >> 8)        then        A0h+n ← fnum & FFh
```

The in-octave F-numbers are therefore 618 655 694 735 779 825 874 926 981 1040 1102 1167 (C … B). With
fM = 3.9936 MHz the output frequency is fnum·2^block·fM/(72·2^21) Hz: note number 57 (block 4, fnum 1040)
= 440.1 Hz, i.e. **note number = 12·octave + semitone, C0 = 0, A4 = 57** (**inferred** arithmetic; the
register values are verified). One pitch unit is 1/618 of an octave's F-number span (≈ 2.8 cents at C,
1.5 cents at B).

The pair is always written high part first, at every note-on and whenever portamento or the pitch LFO
produce a value — even an unchanged one.

### 8.2 SSG pitch, mixer and envelope

**Pitch.** `SSG_PERIOD` (0896, 96 words) for note numbers 12..107:

```
3816 3602 3400 3209 3029 2859 2698 2547 2404 2269 2142 2022      (12..23 = C1..B1)
1908 1801 1700 1604 1514 1429 1349 1273 1202 1135 1071 1011
 954  900  850  802  757  715  675  637  601  567  535  505
 477  450  425  401  379  357  337  318  301  284  268  253
 239  225  212  201  189  179  169  159  150  142  134  126
 119  113  106  100   95   89   84   80   75   71   67   63
  60   56   53   50   47   45   42   40   38   35   33   32
  30   28   27   25   24   22   21   20   19   18   17   16
```

All 96 values equal round(124 800 / f) with f = 440·2^((N−57)/12) — the chip's tone frequency being
fM/(32·period) (**inferred**). The same note numbers as FM, so both kinds are in tune with each other.
The note-on writes `pitch` unclamped (low byte to 2n, high byte to 2n+1); values produced by portamento
or the pitch LFO are clamped (signed) to 0..0FFFh first (`ssg_write_period` 145E). Detune, LFO and
portamento are in period units: positive = lower.

**Mixer** (`ssg_key_on` 10A1, `ssg_key_off` 10CD; shadow in 0572, initially BFh):

```
key on:   shadow = (shadow | (09h << n)) & ~mask;   07h ← shadow;   keyed ← true
key off:  shadow |= mask;   07h ← shadow;   keyed ← false;   08h+n ← 0
```

`mask` = voice byte 0 shifted left by n: bit 0 = tone, bit 3 = noise of the channel. Bits 6–7 of the
shadow (I/O port directions) never change. The noise period register 06h is shared by the three channels:
it is written when a voice with the noise bit is loaded and by the noise LFO.

**Envelope** (`ssg_envelope` 0FFD), one step per effect tick for every active SSG channel, plus one step
at the note-on itself. `v[i]` = byte i of the voice record:

```
attack:   level += v[4];   if level >= v[2]: level = v[2]; state = decay
decay:    level -= v[5];   if level <= v[3]: state = sustain            # level is not clamped to v[3]
sustain:  level -= v[6];   if level <= 0: level = 0; state = off; key_off()
release:  level -= v[7];   if level <= 0: level = 0; state = off; key_off()
off:      (level counts as 0)

out = level
if priority >= fade threshold: out += 2·master
out += volume + volume-LFO accumulator
08h+n ← clamp(out >> 4, 0, 15)                 # arithmetic shift; ≥ 16 → 15
```

Points that are easy to get wrong:

* The volume register is rewritten **every effect tick** while the channel is active — also in the *off*
  state, where it writes clamp((volume + LFO + 2·master) >> 4), i.e. 0 for NOVA's (negative) volumes.
* The release state is entered by the gate or at the end of the note (§4); *sustain* with rate 0 holds
  forever. A voice whose decay target is above its attack level (several NOVA voices: attack to 182,
  decay "to" 200) simply passes through decay in one step.
* A rest (or `FF`) forces the mixer off and the volume register to 0 but leaves the state machine alone;
  if the envelope was still above 0 it goes on stepping and writing its level to the (muted) channel
  until it reaches 0, where `key_off` is issued once more.
* `key_off` inside the envelope is followed by the normal volume write of that step.

### 8.3 FM level (`fm_set_level` 0FA6)

```
set_level(vol):
    if priority >= fade threshold: vol += master
    for slot i = 0..3 (registers 40h+n, 44h+n, 48h+n, 4Ch+n) with bit i of the volume mask set:
        reg ← clamp( (signed byte) voice TL[i] − vol, 0, 127 )
```

Called with the track volume at every note-on, with the LFO value when the volume LFO steps, and with
−1024 at the end of a track. Slots outside the mask keep the TL written by the voice load. The masks in
NOVA's 110 voices follow the algorithm: ALG 0–3 → 08h (slot 4), ALG 4 → 0Ch, ALG 5–6 → 0Eh; ALG 7 is not
used. Bit i ↔ register offset 4·i, i.e. operators 1, 3, 2, 4 in Yamaha's numbering.

### 8.4 Portamento (`porta_step` 0F7D)

Per effect tick while the flag is on, comparing `pitch` and `target` as **unsigned** words:

```
if   pitch > target:  pitch -= step;  if pitch < target: pitch = target
elif pitch < target:  pitch += step;  if pitch > target: pitch = target
```

then the pitch registers are rewritten (directly, or by the pitch LFO when that is enabled: it adds its
accumulator to the sliding `pitch`). The first note after `F6 b` sets `pitch` at once; later notes only set
`target`, and the slide continues across note boundaries without key-off. On SSG the value is a period,
so "up" is down in frequency. NOVA: FM steps 2–20 (40×), SSG (10×).

## 9. Voice records

### 9.1 FM voice (39 bytes) and `cmd_fm_voice` 1ABA

| offset | size | meaning |
|---|---|---|
| 0 | 4 | register 30h (DT/MUL) for slots at +0, +4, +8, +C (operators 1, 3, 2, 4) |
| 4 | 4 | register 40h (TL) — the base levels |
| 8 | 4 | register 50h (KS/AR) |
| 12 | 4 | register 60h (AM/DR) |
| 16 | 4 | register 70h (SR) |
| 20 | 4 | register 80h (SL/RR) |
| 24 | 1 | register B0h (FB/ALG) |
| 25 | 1 | volume mask: bit i = slot i takes the track volume (§8.3) |
| 26 | 1 | key-on mask: register 28h ← (this & F0h) \| n at a note-on. F0h in 107 voices, 70h in 2, C0h in 1 |
| 27 | 6 | pitch LFO: type, delay, speed, count, step (word) (§10) |
| 33 | 6 | volume LFO: same layout |

Loading (E1 b): clear the two LFO-enable flags, copy the record to `[30]`, then write
`30h+n+4·i ← byte i` for i = 0..23 (that is 30h, 34h, … 8Ch: all six register groups in file order),
`90h+n, 94h+n, 98h+n, 9Ch+n ← 0` (SSG-EG off), `B0h+n ← byte 24`; finally enable the pitch LFO if byte 27
≠ 0 and the volume LFO if byte 33 ≠ 0. 29 register writes. The TLs are written raw; the track volume is
applied by the next note-on. LFO *state* (phase, counters, accumulator) is not touched — it is restarted
by the next note-on; until then an LFO that was running continues with the new parameters.

### 9.2 SSG voice (30 bytes) and `cmd_ssg_voice` 1B29

| offset | size | meaning |
|---|---|---|
| 0 | 1 | mixer mask: bit 0 tone, bit 3 noise (NOVA: 01h 39×, 08h 14×, 09h 4×) |
| 1 | 1 | noise period (register 06h), base for the noise LFO |
| 2 | 1 | attack level (peak) |
| 3 | 1 | decay level |
| 4 | 1 | attack rate (FFh = immediately at the peak) |
| 5 | 1 | decay rate |
| 6 | 1 | sustain rate |
| 7 | 1 | release rate |
| 8 | 4 | not read by the driver (0 in all NOVA voices) |
| 12 | 6 | pitch LFO: type, delay, speed, count, step (word) |
| 18 | 6 | volume LFO |
| 24 | 6 | noise LFO |

Loading (E0 b): clear the three LFO-enable flags, copy the record to `[3A]`; if the mask has the noise bit:
`06h ← byte 1`, and enable the noise LFO if byte 24 ≠ 0; enable the pitch LFO if byte 12 ≠ 0 and the
volume LFO if byte 18 ≠ 0; shift `[3A]` left by n. No other register is written; mixer and volume change
at the next note-on. Envelope state and level are not touched.

## 10. The LFOs

Five instances share one scheme (FM pitch 10FB, FM volume 1232, SSG pitch 1346, SSG volume 148F, SSG
noise 1595). Parameters: **type** (0 = off; otherwise bits 1–2 select the shape — the files use 80h, 82h,
84h, 86h), **delay**, **speed**, **count** (bytes), **step** (signed word). State: phase (0 = not started),
delay left, speed counter, count counter, accumulator `acc`.

*Restart*: at every note-on of the channel, if the LFO is enabled then: phase ← 0, delay left ← delay.
Rests do not restart it, and it keeps running through rests and after a release.

*Step*, once per effect tick while enabled (byte counters wrap, so a speed or count of 0 means 256):

```
if delay left != 0: delay left -= 1; return

shape 0 (ramp), 1 (sawtooth), 2 (zigzag):
    if phase == 0:
        phase = 1;  speed ctr = speed;  acc = HOME
        shape 1: count ctr = count
        shape 2: count ctr = count >> 1, but at least 1
    if --speed ctr != 0: return
    speed ctr = speed
    shape 0, 1:   acc += step;                        OUT(acc)
    shape 2:      see the table
    shape 1, 2:   if --count ctr == 0:
                      count ctr = count
                      shape 1: acc = HOME              (no output: heard at the next step)
                      shape 2: see the table;  phase = 3 − phase

shape 3 (square):
    if phase != 0:
        if --speed ctr != 0: return
    if phase == 1:  phase = 2;  value = HOME
    else:           phase = 1;  value = HOME + step
    speed ctr = speed;  count ctr = count;  OUT(value)        (acc is not used, except SSG volume)
```

What differs between the five:

| | FM pitch, SSG pitch | FM volume | SSG volume | SSG noise |
|---|---|---|---|---|
| HOME | 0 | the track volume `[0A]` (read when used) | 0 | 0 |
| OUT(x) | pitch registers ← `pitch` + x (FM: §8.1; SSG: clamped period) | `set_level(x)` (§8.3) | nothing: `acc` itself is added in the envelope output (§8.2) | `06h ← clamp(noise period + (x >> 4), 0, 31)` |
| shape 2 step | `acc += step`; OUT(acc) in phase 1, **OUT(−acc)** in phase 2 | `acc += step` in phase 1, `acc −= step` in phase 2; OUT(acc) | as FM volume | as FM volume |
| shape 2 at count end | **acc = 0** | acc kept | acc kept | **acc = 0** |
| shape 3 | OUT only | OUT only | `acc` = step / 0 | OUT only |
| note-on | – | – | `acc ← 0` at every note-on, even with the LFO off | – |

So the volume "zigzag" is a true triangle (up count/2 steps, down count, up count, …), while the **pitch
zigzag is not**: it ramps away from the note for count/2 steps, snaps back, ramps to the *other* side for
count steps, snaps back, and so on (a mirrored sawtooth). The noise version ramps up, snaps to the base,
ramps down, snaps. This is what the code does and what NOVA's music sounds like (85 of 110 FM voices use
pitch type 84h; 67 of them with step ±1, i.e. a vibrato of a few cents).

Timing: the first effect tick after a note-on in which the LFO acts is the (delay + 1)-th. A square
outputs HOME + step on that tick; the other shapes make their first step `speed` ticks into it (on the
same tick if speed = 1).

Use in NOVA's voices (type byte: count) — FM pitch: 84h 85, 80h 12, 82h 7, off 6; FM volume: off 81, 84h
22, 80h 5, 82h 1, 86h 1; SSG pitch: 84h 35, off 13, 86h 7, 80h 2; SSG volume: off 48, 80h 5, 84h 2, 82h 2;
SSG noise: off 50, 84h 4, 80h 3. Shapes not occurring in a column are verified *(synthetic)*.

Interaction details:

* The FM volume LFO writes absolute levels; when the LFO ends its influence (e.g. the next note-on) the
  note-on's `set_level(volume)` takes over. A fade reaches a held FM note only through this LFO.
* Pitch LFO output uses the *current* `pitch`, so it rides on a portamento.
* A ramp (shape 0) on pitch is a continuous slide for the rest of the note (NOVA's drum-like FM voices:
  step −57 per effect tick), limited only by the clamp of §8.1.

## 11. Songs

In the game's documents: `docs/re/songs.md`, which is about this game's songs.

## 12. Verification

`usdmodel.py --check` (usd-driver.md §10): the model's register-write stream equals the original's in all
scenarios, for all 28 files and for the synthetic songs.

To make sure the comparison actually sees the details described here, 27 single rules of the model were
broken one at a time and the synthetic scenario (120 songs) re-run. 24 were detected: each of the gate
formulas tried and the `<` of the gate compare; unsigned portamento compare; "first note after F6 does not
slide"; signed TL; fade threshold; unclamped SSG note-on period; clamp limit of the FM pitch; stop order;
owner / clock mask; tempo only from owner bit 0; pitch zigzag mirrored vs. reversing; LFO count, delay and
the sawtooth reset; LFO state kept across voice loads; `<=` in the envelope decay; 2·master on SSG; F4
semantics; SSG envelope kept across rests; detune reset, volume and transpose kept at a song start. The
other three cannot be observed at all and are therefore not claims of this document: the tie flag set by
a gate release (§4), the clearing of the portamento target at `FF` (the next `F6` clears it anyway), and
8-bit-add-with-carry versus plain 16-bit addition in the noise period (the same arithmetic).

Coverage by real data: the commands, voices, LFO shapes and services not marked *(synthetic)* or **code**
are exercised by NOVA's own files in the play / fade / chain / phase scenarios. Boundary behaviour — note
and pitch clamps, TL bytes ≥ 80h, speed or count 0, the fade threshold, priorities — is reached only by
the synthetic songs.

## 13. Open questions

1. The 4 unused bytes of the SSG voice (8–11) and the unreferenced skip stubs suggest features of other
   driver versions; nothing reads them here.
2. Musical intent of the pitch "zigzag" (§10) — bug or design — is unknown; it is reproduced as is.
3. Real-chip effect of the unclamped SSG period write at a note-on with a detune that leaves 0..4095, and
   of key-on masks other than F0h (70h, C0h: one or two operators never keyed): the register values are
   verified, how it sounds is left to the chip emulation.
4. What tool and MML produced the files (command names, how the compiler chooses the transpose windows).
