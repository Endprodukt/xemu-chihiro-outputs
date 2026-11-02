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
 *
 * What a gun cabinet does besides showing the game: the start lamps light,
 * the gun kicks, Ghost Squad's card drawers lock. The games drive these
 * through the JVS I/O board's general purpose outputs, which the emulated
 * board receives (chihiro_outputs_jvs_gpo). Virtua Cop 3 and The House of
 * the Dead III have no recoil output on the real cabinet, so their shots are
 * read from the game: the magazine counter in memory drops by one for each
 * shot that is fired, in play only (not in the attract demo, which shoots
 * too), and never when it is empty. The same memory says whether the player
 * is in play, how much life and ammunition they have and how many credits
 * are in. The addresses are DemulShooter's for its Cxbx-Reloaded targets,
 * rebased to the Xbox (its offsets are from the XBE base, 0x10000; the
 * instruction bytes it checks at them are at the same place in these
 * images), and the outputs carry its names, so the MameHooker ini files
 * written for those targets apply unchanged.
 *
 * Two ways out, both the ones MAME uses:
 *  - On Windows, a hidden "MAMEOutput" window on its own thread. A game's
 *    start is broadcast as MAMEOutputStart with the window; a listener
 *    registers itself (MAMEOutputRegister), asks the names of the ids it
 *    sees (MAMEOutputGetIDString, answered by WM_COPYDATA; id 0 is the ROM
 *    name, which picks the listener's ini) and gets MAMEOutputUpdateState
 *    for each change. This is how MameHooker listens.
 *  - A TCP server on the loopback, text lines "name = value\r" like
 *    DemulShooter's (MAME ends them with \1): "mame_start = <rom>" when a
 *    game is on, every output once, then the changes, "mame_stop = 1" at the
 *    end. For Hook of the Reaper and other listeners, and for Linux.
 */
#include "qemu/osdep.h"
#include "qemu/timer.h"
#include "qemu/main-loop.h"
#include "qemu/sockets.h"
#include "qemu/thread.h"
#include "qemu/bswap.h"
#include "ui/xemu-settings.h"
#include "chihiro.h"
#include "chihiro-log.h"
#include "chihiro-outputs.h"

#ifndef _WIN32
#include <fcntl.h>
#endif

/* Every output a game can publish; DemulShooter's names. */
typedef enum {
    OUT_P1_LMP_START, OUT_P2_LMP_START,
    OUT_LMP_BILLBOARD, OUT_P1_LMP_HOLDER, OUT_P2_LMP_HOLDER,
    OUT_P1_LMP_FOOT, OUT_P2_LMP_FOOT,
    OUT_P1_GUN_RECOIL, OUT_P2_GUN_RECOIL,
    OUT_P1_CARD_LOCK, OUT_P2_CARD_LOCK,
    OUT_LAST_JVS = OUT_P2_CARD_LOCK,      /* the ones the JVS byte carries */
    OUT_P1_AMMO, OUT_P2_AMMO,
    OUT_P1_CLIP, OUT_P2_CLIP,
    OUT_P1_CTM_RECOIL, OUT_P2_CTM_RECOIL,
    OUT_P1_LIFE, OUT_P2_LIFE,
    OUT_P1_DAMAGED, OUT_P2_DAMAGED,
    OUT_CREDITS,
    OUT_COUNT
} OutputIdx;

static const char *const output_names[OUT_COUNT] = {
    [OUT_P1_LMP_START]  = "P1_LmpStart",
    [OUT_P2_LMP_START]  = "P2_LmpStart",
    [OUT_LMP_BILLBOARD] = "LmpBillboard",
    [OUT_P1_LMP_HOLDER] = "P1_LmpHolder",
    [OUT_P2_LMP_HOLDER] = "P2_LmpHolder",
    [OUT_P1_LMP_FOOT]   = "P1_LmpFoot",
    [OUT_P2_LMP_FOOT]   = "P2_LmpFoot",
    [OUT_P1_GUN_RECOIL] = "P1_GunRecoil",
    [OUT_P2_GUN_RECOIL] = "P2_GunRecoil",
    [OUT_P1_CARD_LOCK]  = "P1_CardLock",
    [OUT_P2_CARD_LOCK]  = "P2_CardLock",
    [OUT_P1_AMMO]       = "P1_Ammo",
    [OUT_P2_AMMO]       = "P2_Ammo",
    [OUT_P1_CLIP]       = "P1_Clip",
    [OUT_P2_CLIP]       = "P2_Clip",
    [OUT_P1_CTM_RECOIL] = "P1_CtmRecoil",
    [OUT_P2_CTM_RECOIL] = "P2_CtmRecoil",
    [OUT_P1_LIFE]       = "P1_Life",
    [OUT_P2_LIFE]       = "P2_Life",
    [OUT_P1_DAMAGED]    = "P1_Damaged",
    [OUT_P2_DAMAGED]    = "P2_Damaged",
    [OUT_CREDITS]       = "Credits",
};

#define OBIT(idx) (1u << (idx))
#define OBIT_PAIR(idx) (OBIT(idx) | OBIT((idx) + 1))
/* What every gun game reads from its memory. */
#define OBIT_MEMORY (OBIT_PAIR(OUT_P1_AMMO) | OBIT_PAIR(OUT_P1_CLIP) | \
                    OBIT_PAIR(OUT_P1_CTM_RECOIL) |                       \
                    OBIT_PAIR(OUT_P1_LIFE) |                             \
                    OBIT_PAIR(OUT_P1_DAMAGED) | OBIT(OUT_CREDITS))

typedef enum {
    MEM_BYTES,      /* status, life, ammo: one byte each at a fixed address */
    MEM_GS,         /* Ghost Squad: life and ammo behind pointers */
} MemKind;

/* Where a build of the game keeps what we read; told apart by a few bytes
 * of its code, as DemulShooter tells its targets apart. */
typedef struct {
    const char *name;
    uint32_t    check_va;
    uint8_t     check[4];
    int         check_len;
    uint32_t    status[2];
    uint32_t    life[2];        /* MEM_GS: the pointer to the player's record */
    uint32_t    ammo[2];        /* MEM_GS: the one pointer, both players */
    uint32_t    credits;
} OutputRevision;

typedef struct {
    const char *xbe;            /* chihiro_game_filename, without its directory */
    const char *rom;            /* the ROM name: the listener's ini file */
    uint32_t    published;      /* OBIT() mask */
    /* JVS general purpose output, bank 0: the bit of each lamp or solenoid,
     * 0 where the cabinet has none. */
    uint8_t     gpo_bit[OUT_LAST_JVS + 1];
    /* The recoil pulse: from the game's own JVS recoil output, else from the
     * magazine counter dropping. */
    bool        recoil_from_jvs;
    MemKind     kind;
    uint8_t     ingame;         /* the status byte's value while in play */
    const OutputRevision *revs;
    int         nrevs;
} OutputGame;

/* Virtua Cop 3 (vc3.xbe). The status byte: 0 inactive, 2 in play,
 * 8 continue screen, 16 game over, 128 attract demo. The player's record
 * holds the life at +0xC and the score at +0x18; player 2's is 0xAC behind,
 * their magazine 0xD8 behind.
 * Two builds: the GD-ROM MAME calls vcop3 (XBE of 2003-05-21, 0x5B5080
 * bytes), measured here (the magazine 9, 8, 7, 0, the status 0, 2, 8 in
 * attract, play, continue); and the one DemulShooter's Cxbx target knows
 * (0x51BA00 bytes), its addresses. The credits of the first are the
 * second's moved by the same 0x76B00 as the status, not yet seen counting. */
static const OutputRevision vcop3_revs[] = {
    { "2003-05 GD-ROM", 0x0007A3D6, { 0xF0, 0x68, 0x30, 0x9F }, 4,
      .status  = { 0x003F3F68, 0x003F3F68 + 0xAC },
      .life    = { 0x003F3F74, 0x003F3F74 + 0xAC },
      .ammo    = { 0x003DE432, 0x003DE432 + 0xD8 },
      .credits = 0x0055FB18 },
    { "Cxbx dump", 0x0007A3D6, { 0x8B, 0xE8 }, 2,
      .status  = { 0x0037D468, 0x0037D468 + 0xAC },
      .life    = { 0x0037D474, 0x0037D474 + 0xAC },
      .ammo    = { 0x00367942, 0x00367942 + 0xD8 },
      .credits = 0x004E9018 },
};
/* Bit 6 and bit 3 are DemulShooter's "foot lamps"; seen here, they come on
 * when the player is hit. */
static const OutputGame game_vcop3 = {
    .xbe = "vc3.xbe", .rom = "vcop3",
    .published = OBIT_PAIR(OUT_P1_LMP_START) |
                 OBIT_PAIR(OUT_P1_LMP_FOOT) | OBIT_MEMORY,
    .gpo_bit = { [OUT_P1_LMP_START] = 0x80, [OUT_P2_LMP_START] = 0x10,
                 [OUT_P1_LMP_FOOT]  = 0x40, [OUT_P2_LMP_FOOT]  = 0x08 },
    .kind = MEM_BYTES, .ingame = 2,
    .revs = vcop3_revs, .nrevs = ARRAY_SIZE(vcop3_revs),
};

/* The House of the Dead III (hod3xb.xbe). The status byte: 5 in play,
 * 4 continue screen, 66 game over, 9 attract demo. */
static const OutputRevision hod3_revs[] = {
    { "GD-ROM", 0x00011B62, { 0x66, 0x89, 0x4E, 0x12 }, 4,
      .status  = { 0x00276708, 0x00276934 },
      .life    = { 0x00276714, 0x00276940 },
      .ammo    = { 0x00276760, 0x0027698C },
      .credits = 0x004CBA38 },
};
static const OutputGame game_hod3 = {
    .xbe = "hod3xb.xbe", .rom = "hod3",
    .published = OBIT_PAIR(OUT_P1_LMP_START) | OBIT_MEMORY,
    .gpo_bit = { [OUT_P1_LMP_START] = 0x80, [OUT_P2_LMP_START] = 0x10 },
    .kind = MEM_BYTES, .ingame = 5,
    .revs = hod3_revs, .nrevs = ARRAY_SIZE(hod3_revs),
};

/* Ghost Squad (vsg.xbe). The cabinet has the recoil: its JVS output is the
 * kick, taken as it is and as the pulse. The status byte is 2 in play. The
 * card locks are the cabinet table's (chihiro.c), the holder lamps are
 * DemulShooter's reading of the same byte. */
static const OutputRevision gsquad_revs[] = {
    { "GD-ROM", 0x000852BE, { 0x8D, 0x54, 0x24, 0x0F }, 4,
      .status  = { 0x00465A28, 0x00465A28 + 0x1AC },
      .life    = { 0x00465B14, 0x00465B14 + 0x1AC },
      .ammo    = { 0x00451828, 0x00451828 },
      .credits = 0x004B9EA0 },
};
static const OutputGame game_gsquad = {
    .xbe = "vsg.xbe", .rom = "gsquad",
    .published = OBIT_PAIR(OUT_P1_LMP_START) | OBIT(OUT_LMP_BILLBOARD) |
                 OBIT_PAIR(OUT_P1_LMP_HOLDER) |
                 OBIT_PAIR(OUT_P1_GUN_RECOIL) |
                 OBIT_PAIR(OUT_P1_CARD_LOCK) | OBIT_MEMORY,
    .gpo_bit = { [OUT_P1_LMP_START]  = 0x80, [OUT_P2_LMP_START]  = 0x04,
                 [OUT_LMP_BILLBOARD] = 0x10,
                 [OUT_P1_LMP_HOLDER] = 0x08, [OUT_P2_LMP_HOLDER] = 0x20,
                 [OUT_P1_GUN_RECOIL] = 0x40, [OUT_P2_GUN_RECOIL] = 0x02,
                 [OUT_P1_CARD_LOCK]  = 0x20, [OUT_P2_CARD_LOCK]  = 0x01 },
    .recoil_from_jvs = true,
    .kind = MEM_GS, .ingame = 2,
    .revs = gsquad_revs, .nrevs = ARRAY_SIZE(gsquad_revs),
};

static const OutputGame *const games[] = {
    &game_vcop3, &game_hod3, &game_gsquad,
};

/* A pulse output: on for a while, then at rest for a while, during which
 * another trigger is not another pulse (DemulShooter's AsyncGameOutput). */
typedef struct {
    OutputIdx  idx;
    QEMUTimer *timer;
    int64_t    free_at;         /* QEMU_CLOCK_REALTIME ms */
} Pulse;

enum { PULSE_P1_RECOIL, PULSE_P2_RECOIL, PULSE_P1_DAMAGED, PULSE_P2_DAMAGED,
       PULSE_COUNT };

static struct {
    const OutputGame *game;     /* NULL between sessions */
    const OutputRevision *rev;  /* the build found in memory, NULL until then */
    bool     rev_missing_said;
    int32_t  value[OUT_COUNT];
    int32_t  sent[OUT_COUNT];
    int32_t  last_ammo[2];
    int32_t  last_life[2];
    uint8_t  gpo;
    bool     gpo_seen;
    Pulse    pulse[PULSE_COUNT];
} st = {
    .pulse = {
        [PULSE_P1_RECOIL]  = { .idx = OUT_P1_CTM_RECOIL },
        [PULSE_P2_RECOIL]  = { .idx = OUT_P2_CTM_RECOIL },
        [PULSE_P1_DAMAGED] = { .idx = OUT_P1_DAMAGED },
        [PULSE_P2_DAMAGED] = { .idx = OUT_P2_DAMAGED },
    },
};

static void publish(void);

/* ------------------------------------------------------------------------
 * The MAME output window (Windows)
 * ------------------------------------------------------------------------ */
#ifdef _WIN32

#define WM_MAX_CLIENTS 16
#define COPYDATA_MESSAGE_ID_STRING 1

typedef struct {
    HWND   hwnd;
    LPARAM id;
} WmClient;

static struct {
    bool          up;           /* the thread and its window exist */
    QemuThread    thread;
    QemuSemaphore ready;
    QemuMutex     lock;         /* clients, rom, published, last */
    HWND          hwnd;
    UINT om_start, om_stop, om_update, om_register, om_unregister, om_getid;
    WmClient      clients[WM_MAX_CLIENTS];
    int           nclients;
    char          rom[32];
    uint32_t      published;
    int32_t       last[OUT_COUNT];
    bool          on_air;       /* MAMEOutputStart sent, no Stop yet */
} wm;

/* A listener's hello. Known already (same id): its window is the new one.
 * Either way it gets every output once, as MAME's notify_all. */
static void wm_register(HWND hwnd, LPARAM id)
{
    qemu_mutex_lock(&wm.lock);
    int i;
    for (i = 0; i < wm.nclients; i++) {
        if (wm.clients[i].id == id) {
            break;
        }
    }
    if (i == wm.nclients) {
        if (wm.nclients == WM_MAX_CLIENTS) {
            /* The oldest goes: a listener that restarted many times. */
            memmove(&wm.clients[0], &wm.clients[1],
                    sizeof(wm.clients[0]) * (WM_MAX_CLIENTS - 1));
            i = WM_MAX_CLIENTS - 1;
        } else {
            wm.nclients++;
        }
    }
    wm.clients[i].hwnd = hwnd;
    wm.clients[i].id = id;
    for (int o = 0; o < OUT_COUNT; o++) {
        if (wm.published & OBIT(o)) {
            PostMessageA(hwnd, wm.om_update, (WPARAM)(o + 1),
                         (LPARAM)wm.last[o]);
        }
    }
    qemu_mutex_unlock(&wm.lock);
}

static void wm_unregister(HWND hwnd, LPARAM id)
{
    qemu_mutex_lock(&wm.lock);
    for (int i = 0; i < wm.nclients; i++) {
        if (wm.clients[i].id == id && wm.clients[i].hwnd == hwnd) {
            memmove(&wm.clients[i], &wm.clients[i + 1],
                    sizeof(wm.clients[0]) * (wm.nclients - i - 1));
            wm.nclients--;
            break;
        }
    }
    qemu_mutex_unlock(&wm.lock);
}

/* The name behind an id, by WM_COPYDATA: id 0 is the ROM, the others the
 * outputs, an unknown one an empty string (as MAME answers). */
static void wm_send_id_string(HWND hwnd, LPARAM id)
{
    char name[64] = "";

    qemu_mutex_lock(&wm.lock);
    if (id == 0) {
        g_strlcpy(name, wm.rom, sizeof(name));
    } else if (id >= 1 && id <= OUT_COUNT &&
               (wm.published & OBIT(id - 1))) {
        g_strlcpy(name, output_names[id - 1], sizeof(name));
    }
    qemu_mutex_unlock(&wm.lock);

    /* MAME's copydata_id_string: a UINT32 id, then the string. */
    size_t len = sizeof(uint32_t) + strlen(name) + 1;
    uint8_t *buf = g_malloc0(len);
    uint32_t id32 = (uint32_t)id;
    memcpy(buf, &id32, sizeof(id32));
    memcpy(buf + sizeof(id32), name, strlen(name) + 1);

    COPYDATASTRUCT cd = {
        .dwData = COPYDATA_MESSAGE_ID_STRING,
        .cbData = (DWORD)len,
        .lpData = buf,
    };
    SendMessageA(hwnd, WM_COPYDATA, (WPARAM)wm.hwnd, (LPARAM)&cd);
    g_free(buf);
}

static LRESULT CALLBACK wm_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == wm.om_register) {
        wm_register((HWND)wp, lp);
        return 0;
    }
    if (msg == wm.om_unregister) {
        wm_unregister((HWND)wp, lp);
        return 0;
    }
    if (msg == wm.om_getid) {
        wm_send_id_string((HWND)wp, lp);
        return 0;
    }
    if (msg == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

static void *wm_thread_fn(void *arg)
{
    WNDCLASSA wc = {
        .lpfnWndProc = wm_proc,
        .hInstance = GetModuleHandleA(NULL),
        .lpszClassName = "MAMEOutput",
    };
    RegisterClassA(&wc);        /* twice is an error, and no harm */
    wm.hwnd = CreateWindowExA(0, "MAMEOutput", "MAMEOutput",
                              WS_OVERLAPPEDWINDOW, 0, 0, 1, 1,
                              NULL, NULL, wc.hInstance, NULL);
    qemu_sem_post(&wm.ready);
    if (!wm.hwnd) {
        return NULL;
    }

    MSG m;
    while (GetMessageA(&m, NULL, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageA(&m);
    }
    wm.hwnd = NULL;
    return NULL;
}

static bool wm_up(void)
{
    if (wm.up) {
        return wm.hwnd != NULL;
    }
    wm.om_start      = RegisterWindowMessageA("MAMEOutputStart");
    wm.om_stop       = RegisterWindowMessageA("MAMEOutputStop");
    wm.om_update     = RegisterWindowMessageA("MAMEOutputUpdateState");
    wm.om_register   = RegisterWindowMessageA("MAMEOutputRegister");
    wm.om_unregister = RegisterWindowMessageA("MAMEOutputUnregister");
    wm.om_getid      = RegisterWindowMessageA("MAMEOutputGetIDString");
    qemu_mutex_init(&wm.lock);
    qemu_sem_init(&wm.ready, 0);
    qemu_thread_create(&wm.thread, "chihiro-outputs", wm_thread_fn, NULL,
                       QEMU_THREAD_JOINABLE);
    qemu_sem_wait(&wm.ready);
    wm.up = true;
    if (!wm.hwnd) {
        fprintf(stderr, "Chihiro outputs: no output window (%lu)\n",
                (unsigned long)GetLastError());
    }
    return wm.hwnd != NULL;
}

static void wm_start(const char *rom, uint32_t published)
{
    if (!wm_up()) {
        return;
    }
    qemu_mutex_lock(&wm.lock);
    g_strlcpy(wm.rom, rom, sizeof(wm.rom));
    wm.published = published;
    memset(wm.last, 0, sizeof(wm.last));
    qemu_mutex_unlock(&wm.lock);
    wm.on_air = true;
    PostMessageA(HWND_BROADCAST, wm.om_start, (WPARAM)wm.hwnd, 0);
}

static void wm_send(OutputIdx idx, int32_t value)
{
    if (!wm.up || !wm.hwnd) {
        return;
    }
    qemu_mutex_lock(&wm.lock);
    wm.last[idx] = value;
    for (int i = 0; i < wm.nclients; i++) {
        PostMessageA(wm.clients[i].hwnd, wm.om_update, (WPARAM)(idx + 1),
                     (LPARAM)value);
    }
    qemu_mutex_unlock(&wm.lock);
}

static void wm_stop(void)
{
    if (!wm.up || !wm.hwnd || !wm.on_air) {
        return;
    }
    wm.on_air = false;
    PostMessageA(HWND_BROADCAST, wm.om_stop, (WPARAM)wm.hwnd, 0);
    qemu_mutex_lock(&wm.lock);
    wm.rom[0] = 0;
    wm.published = 0;
    qemu_mutex_unlock(&wm.lock);
}

static void wm_exit(void)
{
    wm_stop();
    if (!wm.up) {
        return;
    }
    if (wm.hwnd) {
        PostMessageA(wm.hwnd, WM_CLOSE, 0, 0);
    }
    qemu_thread_join(&wm.thread);
    wm.up = false;
}

static int wm_listeners(void)
{
    if (!wm.up) {
        return 0;
    }
    qemu_mutex_lock(&wm.lock);
    int n = wm.nclients;
    qemu_mutex_unlock(&wm.lock);
    return n;
}

#else /* !_WIN32 */

static void wm_start(const char *rom, uint32_t published)
{
    (void)rom;
    (void)published;
}
static void wm_send(OutputIdx idx, int32_t value)
{
    (void)idx;
    (void)value;
}
static void wm_stop(void) { }
static void wm_exit(void) { }
static int  wm_listeners(void) { return 0; }

#endif

/* ------------------------------------------------------------------------
 * The TCP server
 * ------------------------------------------------------------------------ */
#define NET_MAX_CLIENTS 8

static struct {
    int listen_fd;
    int port;
    int clients[NET_MAX_CLIENTS];
    int nclients;
} net = { .listen_fd = -1 };

static void net_set_nonblock(int fd)
{
#ifdef _WIN32
    unsigned long on = 1;
    ioctlsocket(fd, FIONBIO, &on);
#else
    int fl = fcntl(fd, F_GETFL);
    if (fl >= 0) {
        fcntl(fd, F_SETFL, fl | O_NONBLOCK);
    }
#endif
}

static void net_drop(int i)
{
    qemu_set_fd_handler(net.clients[i], NULL, NULL, NULL);
    close(net.clients[i]);
    memmove(&net.clients[i], &net.clients[i + 1],
            sizeof(net.clients[0]) * (net.nclients - i - 1));
    net.nclients--;
}

/* False when the connection is gone (a slow reader is not: its line is
 * lost, which beats blocking the emulation). */
static bool net_write(int fd, const char *line)
{
    ssize_t n = send(fd, line, strlen(line), 0);
    if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
        return false;
    }
    return true;
}

static void net_broadcast(const char *line)
{
    for (int i = net.nclients - 1; i >= 0; i--) {
        if (!net_write(net.clients[i], line)) {
            net_drop(i);
        }
    }
}

static void net_send_value_to(int fd, OutputIdx idx, int32_t value)
{
    char line[96];
    snprintf(line, sizeof(line), "%s = %d\r", output_names[idx], (int)value);
    net_write(fd, line);
}

static void net_send_value(OutputIdx idx, int32_t value)
{
    char line[96];
    snprintf(line, sizeof(line), "%s = %d\r", output_names[idx], (int)value);
    net_broadcast(line);
}

/* A listener says nothing we need; what it does say is drained, and its
 * leaving noticed. */
static void net_client_read(void *opaque)
{
    int fd = (int)(intptr_t)opaque;
    char buf[128];
    ssize_t n = recv(fd, buf, sizeof(buf), 0);
    bool gone = n == 0 ||
                (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK &&
                 errno != EINTR);
    if (!gone) {
        return;
    }
    for (int i = 0; i < net.nclients; i++) {
        if (net.clients[i] == fd) {
            net_drop(i);
            return;
        }
    }
}

static void net_greet(int fd)
{
    char line[96];

    if (!st.game) {
        net_write(fd, "mame_start = ___empty\r");
        return;
    }
    net_write(fd, "mame_stop = 1\r");
    snprintf(line, sizeof(line), "mame_start = %s\r", st.game->rom);
    net_write(fd, line);
    for (int o = 0; o < OUT_COUNT; o++) {
        if (st.game->published & OBIT(o)) {
            net_send_value_to(fd, o, st.value[o]);
        }
    }
}

static void net_accept(void *opaque)
{
    int fd = accept(net.listen_fd, NULL, NULL);
    if (fd < 0) {
        return;
    }
    if (net.nclients == NET_MAX_CLIENTS) {
        close(fd);
        return;
    }
    net_set_nonblock(fd);
    net.clients[net.nclients++] = fd;
    qemu_set_fd_handler(fd, net_client_read, NULL, (void *)(intptr_t)fd);
    net_greet(fd);
}

static void net_close(void)
{
    while (net.nclients) {
        net_drop(net.nclients - 1);
    }
    if (net.listen_fd >= 0) {
        qemu_set_fd_handler(net.listen_fd, NULL, NULL, NULL);
        close(net.listen_fd);
        net.listen_fd = -1;
    }
}

/* Listens on the loopback; once, and again on another port. */
static void net_listen(int port)
{
    static int failed_port;

    if (port < 1 || port > 65535) {
        port = 8000;
    }
    if (net.listen_fd >= 0 && net.port == port) {
        return;
    }
    net_close();
    if (failed_port == port) {
        return;                 /* said so already */
    }

    int fd = qemu_socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        fprintf(stderr, "Chihiro outputs: socket: %s\n", strerror(errno));
        failed_port = port;
        return;
    }
    socket_set_fast_reuse(fd);
    struct sockaddr_in sa = {
        .sin_family = AF_INET,
        .sin_port = htons((uint16_t)port),
    };
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0 ||
        listen(fd, 4) < 0) {
        fprintf(stderr, "Chihiro outputs: TCP port %d is not ours: %s "
                "(DemulShooter or another xemu listening there?)\n",
                port, strerror(errno));
        close(fd);
        failed_port = port;
        return;
    }
    net_set_nonblock(fd);
    net.listen_fd = fd;
    net.port = port;
    failed_port = 0;
    qemu_set_fd_handler(fd, net_accept, NULL, NULL);
    fprintf(stderr, "Chihiro outputs: TCP server on 127.0.0.1:%d\n", port);
}

/* ------------------------------------------------------------------------
 * The session: a game's outputs, from its start to its end
 * ------------------------------------------------------------------------ */

static void publish(void)
{
    if (!st.game) {
        return;
    }
    for (int o = 0; o < OUT_COUNT; o++) {
        if (!(st.game->published & OBIT(o)) || st.value[o] == st.sent[o]) {
            continue;
        }
        st.sent[o] = st.value[o];
        wm_send(o, st.value[o]);
        net_send_value(o, st.value[o]);
    }
}

static void pulse_end(void *opaque)
{
    Pulse *p = opaque;
    st.value[p->idx] = 0;
    publish();
}

static void pulse_fire(Pulse *p, int on_ms, int off_ms)
{
    int64_t now = qemu_clock_get_ms(QEMU_CLOCK_REALTIME);

    if (now < p->free_at) {
        return;
    }
    if (on_ms < 1) {
        on_ms = 1;
    }
    if (off_ms < 0) {
        off_ms = 0;
    }
    if (!p->timer) {
        p->timer = timer_new_ms(QEMU_CLOCK_REALTIME, pulse_end, p);
    }
    st.value[p->idx] = 1;
    p->free_at = now + on_ms + off_ms;
    timer_mod(p->timer, now + on_ms);
}

static void pulse_reset(Pulse *p)
{
    if (p->timer) {
        timer_del(p->timer);
    }
    p->free_at = 0;
}

static const OutputGame *game_for(const char *filename)
{
    /* The name may carry the directory it was booted from ("A\\vsg.xbe"). */
    const char *n = filename;
    for (const char *c = filename; *c; c++) {
        if (*c == '\\' || *c == '/') {
            n = c + 1;
        }
    }
    if (!*n) {
        return NULL;
    }
    for (size_t i = 0; i < ARRAY_SIZE(games); i++) {
        if (g_ascii_strcasecmp(n, games[i]->xbe) == 0) {
            return games[i];
        }
    }
    return NULL;
}

static void session_start(const OutputGame *g)
{
    memset(st.value, 0, sizeof(st.value));
    memset(st.sent, 0, sizeof(st.sent));
    memset(st.last_ammo, 0, sizeof(st.last_ammo));
    memset(st.last_life, 0, sizeof(st.last_life));
    st.gpo = 0;
    st.gpo_seen = false;
    st.rev = NULL;
    st.rev_missing_said = false;
    for (int i = 0; i < PULSE_COUNT; i++) {
        pulse_reset(&st.pulse[i]);
    }
    st.game = g;
    fprintf(stderr, "Chihiro outputs: %s as '%s'\n", g->xbe, g->rom);

    wm_start(g->rom, g->published);
    if (net.nclients) {
        char line[96];
        net_broadcast("mame_stop = 1\r");
        snprintf(line, sizeof(line), "mame_start = %s\r", g->rom);
        net_broadcast(line);
    }
    /* Every output once, so a listener that is already there knows them. */
    for (int o = 0; o < OUT_COUNT; o++) {
        if (g->published & OBIT(o)) {
            wm_send(o, st.value[o]);
            net_send_value(o, st.value[o]);
        }
    }
}

static void session_stop(void)
{
    if (!st.game) {
        return;
    }
    fprintf(stderr, "Chihiro outputs: '%s' off\n", st.game->rom);
    for (int i = 0; i < PULSE_COUNT; i++) {
        pulse_reset(&st.pulse[i]);
    }
    /* What was on goes off: a recoil or lamp left on would stay on. */
    for (int o = 0; o < OUT_COUNT; o++) {
        st.value[o] = 0;
    }
    publish();
    wm_stop();
    net_broadcast("mame_stop = 1\r");
    net_broadcast("mame_start = ___empty\r");
    st.game = NULL;
}

/* ------------------------------------------------------------------------
 * The game's memory
 * ------------------------------------------------------------------------ */

static bool rd8(uint32_t va, uint8_t *v)
{
    return chihiro_guest_read(va, v, 1);
}

static bool rd32(uint32_t va, uint32_t *v)
{
    uint32_t raw;
    if (!chihiro_guest_read(va, &raw, 4)) {
        return false;
    }
    *v = le32_to_cpu(raw);
    return true;
}

/* DemulShooter's ReadPtrChain: the pointer at base, then the value at each
 * offset from the last one; 0 anywhere on the way is nothing. */
static bool rd_chain(uint32_t base, const uint32_t *offs, int n, uint32_t *out)
{
    uint32_t p;

    if (!rd32(base, &p) || !p) {
        return false;
    }
    for (int i = 0; i < n; i++) {
        if (!rd32(p + offs[i], &p)) {
            return false;
        }
        if (!p && i < n - 1) {
            return false;
        }
    }
    *out = p;
    return true;
}

static void poll_player(int p)
{
    const OutputGame *g = st.game;
    const OutputRevision *r = st.rev;
    uint8_t status = 0;
    int32_t life = 0, ammo = 0, clip = 0;

    if (rd8(r->status[p], &status) && status == g->ingame) {
        if (g->kind == MEM_GS) {
            uint32_t v;
            static const uint32_t life_offs[] = { 0xB8 };
            uint32_t ammo_offs[] = { 0x38 + (p ? 0x650 : 0), 0x0C };
            life = rd_chain(r->life[p], life_offs, 1, &v) ? (int32_t)v : 0;
            ammo = rd_chain(r->ammo[p], ammo_offs, 2, &v) ? (int32_t)v : 0;
        } else {
            uint8_t b;
            life = rd8(r->life[p], &b) ? b : 0;
            ammo = rd8(r->ammo[p], &b) ? b : 0;
        }
        /* A shot: one round fewer. A reload adds, an empty magazine stays,
         * neither is a kick. */
        if (!g->recoil_from_jvs && ammo < st.last_ammo[p]) {
            pulse_fire(&st.pulse[PULSE_P1_RECOIL + p],
                       g_config.chihiro.outputs.recoil_on_ms,
                       g_config.chihiro.outputs.recoil_off_ms);
        }
        clip = ammo > 0;
        if (life < st.last_life[p]) {
            pulse_fire(&st.pulse[PULSE_P1_DAMAGED + p],
                       g_config.chihiro.outputs.damaged_ms, 100);
        }
    }
    st.last_ammo[p] = ammo;
    st.last_life[p] = life;
    st.value[OUT_P1_AMMO + p] = ammo;
    st.value[OUT_P1_CLIP + p] = clip;
    st.value[OUT_P1_LIFE + p] = life;
}

/* Which build runs: the first revision whose check bytes are in memory.
 * The game's pages may not be mapped yet when the session starts, so this
 * is asked again every tick until one answers. */
static bool find_revision(void)
{
    const OutputGame *g = st.game;
    uint8_t have[4] = { 0 };
    bool any_read = false;

    for (int i = 0; i < g->nrevs; i++) {
        const OutputRevision *r = &g->revs[i];
        if (!chihiro_guest_read(r->check_va, have, r->check_len)) {
            continue;
        }
        any_read = true;
        if (memcmp(have, r->check, r->check_len) == 0) {
            st.rev = r;
            fprintf(stderr, "Chihiro outputs: %s is the %s build\n",
                    g->xbe, r->name);
            return true;
        }
    }
    if (any_read && !st.rev_missing_said) {
        st.rev_missing_said = true;
        fprintf(stderr, "Chihiro outputs: %s is a build without known "
                "addresses (%02X %02X %02X %02X at %08X): lamps only\n",
                g->xbe, have[0], have[1], have[2], have[3],
                g->revs[0].check_va);
    }
    return false;
}

static void poll_memory(void)
{
    uint8_t credits;

    if (!st.rev && !find_revision()) {
        return;
    }
    poll_player(0);
    poll_player(1);
    st.value[OUT_CREDITS] = rd8(st.rev->credits, &credits) ? credits : 0;
}

/* ------------------------------------------------------------------------
 * Entry points
 * ------------------------------------------------------------------------ */

void chihiro_outputs_tick(void)
{
    if (!g_config.chihiro.outputs.enable) {
        session_stop();
        net_close();
        return;
    }
    if (g_config.chihiro.outputs.network) {
        net_listen(g_config.chihiro.outputs.network_port);
    } else {
        net_close();
    }
    if (!st.game) {
        const OutputGame *g = game_for(chihiro_game_filename);
        if (!g) {
            return;
        }
        session_start(g);
    }
    poll_memory();
    publish();
}

void chihiro_outputs_jvs_gpo(uint8_t bank0)
{
    const OutputGame *g = st.game;

    if (!g) {
        return;
    }
    if (!st.gpo_seen || bank0 != st.gpo) {
        CHIHIRO_LOGF(JVS, "GPO bank 0 %02X\n", bank0);
    }
    for (int o = 0; o <= OUT_LAST_JVS; o++) {
        if (g->gpo_bit[o]) {
            st.value[o] = (bank0 & g->gpo_bit[o]) ? 1 : 0;
        }
    }
    if (g->recoil_from_jvs) {
        for (int p = 0; p < 2; p++) {
            uint8_t bit = g->gpo_bit[OUT_P1_GUN_RECOIL + p];
            bool now = bit && (bank0 & bit);
            bool was = bit && st.gpo_seen && (st.gpo & bit);
            if (now && !was) {
                pulse_fire(&st.pulse[PULSE_P1_RECOIL + p],
                           g_config.chihiro.outputs.recoil_on_ms,
                           g_config.chihiro.outputs.recoil_off_ms);
            }
        }
    }
    st.gpo = bank0;
    st.gpo_seen = true;
    publish();
}

void chihiro_outputs_stop(void)
{
    session_stop();
}

void chihiro_outputs_exit(void)
{
    session_stop();
    wm_exit();
    net_close();
}

const char *chihiro_outputs_rom(void)
{
    return st.game ? st.game->rom : NULL;
}

int chihiro_outputs_listeners(void)
{
    return wm_listeners() + net.nclients;
}
