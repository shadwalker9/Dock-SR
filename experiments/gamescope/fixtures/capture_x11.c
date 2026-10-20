// DockSR-owned XGetImage capture. PPM preserves RGB; it cannot prove alpha.
#define _POSIX_C_SOURCE 200809L
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned component(unsigned long pixel, unsigned long mask) {
    unsigned shift = 0;
    if (!mask) return 0;
    while (!(mask & 1)) { mask >>= 1; ++shift; }
    return (unsigned)((((pixel >> shift) & mask) * 255 + mask / 2) / mask);
}

static Window find_window(Display *display, Window parent, unsigned long pid,
                          unsigned width, unsigned height, Atom pid_atom) {
    XWindowAttributes attributes;
    if (XGetWindowAttributes(display, parent, &attributes) &&
        attributes.map_state == IsViewable && (unsigned)attributes.width == width &&
        (unsigned)attributes.height == height) {
        Atom actual_type; int actual_format; unsigned long count, remaining;
        unsigned char *value = NULL;
        int ok = XGetWindowProperty(display, parent, pid_atom, 0, 1, False,
            XA_CARDINAL, &actual_type, &actual_format, &count, &remaining, &value);
        int match = ok == Success && actual_type == XA_CARDINAL && actual_format == 32 &&
            count == 1 && value && *(unsigned long *)value == pid;
        if (value) XFree(value);
        if (match) return parent;
    }
    Window root, ancestor, *children = NULL; unsigned count = 0;
    Window found = None;
    if (XQueryTree(display, parent, &root, &ancestor, &children, &count)) {
        for (unsigned i = 0; i < count && found == None; ++i)
            found = find_window(display, children[i], pid, width, height, pid_atom);
    }
    if (children) XFree(children);
    return found;
}

int main(int argc, char **argv) {
    Display *display = XOpenDisplay(NULL);
    if (!display) { fputs("capture cannot open DISPLAY\n", stderr); return 1; }
    if (argc == 2 && strcmp(argv[1], "--check") == 0) { XCloseDisplay(display); return 0; }
    if (argc != 5) {
        fputs("usage: capture_x11 PID WIDTH HEIGHT OUTPUT.ppm | --check\n", stderr);
        XCloseDisplay(display); return 2;
    }
    char *end; errno = 0;
    unsigned long pid = strtoul(argv[1], &end, 10);
    if (errno || *end || !pid) return 2;
    unsigned long width = strtoul(argv[2], &end, 10);
    if (errno || *end || !width || width > 16384) return 2;
    unsigned long height = strtoul(argv[3], &end, 10);
    if (errno || *end || !height || height > 16384) return 2;
    Window window = find_window(display, DefaultRootWindow(display), pid,
        (unsigned)width, (unsigned)height, XInternAtom(display, "_NET_WM_PID", False));
    if (!window) { fputs("no viewable window with exact PID/extent\n", stderr); XCloseDisplay(display); return 3; }
    XSync(display, False);
    XImage *image = XGetImage(display, window, 0, 0, (unsigned)width, (unsigned)height,
        AllPlanes, ZPixmap);
    if (!image) { fputs("XGetImage failed\n", stderr); XCloseDisplay(display); return 4; }
    // A diagnostic capture must never replace an existing file or symlink.
    FILE *output = fopen(argv[4], "wbx");
    if (!output) { perror("capture output"); XDestroyImage(image); XCloseDisplay(display); return 4; }
    fprintf(output, "P6\n%lu %lu\n255\n", width, height);
    unsigned char *row = malloc(width * 3);
    if (!row) return 4;
    int failed = 0;
    for (unsigned y = 0; y < height && !failed; ++y) {
        for (unsigned x = 0; x < width; ++x) {
            unsigned long pixel = XGetPixel(image, (int)x, (int)y);
            row[x * 3] = (unsigned char)component(pixel, image->red_mask);
            row[x * 3 + 1] = (unsigned char)component(pixel, image->green_mask);
            row[x * 3 + 2] = (unsigned char)component(pixel, image->blue_mask);
        }
        failed = fwrite(row, 3, width, output) != width;
    }
    free(row);
    if (fclose(output)) failed = 1;
    XDestroyImage(image); XCloseDisplay(display);
    if (failed) return 4;
    printf("{\"schema_version\":1,\"capture_method\":\"XGetImage_PPM_RGB\","
        "\"evidence_class\":\"VIRTUAL_WINDOW\",\"synthetic_not_game\":true,"
        "\"pid\":%lu,\"window\":%lu,\"width\":%lu,\"height\":%lu,"
        "\"alpha_verified\":false}\n", pid, window, width, height);
    return 0;
}
