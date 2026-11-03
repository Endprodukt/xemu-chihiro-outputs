<img width="488" height="104" alt="chihiro-logo" src="https://github.com/user-attachments/assets/6fd9a78f-b636-4eb9-91f9-4f27a075e9bf" />

# xemu Chihiro fork by Tovarichtch

A fork of [xemu](https://xemu.app) that emulates the **Sega Chihiro**, the arcade
board Sega built on Xbox hardware. It boots the cabinet's own firmware, speaks the
arcade's own protocols, and plays games with the controls they were built for.

# Supported games

| Game | Status | Note |
|---|---|---|
| Crazy Taxi High Roller | ✅ |
| Ghost Squad | ✅ |
| Gundam Battle Operating Simulator | ✅ | network firmware required |
| OutRun 2 | ✅ |
| OutRun 2 SP | ✅ | network firmware required |
| Ollie King | ✅ |
| The House of the Dead III | ✅ |
| Virtua Cop 3 | ✅ |
| Wangan Midnight: Maximum Tune | ✅ |
| Wangan Midnight: Maximum Tune 2 | ✅ |
| Satellite Terminal games | ❌ | ALL.net; touchpad not emulated |

# Main features

### Type-1 and Type-3 boards

Both types are emulated with their own full protocol from boot to launch. The arcade I/O protocol is spoken by the emulated AN2131 with its 8051 core, its serial lines and its endpoints, not faked above them. The media board and its ROMs are emulated, and their state is real state. **Games must be .bin netboot images: make them with my tool [Chihiro-netboot](https://github.com/Tovarichtch/chihiro-netboot)**. All regions work: xemu picks one the game accepts.

## Light guns

- One pointer per player, each read on its own device (evdev on Linux, Raw Input
  on Windows). Up to 32 pointer devices, perfect for big arcade cabinet setups.
- A crosshair per player, with its own image and size of your choice.
- Sinden border around the game or the whole window, with its thickness. (Shout-out to the Sinden Lightgun Discord community!)
- F3 (default) toggles Light Gun Mode: in gun games the cursor hides and the mouse no longer opens xemu's menus.

## Steering wheel and force feedback

- Namco V257 (Maximum Tune series) and Sega 838-13683 (OutRun 2 series) drive boards emulated at the protocol level: real force feedback on a wheel, rumble on a gamepad.
- Settings for rotation, strength and weight to your taste; invert switch for wheels whose drivers push the wrong way.
- Auto-centering for Crazy Taxi, while the game is not driving the wheel, because no auto-centering feels wrong on a driving game.

## Card reader

- Tamura (SAXA) HW210 (Ghost Squad, Gundam) and Sanwa CRP-1231LR-10NAB (Maximum Tune series) card readers fully emulated.
- Create, share, swap cards on the fly, one per player. Insert the card with a single key.
- Cards are read, written and kept: a card carries its player's progress from one session to the next.
- For Ghost Squad players, grab [Dogehiro](https://github.com/Tovarichtch/dogehiro) to view and edit your cards.

## Cabinet outputs (this fork)

The gun games' outputs go to MameHooker and its kin, the way MAME's do:

- **Ghost Squad**: the cabinet's own JVS outputs, start lamps, billboard, the gun recoil of each player, the card locks.
- **Virtua Cop 3** and **The House of the Dead III**: start lamps (and VC3's foot-pedal lamps) from JVS; the recoil is read from the game itself, since these cabinets had none: a shot is the magazine counter dropping by one, in play only (not in the attract demo) and never with an empty magazine. Ammo, clip, life, a damaged pulse and credits come from the same memory.

Measured in xemu (2026-11-02), both players where the test harness could drive them: Virtua Cop 3 counts its magazine 9, 8, 7 ... 0 with one `P1_CtmRecoil` pulse per shot and none on an empty magazine or a reload; `P1_Damaged` pulses when life drops; The House of the Dead III 6 ... 0 the same way; Ghost Squad 24 ... 0 with the cabinet's own `P1_GunRecoil`. The netboot Virtua Cop 3 (the GD-ROM MAME calls vcop3, XBE of 2003-05-21) is not the build DemulShooter's addresses are for, so the module carries one address set per build and picks it from a few code bytes; an unknown build still gets the lamps. VC3's bit 6 / bit 3 (`P1_LmpFoot`, `P2_LmpFoot` in DemulShooter's naming) light when the player is hit. The attract demos shoot too, under another status byte (VC3 128, HOTD3 9, Ghost Squad 128), which the in-play check leaves out: no recoil in attract. Player 2 was verified in play for VC3 (its record 0xB0 behind player 1's in the GD-ROM build), Ghost Squad (24 ... 12, its own recoil, reload, life) and HOTD3 (life, damage, in-play; its shots could not be driven from the keyboard, the magazine address is DemulShooter's). Ghost Squad's player 2 gets the card screen first: shoot "Start game without card" or insert a card.

The outputs carry DemulShooter's names (`P1_LmpStart`, `P1_CtmRecoil`, `P1_Ammo`, `P1_Clip`, `P1_Life`, `P1_Damaged`, `Credits`, ...) under the ROM names `vcop3`, `hod3` and `gsquad`, so MameHooker ini files written for DemulShooter's Chihiro targets apply unchanged. On Windows the outputs are the MAME output window messages (start MameHooker first, as with MAME). Settings > Chihiro > Outputs can also serve them as text lines on a TCP port (`name = value`, DemulShooter's protocol, 8000 by default) for Hook of the Reaper and other listeners. The pulses are fixed, since the guns are driven by the listener, not by xemu: a recoil is held for 50 ms, a full solenoid stroke with the usual GUN4IR ini line `cmw 1 F0x%s%`, which keeps the solenoid on exactly as long as the output is 1 (DemulShooter's default 10 ms and PCSX2x6's one 15 ms poll are too short for that), then rests 30 ms; the damaged pulse is 200 ms. The times and the addresses are in `hw/xbox/chihiro/chihiro-outputs.c`. `contrib/chihiro-outputs-test/` holds a MAME-output listener and the scripted test that measured the above.

## Snapshots

Native VM snapshots, kept in a qcow2 beside the settings. Snapshots are saved per game, quicksaving and quickloading on the fly.

## Link for multi-cabinets

Link up to 4 cabinets for supported games: Ollie King, OutRun 2, OutRun 2 SP, Maximum Tune 1 & 2. The real network board is emulated and runs its own firmware, so every linked cabinet needs the network firmware (ver1305.bin). Maximum Tune needs a wired network.

## Cabinet settings

Free play, region, and the operator keys. The test menu works, and so do the
settings it writes. Hi-scores are saved.

## Performance optimization (experimental)

The fork carries its own work on the NV2A and the guest CPU, switchable:

| Setting | What it does |
|---|---|
| `GPU boost` | Smoother, faster rendering. Turn it off and you get stock xemu |
| `CPU boost` | Games run faster. Turn it off only if one misbehaves; needs a restart. |
| `Smooth first play` | Prepares the effects while the game boots, so the first minutes do not stutter as it compiles them |
| `Real hardware speed` | Holds the machine to the cabinet's own pace. Off, it runs as fast as your computer allows. |

This heavy lifting was done with an enormous amount of debugging with Ghidra-MCP and Claude Code sessions. The aim is to test and bring incremental changes to upstream for native integration in xemu.

## Building

Compile the `perf-experimental` branch for all the optimizations; you can switch back to the stock NV2A at any time (GPU boost off).
Compile the `main` branch if you just want Chihiro emulation without any optimization. This branch does contain some core changes and fixes.

## Reporting a problem

Tick **Debug mode** in the experimental settings. It writes a log to the `logs` folder saying
where each frame went: the frame rate, the stutters, the effects being compiled, the
waits on the graphics card and on the processor. Attach it to the report and the
problem can be read rather than guessed. It costs nothing while it is off.

**DO NOT REPORT ISSUES AND FEATURE REQUESTS ON MAIN XEMU GITHUB**

Report issues in this repository's [Issues](https://github.com/Tovarichtch/xemu/issues), never on xemu's GitHub.

## Important notes

- To set it up and see what xemu Chihiro can do, read the [wiki](https://github.com/Tovarichtch/xemu/wiki/) (WIP).
- Make sure the controller you play with is selected on port 1 in the `Input` tab. If you play with a steering wheel, select it on `Port 2`.
- Xbox retail games run, but only a few have been tested: expect glitches and bugs.

## Doge mode (Easter egg)

In your `xemu.toml` file, at the very bottom, add:

```
[doge]
doge_mode = 'wow'
```

## License

GPL-2.0, like xemu.

## About

Special thanks to all testers and SUPA Peter for extensive testing over and over again.

You can follow me on [Arcade Community discord](https://discord.gg/a2rHM7BVy) for my next projects.
