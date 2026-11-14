/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Adv98X engine - public entry point for the backends. */
#ifndef AX_AX_H
#define AX_AX_H

#include "ax_hal.h"

struct ax_config {
    struct ax_video_cfg video;
    int language;          /* XPAK_L_JA / _EN / _PL (xpak_lang_id); 0 = the profile's default */
    int audio_rate;        /* requested output rate, 0 = audio off */
    /* picture viewer (a tool, not the game): 1 = browse the pack's pictures instead of
     * running the game; view_picture names the first one (NULL = the first in the pack) */
    int view;
    const char *view_picture;
};

/* Run the game (or the viewer) until it quits. Returns the process exit code. */
int ax_run(const struct ax_hal *hal, const struct ax_config *cfg);

/* Pull-mode audio (ax_hal.h): render `frames` mono 16-bit samples at the rate audio_open
 * accepted. Called by the backend from its audio thread/interrupt; takes audio_lock. */
void ax_audio_render(int16_t *pcm, int frames);

#endif
