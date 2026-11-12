# BMM — Balatro Mod Manager

A Windows mod manager for Balatro (Steamodded + Lovely) with a glass UI built on [Raven](https://github.com/oscar-soirey/Raven).

- **Installed**: every mod in `%APPDATA%\Balatro\Mods` with its id, version, author and description. You can enable or disable a mod (double-click it), see missing dependencies and conflicts, and update, reinstall, open or remove a mod.
- **Browse**: the [Balatro Mod Index](https://github.com/skyline69/balatro-mod-index) (~440 mods), with search, category filter, thumbnails, Markdown descriptions and one-click install/update.
- **Install from GitHub**: `owner/repo`, a repo/tag URL, or a direct `.zip` link. Mods installed this way are checked against the repo's latest GitHub release for updates.
- **Updates**: installed mods are matched to the index, or to the repo they came from. *Update all* appears when updates are available.
- Buttons to open the Mods folder and the newest Lovely log.

## Run

Double-click `run.bat`. On first run it creates `.venv` and installs `raven-gui` (a prebuilt Windows wheel; no compiler needed). Requires Python 3.8+ and a Vulkan-capable GPU driver.

CLI without the window:

```
python modman.py --list    # installed mods, problems, updates (uses the cached index)
python modman.py --test    # self-check
```

## How it works

- **Disable** = a `.lovelyignore` file in the mod folder, which is the convention Steamodded's loader and Lovely both honour. Enabling also removes the folder from `Mods\lovely\blacklist.txt`.
- **Install** downloads the archive to a temp dir, finds the mod folder(s) (metadata JSON, a `STEAMODDED HEADER` Lua file, or `lovely.toml`), and copies them into Mods. A previous copy of the same mod id is replaced, but only after it has been moved to `%LOCALAPPDATA%\BalatroModManager\backups`. The disabled state is kept.
- **Remove** moves the mod to the same backups folder (click twice). Nothing is permanently deleted.
- Update checks compare dotted versions only. About two thirds of index entries track commits (their "version" is a hash or a date), so for those use *Reinstall latest*.
- Cache: `%LOCALAPPDATA%\BalatroModManager` (index, thumbnails, install sources, backups). The index refreshes on start if it's older than 6 hours, or when you press *Refresh*.

Set `BALATRO_MODS_DIR` to manage a different Mods folder (handy for testing).
