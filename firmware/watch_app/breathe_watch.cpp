// BreatheDetroit watch app: runs ON the FREE-WILi, no laptop needed.
//
// The BottleNose (ESP32-C6, WiFi) sends lines over the Orca UART:
//   "S <risk> <tvoc> <puffs>"  live status   risk: 0 green, 1 yellow, 2 red, 3 unknown
//   "D <tvoc>"                 history point (fills the graph at start-up)
//   "M <text>"                 status message (WIFI..., ONLINE, AWS ERR)
//   "A" / "E"                  puff saved / puff failed
// The watch sends "P\n" when a puff button (yellow / green / blue) is pressed.
// RED button exits the app.

#include <fwwasm.h>
#include <stdint.h>

namespace {

constexpr int PANEL = 0;
constexpr int CTL_RISK = 0;
constexpr int CTL_TVOC = 1;
constexpr int CTL_PUFFS = 2;
constexpr int CTL_STATUS = 3;
constexpr int CTL_PLOT = 4;
constexpr int PLOT_MAX = 1000;
constexpr int NUM_LEDS = 7;
constexpr unsigned int OFFLINE_MS = 12000;

int g_risk = 3;
int g_tvoc = 0;
int g_puffs = 0;
unsigned int g_last_status_ms = 0;
unsigned int g_flash_until_ms = 0;
bool g_offline_shown = false;

char g_line[96];
int g_line_len = 0;

// ---- tiny string helpers (keep the app small; no printf) ----
int str_copy(char* dst, int pos, const char* src)
{
    while (*src) dst[pos++] = *src++;
    dst[pos] = 0;
    return pos;
}

int int_to_str(char* dst, int pos, int value)
{
    char tmp[12];
    int n = 0;
    bool neg = value < 0;
    unsigned int v = neg ? static_cast<unsigned int>(-value) : static_cast<unsigned int>(value);
    do {
        tmp[n++] = static_cast<char>('0' + static_cast<int>(v % 10u));
        v /= 10u;
    } while (v != 0u && n < 11);
    if (neg) dst[pos++] = '-';
    while (n > 0) dst[pos++] = tmp[--n];
    dst[pos] = 0;
    return pos;
}

// Reads the next integer from s starting at *i. Returns false if none.
bool next_int(const char* s, int* i, int* out)
{
    while (s[*i] == ' ') (*i)++;
    bool neg = false;
    if (s[*i] == '-') { neg = true; (*i)++; }
    if (s[*i] < '0' || s[*i] > '9') return false;
    int v = 0;
    while (s[*i] >= '0' && s[*i] <= '9') {
        v = v * 10 + (s[*i] - '0');
        (*i)++;
    }
    *out = neg ? -v : v;
    return true;
}

// ---- display ----
void risk_rgb(int risk, int* r, int* g, int* b)
{
    if (risk == 0) { *r = 40; *g = 200; *b = 90; }
    else if (risk == 1) { *r = 240; *g = 190; *b = 40; }
    else if (risk == 2) { *r = 230; *g = 60; *b = 60; }
    else { *r = 90; *g = 120; *b = 230; }
}

const char* risk_text(int risk)
{
    if (risk == 0) return "AIR GOOD";
    if (risk == 1) return "AIR FAIR";
    if (risk == 2) return "AIR BAD";
    return "NO DATA";
}

void set_status(const char* text)
{
    setControlValueText(PANEL, CTL_STATUS, text);
}

void show_leds()
{
    int r, g, b;
    risk_rgb(g_risk, &r, &g, &b);
    int lit = (g_tvoc * NUM_LEDS + PLOT_MAX / 2) / PLOT_MAX;
    if (lit < 1) lit = 1;
    if (lit > NUM_LEDS) lit = NUM_LEDS;
    if (g_risk == 3) lit = 1;
    for (int i = 0; i < NUM_LEDS; i++) {
        if (i < lit) setBoardLED(i, r / 4, g / 4, b / 4, 6000, ledsimplevalue);
        else setBoardLED(i, 0, 0, 0, 6000, ledsimplevalue);
    }
}

void show_status()
{
    setControlValueText(PANEL, CTL_RISK, risk_text(g_risk));
    setControlValue(PANEL, CTL_TVOC, g_tvoc);
    char buf[24];
    int p = str_copy(buf, 0, "PUFFS ");
    int_to_str(buf, p, g_puffs);
    setControlValueText(PANEL, CTL_PUFFS, buf);
    show_leds();
}

void add_point(int tvoc)
{
    int v = tvoc > PLOT_MAX ? PLOT_MAX : (tvoc < 0 ? 0 : tvoc);
    setPlotData(0, 0, v);
}

void build_screen()
{
    addPanel(PANEL, 1, 0, 0, 0, 10, 12, 20, 1);
    addControlText(PANEL, CTL_RISK, 10, 8, 1, 2, 240, 240, 240, "STARTING");
    addControlNumber(PANEL, CTL_TVOC, 1, 210, 8, 100, 2, 1, 10, 12, 20, 0, 0, 0, 1);
    addControlText(PANEL, CTL_PUFFS, 10, 44, 1, 1, 170, 180, 210, "PUFFS 0");
    addControlText(PANEL, CTL_STATUS, 150, 44, 1, 1, 120, 130, 160, "WIFI...");
    addControlPlotData(0, 240, 190, 40);
    addControlPlot(PANEL, CTL_PLOT, 1, 1, 10, 72, 300, 125, 0, PLOT_MAX, 20, 24, 36);
    setPanelMenuText(PANEL, 1, "PUFF");
    setPanelMenuText(PANEL, 2, "PUFF");
    setPanelMenuText(PANEL, 3, "PUFF");
    setPanelMenuText(PANEL, 4, "EXIT");
    showPanel(PANEL);
}

// ---- UART protocol ----
void send_puff()
{
    unsigned char msg[2] = { 'P', '\n' };
    UARTDataWrite(msg, 2);
    setControlValueText(PANEL, CTL_RISK, "PUFF...");
    for (int i = 0; i < NUM_LEDS; i++) setBoardLED(i, 60, 60, 60, 400, ledflashfade);
    g_flash_until_ms = millis() + 2500u;
}

void handle_line(const char* s)
{
    int i = 1;
    if (s[0] == 'S') {
        int risk, tvoc, puffs;
        if (!next_int(s, &i, &risk) || !next_int(s, &i, &tvoc) || !next_int(s, &i, &puffs)) return;
        g_risk = (risk < 0 || risk > 3) ? 3 : risk;
        g_tvoc = tvoc;
        g_puffs = puffs;
        g_last_status_ms = millis();
        if (g_offline_shown) { set_status("ONLINE"); g_offline_shown = false; }
        add_point(tvoc);
        if (millis() > g_flash_until_ms) show_status();
    } else if (s[0] == 'D') {
        int tvoc;
        if (next_int(s, &i, &tvoc)) add_point(tvoc);
    } else if (s[0] == 'M') {
        set_status(s[1] == ' ' ? s + 2 : s + 1);
    } else if (s[0] == 'A') {
        setControlValueText(PANEL, CTL_RISK, "PUFF SAVED");
        g_puffs++;
        g_flash_until_ms = millis() + 2000u;
    } else if (s[0] == 'E') {
        setControlValueText(PANEL, CTL_RISK, "PUFF FAILED");
        g_flash_until_ms = millis() + 2000u;
    }
}

void read_uart()
{
    unsigned char buf[64];
    int count = UARTDataRxCount();
    while (count > 0) {
        int want = count > 64 ? 64 : count;
        int got = UARTDataRead(buf, want);
        if (got <= 0) break;
        for (int k = 0; k < got; k++) {
            char c = static_cast<char>(buf[k]);
            if (c == '\n' || c == '\r') {
                if (g_line_len > 0) {
                    g_line[g_line_len] = 0;
                    handle_line(g_line);
                }
                g_line_len = 0;
            } else if (c >= 32 && c < 127 && g_line_len < static_cast<int>(sizeof(g_line)) - 1) {
                g_line[g_line_len++] = c;
            }
        }
        count = UARTDataRxCount();
    }
}

}  // namespace

int main()
{
    build_screen();
    show_leds();
    unsigned char ev[FW_GET_EVENT_DATA_MAX];
    bool running = true;
    unsigned int last_flash_end_check = 0;
    while (running) {
        read_uart();

        while (hasEvent()) {
            int type = getEventData(ev);
            if (type == FWGUI_EVENT_YELLOW_BUTTON || type == FWGUI_EVENT_GREEN_BUTTON ||
                type == FWGUI_EVENT_BLUE_BUTTON) {
                send_puff();
            } else if (type == FWGUI_EVENT_RED_BUTTON) {
                running = false;
            }
        }

        unsigned int now = millis();
        if (g_flash_until_ms != 0u && now > g_flash_until_ms && now - last_flash_end_check > 200u) {
            g_flash_until_ms = 0u;
            show_status();
            last_flash_end_check = now;
        }
        if (g_last_status_ms != 0u && now - g_last_status_ms > OFFLINE_MS && !g_offline_shown) {
            set_status("NO SIGNAL");
            g_offline_shown = true;
        }
        waitms(20);
    }
    for (int i = 0; i < NUM_LEDS; i++) setBoardLED(i, 0, 0, 0, 10, ledsimplevalue);
    exitToMainAppMenu();
    return 0;
}
