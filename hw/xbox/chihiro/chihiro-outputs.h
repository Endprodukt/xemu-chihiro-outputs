/*
 * Chihiro cabinet outputs, published the way MAME publishes its outputs
 *
 * Copyright (c) 2026 Endprodukt
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, see <http://www.gnu.org/licenses/>.
 */
#ifndef HW_XBOX_CHIHIRO_OUTPUTS_H
#define HW_XBOX_CHIHIRO_OUTPUTS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The gun games' cabinet outputs (start lamps, gun recoil, card locks) and
 * what their memory says of the game (in play or in attract, ammo, life,
 * credits), named as DemulShooter names them so the MameHooker ini files
 * written for its Chihiro targets apply unchanged. See chihiro-outputs.c. */

/* The periodic tick while the game runs (chihiro_diag_timer_cb, 16 ms, big
 * lock held): starts the session once the game is known, polls its memory. */
void chihiro_outputs_tick(void);

/* JVS General Purpose Output (0x32), bank 0: the lamps and solenoids the game
 * drives through the I/O board. From the JVS path, big lock held. */
void chihiro_outputs_jvs_gpo(uint8_t bank0);

/* The game is gone (QuickReboot): tells the listeners and forgets it. */
void chihiro_outputs_stop(void);

/* xemu leaves: stop, then take down the output window and the sockets. */
void chihiro_outputs_exit(void);

/* For the UI: the ROM name the outputs are published under while a session
 * is on, NULL otherwise; and how many listeners took them. */
const char *chihiro_outputs_rom(void);
int chihiro_outputs_listeners(void);

#ifdef __cplusplus
}
#endif

#endif
