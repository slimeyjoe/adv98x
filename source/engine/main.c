/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Adv98X as a backend sees it (lrvne/app.h): its name and version, its own options, what runs
 * the game and renders a song, and the names of its trace events for test automation. The
 * backend the program is linked with (lrvne's backends/) provides lrv_app_main. */
#include <string.h>
#include "ax.h"
#include "version.h"

/* The AmigaOS Version command looks for this text in the program file (`version adv98x`);
 * elsewhere it is only a string. */
const char ax_amiga_version[] = "$VER: adv98x " AX_VERSION " (" AX_VERSION_DATE ")";

#if defined(__VBCC__) && defined(__M68K__)
/* vbcc's AmigaOS startup swaps in a stack of this size when the program was started with a
 * smaller one (4 KB, the default of a shell and of an icon that names none, is too little).
 * The interpreter recurses for the script's blocks as the original did on the PC-98's stack;
 * every story played through in 20 KB on x86-64, so 64 KB leaves room. The WarpOS startup has
 * no such variable (docs/amiga.md). */
size_t __stack = 65536;
#endif

static struct ax_options options;

static const struct lrv_option option_table[] = {
    { "view", LRV_OPT_OPTARG, "PICTURE",
      "browse the pack's pictures instead of playing, from PICTURE on" }
};

static int option(void *ctx, const char *name, const char *arg)
{
    struct ax_options *o = ctx;
    if (strcmp(name, "view"))
        return 1;
    o->view = 1;
    o->view_picture = arg;
    return 0;
}

/* enum ax_trace_kind, from LRV_TR_ENGINE */
static const char *const trace_names[(int)AX_TR_KIND_END - (int)LRV_TR_ENGINE] = {
    "script", "op", "text", "menu", "menu_sel", "picture", "palette", "sound", "save", "load",
    "module", "flag"
};

/* every wait but a timed delay waits for the player */
static int wait_is_input(int wait_kind)
{
    return wait_kind != AX_WAIT_TICKS;
}

static const struct lrv_app app = {
    .name = "adv98x",
    .version = AX_VERSION,
    .ctx = &options,
    .options = option_table,
    .noptions = (int)(sizeof option_table / sizeof option_table[0]),
    .option = option,
    .help = "keys: the keyboard is the PC-98's (Return and Space go on, the cursor keys move in\n"
            "  menus, Esc cancels, Shift held skips text); in the viewer the cursor keys step\n"
            "  and Esc quits",
    .run = ax_run,
    .render_music = ax_render_music,
    .trace_names = trace_names,
    .ntrace_names = (int)(sizeof trace_names / sizeof trace_names[0]),
    .wait_is_input = wait_is_input
};

int main(int argc, char **argv)
{
    return lrv_app_main(&app, argc, argv);
}
