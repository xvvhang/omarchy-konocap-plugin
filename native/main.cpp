#include "barDeco.hpp"
#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/animation/AnimationManager.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/rule/windowRule/WindowRuleEffectContainer.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <sys/syscall.h>
#include <unistd.h>
#include <algorithm>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

namespace {
bool active = false, syncing = false, captured = false, stockRequested = false;
int ownerPid = 0, ownerFd = -1;
wl_event_source *ownerSource = nullptr;

bool stockAvailable() {
  return Config::mgr()->getConfigValue("plugin:hyprbars:enabled").dataptr != nullptr;
}

void refreshDecorations() {
  for (auto &bar : g_pOmarchyFloatingGlobalState->bars) {
    if (!bar) continue;
    bar->updateRules();
    bar->onConfigReloaded();
  }
  // Reposition BOTH decorations: stock must give back its space immediately,
  // and on release the focus bar must give that space back to stock.
  for (auto &window : Desktop::windowState()->windows()) {
    if (!validMapped(window)) continue;
    for (auto &decoration : window->m_windowDecorations)
      g_pDecorationPositioner->repositionDeco(decoration.get());
    window->updateWindowDecos();
    g_pHyprRenderer->damageWindow(window);
  }
  for (auto &monitor : State::monitorState()->monitors())
    monitor->m_scheduledRecalc = true;
}

void rebuildButtons() {
  const auto &config = g_pOmarchyFloatingGlobalState->config;
  const CHyprColor background{static_cast<uint64_t>(config.barColor->value())};
  const CHyprColor foreground{static_cast<uint64_t>(config.textColor->value())};
  g_pOmarchyFloatingGlobalState->buttons = {
    {"hyprctl dispatch 'hl.dsp.window.close({ window = \"address:%WINDOW%\" })'", true, foreground, background, 20, "×"},
    {"hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = \"maximized\", action = \"toggle\", window = \"address:%WINDOW%\" })'", true, foreground, background, 20, "□"},
    {"omarchy-hyprland-window-minimize %WINDOW%", true, foreground, background, 20, "−"},
  };
}

void syncStock(bool force = false) {
  if (!active || syncing || !stockAvailable()) return;
  CConfigValue<Config::BOOL> stockEnabled("plugin:hyprbars:enabled");
  if (!force && captured && !*stockEnabled) return;
  syncing = true;
  if (!captured || *stockEnabled) stockRequested = *stockEnabled;
  captured = true;
  // Session-only state through Hyprland's public config-value API. No file,
  // load-path interception, configuration reload, or stock-plugin unload.
  *stockEnabled.ptr() = false;
  g_pOmarchyFloatingGlobalState->config.enabled->data = stockRequested;
  Animation::mgr()->addBezierWithName("focusTitlebar", {0.33, 1.0}, {0.68, 1.0});
  rebuildButtons();
  refreshDecorations();
  syncing = false;
}

void clearOwner() {
  if (ownerSource) wl_event_source_remove(ownerSource);
  ownerSource = nullptr;
  if (ownerFd >= 0) close(ownerFd);
  ownerFd = -1;
  ownerPid = 0;
}

void deactivate() {
  clearOwner();
  if (!active) return;
  active = false;
  g_pOmarchyFloatingGlobalState->config.enabled->data = false;
  if (captured && stockAvailable()) {
    CConfigValue<Config::BOOL> stockEnabled("plugin:hyprbars:enabled");
    *stockEnabled.ptr() = stockRequested;
  }
  captured = false;
  refreshDecorations();
}

int ownerDied(int, uint32_t, void *) {
  // pidfd readiness is event-driven and also covers SIGKILL. If the Omarchy
  // service disappears, restore stock even if no cleanup code got to run.
  deactivate();
  return 0;
}

int activateLua(lua_State *L) {
  const int pid = luaL_checkinteger(L, 1);
  const auto show = std::clamp<Config::INTEGER>(luaL_optinteger(L, 2, 180), 0, 290);
  const auto hide = std::clamp<Config::INTEGER>(luaL_optinteger(L, 3, 120), 0, 290);
  if (pid <= 1) return luaL_error(L, "invalid owner pid");
  const int fd = syscall(SYS_pidfd_open, pid, 0);
  if (fd < 0) return luaL_error(L, "could not monitor plugin owner");
  clearOwner();
  ownerFd = fd;
  ownerPid = pid;
  ownerSource = wl_event_loop_add_fd(g_pCompositor->m_wlEventLoop, fd, WL_EVENT_READABLE, ownerDied, nullptr);
  if (!ownerSource) {
    clearOwner();
    return luaL_error(L, "could not register plugin owner");
  }
  active = true;
  g_pOmarchyFloatingGlobalState->config.focusShowDuration->data = show;
  g_pOmarchyFloatingGlobalState->config.focusHideDuration->data = hide;
  syncStock(true);
  return 0;
}

int deactivateLua(lua_State *L) {
  const int pid = luaL_checkinteger(L, 1);
  if (pid == ownerPid) deactivate();
  return 0;
}

int statusLua(lua_State *L) {
  lua_newtable(L);
  lua_pushboolean(L, active); lua_setfield(L, -2, "active");
  lua_pushinteger(L, ownerPid); lua_setfield(L, -2, "owner");
  lua_pushboolean(L, g_pOmarchyFloatingGlobalState->config.enabled->value()); lua_setfield(L, -2, "enabled");
  return 1;
}

template <typename T, typename V> auto stockValue(const char *name, V fallback) {
  auto value = makeShared<T>(name, "", fallback);
  // Bind to the STOCK plugin's live option, without registering or owning it.
  value->commence();
  return value;
}

void newWindow(PHLWINDOW window) {
  syncStock();
  if (window->m_X11DoesntWantBorders) return;
  if (std::ranges::any_of(window->m_windowDecorations, [](const auto &d) { return d->getDisplayName() == "FocusTitlebar"; })) return;
  auto bar = makeUnique<COmarchyFloatingHyprBar>(window);
  g_pOmarchyFloatingGlobalState->bars.emplace_back(bar);
  bar->m_self = bar;
  HyprlandAPI::addWindowDecoration(OMARCHY_FLOATING_PHANDLE, window, std::move(bar));
}
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
  if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
    throw std::runtime_error("Focus Titlebars: Hyprland ABI mismatch");
  if (!stockAvailable())
    throw std::runtime_error("Focus Titlebars: stock Omarchy titlebars must be loaded first");
  OMARCHY_FLOATING_PHANDLE = handle;
  active = syncing = captured = stockRequested = false;
  g_pOmarchyFloatingGlobalState = makeUnique<SOmarchyFloatingGlobalState>();
  auto &state = *g_pOmarchyFloatingGlobalState;
  auto effects = Desktop::Rule::windowEffects();
  state.nobarRuleIdx = effects->get("hyprbars:no_bar").value();
  state.barColorRuleIdx = effects->get("hyprbars:bar_color").value();
  state.titleColorRuleIdx = effects->get("hyprbars:title_color").value();
  auto &c = state.config;
  using namespace Config::Values;
  c.barColor = stockValue<CColorValue>("plugin:hyprbars:bar_color", 0x88333333);
  c.textColor = stockValue<CColorValue>("plugin:hyprbars:col.text", 0xffffffff);
  c.inactiveBarColor = stockValue<CColorValue>("plugin:hyprbars:bar_color_inactive", 0);
  c.inactiveButtonColor = stockValue<CColorValue>("plugin:hyprbars:inactive_button_color", 0);
  c.buttonBorderColor = stockValue<CColorValue>("plugin:hyprbars:button_border_color", 0);
  c.barHeight = stockValue<CIntValue>("plugin:hyprbars:bar_height", 30);
  c.barTextSize = stockValue<CIntValue>("plugin:hyprbars:bar_text_size", 12);
  c.barTextWeight = stockValue<CFontWeightValue>("plugin:hyprbars:bar_text_weight", 400);
  c.barPadding = stockValue<CIntValue>("plugin:hyprbars:bar_padding", 10);
  c.barButtonPadding = stockValue<CIntValue>("plugin:hyprbars:bar_button_padding", 8);
  c.buttonRounding = stockValue<CIntValue>("plugin:hyprbars:button_rounding", 0);
  c.buttonBorderSize = stockValue<CIntValue>("plugin:hyprbars:button_border_size", 0);
  c.barBlur = stockValue<CBoolValue>("plugin:hyprbars:bar_blur", false);
  c.barTitleEnabled = stockValue<CBoolValue>("plugin:hyprbars:bar_title_enabled", true);
  c.barPartOfWindow = stockValue<CBoolValue>("plugin:hyprbars:bar_part_of_window", true);
  c.barPrecedenceOverBorder = stockValue<CBoolValue>("plugin:hyprbars:bar_precedence_over_border", true);
  c.iconOnHover = stockValue<CBoolValue>("plugin:hyprbars:icon_on_hover", false);
  c.barTextFont = stockValue<CStringValue>("plugin:hyprbars:bar_text_font", "monospace");
  c.barTextAlign = stockValue<CStringValue>("plugin:hyprbars:bar_text_align", "left");
  c.barButtonsAlignment = stockValue<CStringValue>("plugin:hyprbars:bar_buttons_alignment", "right");
  c.onDoubleClick = stockValue<CStringValue>("plugin:hyprbars:on_double_click", "");
  c.workspaceTag = stockValue<CStringValue>("plugin:hyprbars:workspace_tag", "");
  c.enabled = makeShared<FocusLocalValue<bool>>(false);
  c.focusOnly = makeShared<FocusLocalValue<bool>>(true);
  c.focusShowDuration = makeShared<FocusLocalValue<Config::INTEGER>>(180);
  c.focusHideDuration = makeShared<FocusLocalValue<Config::INTEGER>>(120);
  Animation::mgr()->addBezierWithName("focusTitlebar", {0.33, 1.0}, {0.68, 1.0});

  HyprlandAPI::addLuaFunction(handle, "focus_titlebars", "activate", activateLua);
  HyprlandAPI::addLuaFunction(handle, "focus_titlebars", "deactivate", deactivateLua);
  HyprlandAPI::addLuaFunction(handle, "focus_titlebars", "status", statusLua);
  static auto opened = Event::bus()->m_events.window.open.listen([](PHLWINDOW w) { newWindow(w); });
  static auto rules = Event::bus()->m_events.window.updateRules.listen([](PHLWINDOW w) {
    syncStock();
    for (auto &bar : g_pOmarchyFloatingGlobalState->bars)
      if (bar && bar->getOwner() == w) { bar->updateRules(); w->updateWindowDecos(); break; }
  });
  static auto pre = Event::bus()->m_events.config.preReload.listen([] { captured = false; });
  static auto reloaded = Event::bus()->m_events.config.reloaded.listen([] { syncStock(true); });
  static auto properties = Event::bus()->m_events.config.props_refreshed.listen([](bool) { syncStock(true); });
  for (auto &window : Desktop::windowState()->windows())
    if (validMapped(window)) newWindow(window);
  return {"focus-titlebars", "Focus-only animated floating titlebars (Omarchy managed)", "alec", "1.0.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
  deactivate();
  g_pHyprRenderer->m_renderPass.removeAllOfType("CFocusTitlebarPassElement");
  // Stock owns its options, Lua functions, rules, buttons, and .so. Leave all
  // of those intact so disabling this service immediately restores stock.
}
