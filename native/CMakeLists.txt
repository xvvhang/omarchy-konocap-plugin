cmake_minimum_required(VERSION 3.27)
project(konochi-konocap VERSION 1.1.0 LANGUAGES CXX)
# Preserve the native library name for lifecycle/cache compatibility.
set(CMAKE_CXX_STANDARD 23)
add_library(focus-titlebars SHARED main.cpp barDeco.cpp BarPassElement.cpp appName.cpp)
set_target_properties(focus-titlebars PROPERTIES PREFIX "")
target_compile_options(focus-titlebars PRIVATE -fno-gnu-unique)
# The stock plugin remains loaded. Isolate every exported fork symbol so ELF
# interposition cannot bind a decoration to the stock plugin's state or vtable.
target_compile_definitions(focus-titlebars PRIVATE
  COmarchyFloatingHyprBar=CFocusTitlebar
  COmarchyFloatingBarPassElement=CFocusTitlebarPassElement
  SOmarchyFloatingGlobalState=SFocusTitlebarState
  SOmarchyFloatingHyprButton=SFocusTitlebarButton
  OMARCHY_FLOATING_PHANDLE=FOCUS_TITLEBAR_HANDLE
  g_pOmarchyFloatingGlobalState=g_pFocusTitlebarState
  omarchyAppName=focusTitlebarAppName
)
find_package(PkgConfig REQUIRED)
pkg_check_modules(deps REQUIRED IMPORTED_TARGET
  hyprland libdrm libinput libudev pixman-1 wayland-server xkbcommon)
target_link_libraries(focus-titlebars PRIVATE rt PkgConfig::deps)
