# appleton

Windows runner for macOS on Apple Silicon

Edit `appleton.cfg` to point at your Wine executable. Every setting supports an `APPLETON_` environment override, such as `APPLETON_WINE_X86_64`. Run with native ARM Python; x86_64 Wine requires Rosetta 2 already installed.

```sh
chmod +x appleton
./appleton --dry-run '/path/to/game.exe' '/path/to/game'
./appleton '/path/to/game.exe' '/path/to/game' --fullscreen
```

Options go BEFORE the executable. Remaining arguments after the game directory go to the Windows program. The game directory is the working directory. Prefixes default to `~/Library/Application Support/appleton/prefixes`, keyed by game directory, runtime architecture, and graphics backend. Execution checks APFS with `diskutil`, runs `wineboot -u` for new prefixes, and returns the game's exit code. `--prefix PATH` selects a dedicated empty or matching appleton prefix.

## Graphics

The default `wine` backend uses Wine's own graphics implementation.

```sh
./appleton --graphics dxvk '/path/to/game.exe' '/path/to/game'
./appleton --graphics d3dmetal '/path/to/game.exe' '/path/to/game'
```

For DXVK, set `dxvk_x64` to a directory containing `dxgi.dll`, `d3d11.dll`, `d3d10core.dll`, and `d3d9.dll`. Set `moltenvk` to the matching macOS dynamic library. Optionally set `vulkan_icd` to a Vulkan loader ICD JSON file. For Direct3D 12, set `vkd3d_x64` to a directory containing `d3d12.dll` and `d3d12core.dll`. Use macOS-compatible builds: upstream DXVK/VKD3D versions can require Vulkan features unavailable through your MoltenVK build. This runner does not supply those features. See [MoltenVK](https://github.com/KhronosGroup/MoltenVK).

For D3DMetal, use a compatible GPTK-enabled Wine build, set `d3dmetal_x64` to its Windows DLL directory containing `dxgi.dll`, `d3d11.dll`, and `d3d12.dll`, and set `d3dmetal_lib` to the directory containing its native libraries and `D3DMetal.framework`. Obtain components separately from [Apple's Game Porting Toolkit](https://developer.apple.com/games/game-porting-toolkit/).

The runner copies DLLs into prefix `system32`, sets native DLL overrides, and supplies Darwin loader paths after `arch` through `env`. Executable-local DLLs may take precedence. A prefix cannot be switched between runtimes or backends.

ARM64, ARM64EC, and ARM64X PE headers route to `wine_arm64`. the supplied Wine build must support the PE format, Windows ABI, and any mixed x86_64 code. Rosettadoes not provide ARM64EC Wine support!!!!. ARM graphics require matching `_arm64` DLL directories; x64 DLLs are not substituted. 32-bit PE executables are unsupported.

## test

With an x86_64 MinGW-w64 cross compiler and Wine installed:

```sh
x86_64-w64-mingw32-gcc smoke/hello.c -o smoke/hello.exe
APPLETON_WINE_X86_64='/absolute/path/to/wine64' ./appleton --graphics wine smoke/hello.exe smoke
```

Expected stdout: `appleton smoke: Windows execution OK`, exit status `0`. This tests Windows execution without graphics dependencies. An existing 64-bit Windows console executable can also be supplied directly.

```sh
python3 -m unittest discover -s tests -v
```
