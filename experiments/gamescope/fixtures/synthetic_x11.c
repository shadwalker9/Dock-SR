// DockSR-owned synthetic test fixture. This is not a game or a benchmark.
#define _POSIX_C_SOURCE 200809L
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

enum { WIDTH = 1280, HEIGHT = 720 };
static volatile sig_atomic_t running = 1;
static void stop(int signal_number) { (void)signal_number; running = 0; }

static unsigned long channel(unsigned value, unsigned long mask) {
    unsigned shift = 0;
    if (!mask) return 0;
    while (!(mask & 1)) { mask >>= 1; ++shift; }
    return ((value * mask + 127) / 255) << shift;
}

int main(void) {
    signal(SIGTERM, stop); signal(SIGINT, stop);
    Display *display = XOpenDisplay(NULL);
    if (!display) { fputs("synthetic fixture cannot open DISPLAY\n", stderr); return 1; }
    const int screen = DefaultScreen(display);
    Visual *visual = DefaultVisual(display, screen);
    const unsigned depth = (unsigned)DefaultDepth(display, screen);
    Window window = XCreateSimpleWindow(display, RootWindow(display, screen),
        0, 0, WIDTH, HEIGHT, 0, 0, 0);
    XStoreName(display, window, "DockSR owned synthetic fixture (not a game)");
    XClassHint class_hint = {"docksr-synthetic", "DockSRSyntheticFixture"};
    XSetClassHint(display, window, &class_hint);
    XSizeHints size = {0};
    size.flags = PSize | PMinSize | PMaxSize;
    size.width = size.min_width = size.max_width = WIDTH;
    size.height = size.min_height = size.max_height = HEIGHT;
    XSetWMNormalHints(display, window, &size);
    unsigned long pid = (unsigned long)getpid();
    Atom pid_atom = XInternAtom(display, "_NET_WM_PID", False);
    XChangeProperty(display, window, pid_atom, XA_CARDINAL, 32,
        PropModeReplace, (unsigned char *)&pid, 1);
    XSelectInput(display, window, StructureNotifyMask | ExposureMask);
    XImage *image = XCreateImage(display, visual, depth, ZPixmap, 0, NULL,
        WIDTH, HEIGHT, 32, 0);
    if (!image) { fputs("XCreateImage failed\n", stderr); XCloseDisplay(display); return 1; }
    image->data = calloc((size_t)image->bytes_per_line, HEIGHT);
    if (!image->data) { XDestroyImage(image); XCloseDisplay(display); return 1; }
    // Fixed pixels include one-pixel diagonals, steps, checkerboards and ramps.
    // Repeated commits always contain these identical pixels, with no counter UI.
    for (unsigned y = 0; y < HEIGHT; ++y) for (unsigned x = 0; x < WIDTH; ++x) {
        unsigned r = x * 255 / (WIDTH - 1), g = y * 255 / (HEIGHT - 1);
        unsigned b = ((x / 17 + y / 17) & 1) ? 208 : 32;
        if ((x * 9 / 16 == y) || (x * 9 / 16 + 1 == y)) r = g = b = 255;
        if (x > 450 && x < 830 && y > 240 && y < 480) {
            r = ((x / 3 + y / 3) & 1) ? 235 : 20;
            g = 90; b = 120;
        }
        const unsigned long pixel = channel(r, visual->red_mask) |
            channel(g, visual->green_mask) | channel(b, visual->blue_mask);
        XPutPixel(image, (int)x, (int)y, pixel);
    }
    Pixmap fixed = XCreatePixmap(display, window, WIDTH, HEIGHT, depth);
    GC gc = XCreateGC(display, fixed, 0, NULL);
    XPutImage(display, fixed, gc, image, 0, 0, 0, 0, WIDTH, HEIGHT);
    XDestroyImage(image);
    XMapRaised(display, window);
    XSync(display, False);
    XWindowAttributes attributes;
    XGetWindowAttributes(display, window, &attributes);
    printf("DOCKSR_FIXTURE {\"schema_version\":1,\"kind\":\"SYNTHETIC_NOT_GAME\","
        "\"pid\":%ld,\"window\":%lu,\"width\":%d,\"height\":%d,"
        "\"opaque\":true,\"pattern\":\"owned_fixed_v1\"}\n",
        (long)getpid(), window, attributes.width, attributes.height);
    fflush(stdout);
    const struct timespec interval = {0, 100000000};
    while (running) {
        while (XPending(display)) {
            XEvent event; XNextEvent(display, &event);
            if (event.type == DestroyNotify) running = 0;
            if (event.type == ConfigureNotify &&
                (event.xconfigure.width != WIDTH || event.xconfigure.height != HEIGHT))
                XResizeWindow(display, window, WIDTH, HEIGHT);
        }
        if (!running) break;
        XCopyArea(display, fixed, window, gc, 0, 0, WIDTH, HEIGHT, 0, 0);
        XSync(display, False);
        nanosleep(&interval, NULL);
    }
    XFreeGC(display, gc); XFreePixmap(display, fixed);
    XDestroyWindow(display, window); XCloseDisplay(display);
    return 0;
}
