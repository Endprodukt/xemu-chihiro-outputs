# Chihiro outputs: test tools (Windows)

Scripts used to measure and verify the cabinet outputs of the gun games.
They drive a windowed xemu on the developer's PC through the QEMU monitor
and synthetic keys; paths (`D:\Xemu Chihiro`, the xemu.toml under AppData)
are at the top of `xemudrv.py`.

- `outputs_listener.py`: a stand-in for MameHooker. Owns a hidden window,
  answers `MAMEOutputStart`, registers, asks the id names and prints every
  update; `--tcp 8000` also prints the TCP lines.
- `listener_test.py vc3|hotd3|gs`: boots the game, gets into play (mission
  select, intro skips), fires, empties the magazine, reloads, fires again,
  with the listener running; prints what arrived. Binds the trigger to Space
  and reload to R in a temporary copy of xemu.toml, which it restores.
- `memsearch2.py`: finds the magazine counter and the status byte of a build
  by diffing physical memory dumps (`pmemsave`) around scripted shots;
  `analyze_vc3.py` is the offline analysis, `pa2va.py` turns the physical
  addresses it finds into virtual ones through the guest's page tables
  (the Xbox page directory sits at physical 0xF000).

Run them with the plain interpreter (`python`, not `-I`): they import each
other from their own folder.
