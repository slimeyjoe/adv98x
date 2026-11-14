# NOVA / Adv98X

Reverse engineering of the PC-98 visual novel NOVA ～魅入られた肢体～ (Cat's Pro, 1993; engine
Adv98V 1.70.54 on AdvBIOS 0.54) and a new portable engine for it, **Adv98X** (binary `adv98x`,
C prefix `ax_`/`AX_`, game profile and pack name `nova`). Successor of the Xenon port
(`xenon`), whose platform layer this engine starts from.

## Where things are

- `docs/re/README.md` — index of the research: interpreter, script format, AdvBIOS services,
  plug-ins, picture formats, music driver and sequencer, script catalogue, disks, other releases.
  **Read the relevant document before writing engine code; they are the specification.**
- `docs/engine-plan.md` — the approved implementation plan (architecture, what is copied from
  Xenon, milestones M0–M7, verification) with the current status at its top.
- `source/tools/` — build-side Python (stdlib only): `gamedata.py` (import/check/derive),
  `diskimg.py`, `mes.py` (script parser), `gpc.py` (picture decoder). The engine goes in `source/`.
- `re-tools/` — research tools (disassembly, emulation harnesses, verified reference models:
  `usdmodel.py` for the music sequencer, `gpc_verify.py`, `tcmtool.py`, `mesdis.py`, `mesgraph.py`).
- `resources/` — only our own tables are committed (`inventory.tsv`, `scripts.tsv`, `music/*.tsv`).

## Rules

- **No game data in the repository, ever**: no original files, decoded art, script text dumps,
  disassembly listings or recordings. They live in `resources/original/` and `resources/derived/`
  (git-ignored) and are rebuilt from the user's originals:
  `python3 -I source/tools/gamedata.py import <your copies>/pc-98 <EVE.PCK> "<Fuzion .hdi>"`
  then `python3 -I source/tools/gamedata.py derive --python $EMU_PYTHON`.
  Docs quote the game only as far as needed to identify things. The `FLAG*` / `NAME.DEF` of the
  dumped disk A are the previous owner's state: test inputs only, never packed.
- Engine: generic Adv98V engine, NOVA is a profile; no game-specific hacks. Plug-ins (`.TCM`) are
  native modules enabled per game. The VM executes script bytes exactly as `NV.OVL` does.
- Licence GPL-3.0-or-later (SPDX header in every own source file); third-party code keeps its own.
- Every test compares against data from the original code or a verified reference tool, never
  against the engine's own output.
- Research documents mark claims **verified** / **inferred** and cite code addresses; keep that
  when adding to them, and fix a document when the engine work proves it wrong.
- Python tools run as `python3 -I tool.py`; emulation tools need `$EMU_PYTHON`
  (capstone, unicorn, pillow, numpy).
- Commit after each coherent step; private repo for now (a pseudonymous public release comes
  later, so keep names, hosts and home paths out of tracked files).
