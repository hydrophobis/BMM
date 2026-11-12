"""Balatro Mod Manager window (Raven GUI, glass theme). Start with run.bat.

Debug: app.pyw --shot out.png [--tab 1]  renders, saves a screenshot and exits.
"""
import ctypes, os, queue, struct, sys, threading, time, traceback, zlib
from pathlib import Path

import raven as r
import modman as mm

XML = """
<Window Title="Balatro Mod Manager" Width="1200" Height="760" MinWidth="940" MinHeight="580">
  <VBox Spacing="12" Slot.Padding="18">
    <Border Material="TintedGlass" CornerRadius="22" Padding="10,8" Shadow="18" Appear="FlyDown">
      <HBox Spacing="10">
        <Label TextSize="22" Slot.VAlign="Center" Slot.Padding="8,0,0,0">Balatro Mod Manager</Label>
        <Spacer Slot.Fill="1"/>
        <TextInput Name="search" Placeholder="Search" Width="240"/>
        <Button Text="Refresh" OnClicked="app.refresh" Tooltip="Rescan the Mods folder and re-download the mod index"/>
        <Button Text="Mods folder" OnClicked="app.open_mods"/>
        <Button Text="Lovely log" OnClicked="app.open_log" Tooltip="Open the newest Lovely log"/>
      </HBox>
    </Border>
    <TabView Name="tabs" Slot.Fill="1">
      <HBox Slot.Title="Installed" Spacing="12" Slot.Padding="0,10,0,0">
        <Border Material="FrostedGlass" CornerRadius="20" Padding="8" Width="400" Appear="FlyRight">
          <ListView Name="installed"/>
        </Border>
        <Border Material="FrostedGlass" CornerRadius="20" Padding="22" Slot.Fill="1" Appear="FlyLeft">
          <ScrollBox>
            <VBox Spacing="10">
              <Label Name="i_title" TextSize="28">No mod selected</Label>
              <Label Name="i_sub" Opacity="0.7" Wrap="true"/>
              <Label Name="i_update" Color="#7CC4FF" Wrap="true" Visibility="Collapsed"/>
              <Label Name="i_issues" Color="#FF7A6E" Wrap="true" Visibility="Collapsed"/>
              <WrapBox Spacing="8" Slot.Padding="0,6,0,6">
                <Button Name="i_toggle" Text="Disable" Style="Primary" OnClicked="app.toggle"/>
                <Button Name="i_install" Text="Update" OnClicked="app.update_selected" Visibility="Collapsed"/>
                <Button Text="Open folder" OnClicked="app.open_folder"/>
                <Button Name="i_remove" Text="Remove" OnClicked="app.remove" Tooltip="Moves the mod to the backups folder"/>
              </WrapBox>
              <Separator/>
              <Label Name="i_desc" Wrap="true" Markdown="true" Selectable="true"/>
            </VBox>
          </ScrollBox>
        </Border>
      </HBox>
      <HBox Slot.Title="Browse" Spacing="12" Slot.Padding="0,10,0,0">
        <Border Material="FrostedGlass" CornerRadius="20" Padding="8" Width="400">
          <VBox Spacing="8">
            <ComboBox Name="category"/>
            <ListView Name="browse" Slot.Fill="1"/>
          </VBox>
        </Border>
        <Border Material="FrostedGlass" CornerRadius="20" Padding="22" Slot.Fill="1">
          <ScrollBox>
            <VBox Spacing="10">
              <Image Name="b_thumb" Stretch="Fit" Height="220" CornerRadius="14" Visibility="Collapsed"/>
              <Label Name="b_title" TextSize="28">Pick a mod</Label>
              <Label Name="b_sub" Opacity="0.7" Wrap="true"/>
              <Label Name="b_status" Color="#7CC4FF" Wrap="true"/>
              <WrapBox Spacing="8" Slot.Padding="0,6,0,6">
                <Button Name="b_install" Text="Install" Style="Primary" OnClicked="app.install_selected"/>
                <Button Name="b_repo" Text="Open repo" OnClicked="app.open_repo"/>
              </WrapBox>
              <Separator/>
              <Label Name="b_desc" Wrap="true" Markdown="true" Selectable="true"/>
            </VBox>
          </ScrollBox>
        </Border>
      </HBox>
    </TabView>
    <Border Material="TintedGlass" CornerRadius="22" Padding="10,8" Shadow="18" Appear="FlyUp">
      <HBox Spacing="10">
        <TextInput Name="url" Placeholder="Install from GitHub: owner/repo, a repo or release URL, or a .zip link" Slot.Fill="1"/>
        <Button Text="Install" Style="Primary" OnClicked="app.install_url"/>
        <Button Name="update_all" Text="Update all" OnClicked="app.update_all" Visibility="Collapsed"/>
      </HBox>
    </Border>
    <Label Name="status" Opacity="0.75" Slot.Padding="6,0,0,0"/>
  </VBox>
</Window>
"""


def icon_rgba(n=64):
    """A red card with a blue chip: the window/taskbar icon, drawn without image files."""
    px = bytearray(n * n * 4)
    c, rad = (n - 1) / 2, n * 0.2
    for y in range(n):
        for x in range(n):
            # rounded card: inset 8px horizontally, 2px vertically
            dx, dy = max(10 - x, x - (n - 11), 0), max(4 - y, y - (n - 5), 0)
            inside = (dx * dx + dy * dy) ** 0.5 <= 6 and 4 <= x <= n - 5 and 0 <= y <= n - 1
            if not inside:
                continue
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            edge = x < 7 or x > n - 8 or y < 3 or y > n - 4
            col = (255, 255, 255) if edge else (45, 127, 249) if d <= rad else (255, 255, 255) if d <= rad + 3 else (230, 75, 60)
            px[(y * n + x) * 4:(y * n + x) * 4 + 4] = bytes((*col, 255))
    return bytes(px)


def backdrop(path, w=320, h=200):
    """Soft Balatro-coloured blobs (red, blue, felt green, gold) for the glass to blur."""
    blobs = [(0.12, 0.15, 0.55, (254, 95, 85)), (0.88, 0.25, 0.55, (0, 140, 255)),
             (0.45, 1.05, 0.60, (40, 150, 105)), (1.0, 1.0, 0.35, (253, 162, 0))]
    px = bytearray()
    for y in range(h):
        for x in range(w):
            c = [20, 22, 30]
            for bx, by, rad, col in blobs:
                k = max(0.0, 1 - (((x / w - bx) * 1.6) ** 2 + (y / h - by) ** 2) ** 0.5 / rad) ** 2 * 0.75
                c = [a + (b - a) * k for a, b in zip(c, col)]
            px += bytes((*map(int, c), 255))
    write_png(path, bytes(px), w, h)
    return path


def write_png(path, rgba, w, h):
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class App:
    def __init__(self):
        self.q = queue.Queue()
        self.index = mm.load_index() or []
        self.mods, self.shown_inst, self.shown_browse = [], [], []
        self.sel_inst = self.sel_browse = None
        self.remove_armed = None
        self.descs, self.texture, self.busy = {}, None, False

        self.win = r.Rwindow_create_from_xml(XML)
        r.Rwindow_set_icon(self.win, icon_rgba(), 64, 64)
        bg = mm.DATA / "backdrop.png"
        if not bg.exists():
            mm.DATA.mkdir(parents=True, exist_ok=True)
            backdrop(bg)
        r.Rwindow_set_background(self.win, r.Rtexture_create_from_file(str(bg)))
        w = lambda n: r.Rwidget_find(self.win, n)
        self.w = {n: w(n) for n in ("search", "tabs", "installed", "browse", "category", "url", "status", "update_all",
                                    "i_title", "i_sub", "i_update", "i_issues", "i_toggle", "i_install", "i_remove", "i_desc",
                                    "b_thumb", "b_title", "b_sub", "b_status", "b_install", "b_repo", "b_desc")}
        for name in ("refresh", "open_mods", "open_log", "toggle", "update_selected", "open_folder", "remove",
                     "install_selected", "open_repo", "install_url", "update_all"):
            r.Raction_bind("app." + name, self._safe(lambda *_, f=getattr(self, name): f()))
        r.Rtext_input_set_changed_callback(self.w["search"], self._safe(lambda *_: self.fill_lists()))
        r.Rcombo_box_set_changed_callback(self.w["category"], self._safe(lambda *_: self.fill_browse()))
        r.Rlist_view_set_selection_changed_callback(self.w["installed"], self._safe(lambda lv, i, _: self.select_inst(i)))
        r.Rlist_view_set_selection_changed_callback(self.w["browse"], self._safe(lambda lv, i, _: self.select_browse(i)))
        r.Rlist_view_set_activated_callback(self.w["installed"], self._safe(lambda *_: self.toggle()))

        self.rescan()
        self.fill_categories()
        self.fill_lists()
        age = mm.index_age()
        if age is None or age > 6 * 3600:  # first run or stale: refresh the index in the background
            self.refresh_index()
        else:
            self.status(f"{len(self.mods)} mods installed · index has {len(self.index)} mods")
        self.check_releases()

    def check_releases(self):
        """Mods installed from a GitHub repo the index doesn't list: compare with the latest release."""
        if any(m["source"] for m in self.mods):
            self.bg(lambda: mm.check_releases(self.mods), lambda *_: (self.rescan(), self.fill_installed()))

    # ---------- plumbing ----------

    def _safe(self, fn):
        def run(*a):
            try:
                fn(*a)
            except Exception as e:
                traceback.print_exc()
                self.status(f"Error: {e}")
        return run

    def bg(self, work, done):
        """Run work() on a thread, then done(result, error) on the UI thread."""
        def run():
            try:
                res = (work(), None)
            except Exception as e:
                traceback.print_exc()
                res = (None, e)
            self.q.put(lambda: done(*res))
            r.Rwake_up()
        threading.Thread(target=run, daemon=True).start()

    def pump(self):
        while not self.q.empty():
            self.q.get()()

    def status(self, text):
        r.Rlabel_set_text(self.w["status"], text)

    def show(self, name, visible):
        r.Rwidget_set_visibility(self.w[name], r.R_VISIBLE if visible else r.R_COLLAPSED)

    def search(self):
        return (r.Rtext_input_get_text(self.w["search"]) or "").lower().strip()

    # ---------- data ----------

    def rescan(self):
        self.mods = mm.scan(self.index)
        self.installed_keys = {m["index"]["key"]: m for m in self.mods if m["index"]}
        ups = sum(m["update"] for m in self.mods)
        r.Rbutton_set_text(self.w["update_all"], f"Update all ({ups})")
        self.show("update_all", ups > 0)

    def refresh_index(self):
        self.status("Downloading the Balatro Mod Index…")
        def done(index, err):
            if err:
                self.status(f"Couldn't download the mod index: {err}")
                return
            self.index = index
            self.rescan()
            self.fill_categories()
            self.fill_lists()
            ups = sum(m["update"] for m in self.mods)
            self.status(f"{len(self.mods)} mods installed · index has {len(index)} mods · {ups} update(s) available")
        self.bg(mm.fetch_index, done)

    def fill_categories(self):
        cb = self.w["category"]
        cats = sorted({c for e in self.index for c in e.get("categories") or []})
        r.Rcombo_box_clear_items(cb)
        for c in ["All categories", *cats]:
            r.Rcombo_box_add_item(cb, c)
        r.Rcombo_box_set_selected(cb, 0)
        self.cats = [None, *cats]

    def fill_lists(self):
        self.fill_installed()
        self.fill_browse()

    def fill_installed(self):
        q, lv = self.search(), self.w["installed"]
        keep = self.sel_inst and self.sel_inst["folder"]
        self.shown_inst = [m for m in self.mods if not q or q in f"{m['name']} {m['id']} {m['folder']} {m['author']}".lower()]
        r.Rlist_view_clear_items(lv)
        for m in self.shown_inst:
            flags = ("   ▲ update" if m["update"] else "") + ("   ⚠" if m["enabled"] and m["issues"] else "")
            r.Rlist_view_add_item(lv, f"{'●' if m['enabled'] else '○'}   {m['name']}   {m['version']}{flags}")
        i = next((i for i, m in enumerate(self.shown_inst) if m["folder"] == keep), 0)
        if self.shown_inst:
            r.Rlist_view_set_selected(lv, i)
            r.Rlist_view_scroll_to_item(lv, i)
        self.select_inst(i)

    def fill_browse(self):
        q, lv = self.search(), self.w["browse"]
        sel = r.Rcombo_box_get_selected(self.w["category"])
        cat = self.cats[sel] if 0 <= sel < len(getattr(self, "cats", [])) else None
        keep = self.sel_browse and self.sel_browse["key"]
        self.shown_browse = sorted(
            (e for e in self.index
             if (not cat or cat in (e.get("categories") or []))
             and (not q or q in f"{e['title']} {e.get('author', '')} {e['key']}".lower())),
            key=lambda e: -(e.get("last-updated") or 0))
        r.Rlist_view_clear_items(lv)
        for e in self.shown_browse:
            mark = "   ✓" if e["key"] in self.installed_keys else ""
            r.Rlist_view_add_item(lv, f"{e['title']}   ·   {e.get('author', '?')}{mark}")
        i = next((i for i, e in enumerate(self.shown_browse) if e["key"] == keep), 0)
        if self.shown_browse:
            r.Rlist_view_set_selected(lv, i)
            r.Rlist_view_scroll_to_item(lv, i)
        self.select_browse(i)

    # ---------- installed tab ----------

    def select_inst(self, i):
        m = self.sel_inst = self.shown_inst[i] if 0 <= i < len(self.shown_inst) else None
        self.remove_armed = None
        r.Rbutton_set_text(self.w["i_remove"], "Remove")
        if not m:
            r.Rlabel_set_text(self.w["i_title"], "No mods found")
            for n in ("i_sub", "i_desc"):
                r.Rlabel_set_text(self.w[n], "")
            self.show("i_update", False); self.show("i_issues", False); self.show("i_install", False)
            return
        r.Rlabel_set_text(self.w["i_title"], m["name"])
        sub = [f"v{m['version']}", f"id: {m['id'] or '—'}", f"folder: {m['folder']}"]
        if m["author"]:
            sub.insert(0, f"by {m['author']}")
        if not m["enabled"]:
            sub.append("DISABLED")
        r.Rlabel_set_text(self.w["i_sub"], "   ·   ".join(sub))
        r.Rlabel_set_text(self.w["i_issues"], "\n".join("⚠ " + s for s in m["issues"]))
        self.show("i_issues", bool(m["enabled"] and m["issues"]))
        e, src = m["index"], m["source"]
        where = f"In the mod index as “{e['title']}”" if e else f"Installed from github.com/{src}" if src else ""
        if m["update"]:
            r.Rlabel_set_text(self.w["i_update"], f"Update available: {m['version']} → {m['latest']}   ({where})")
        elif where:
            r.Rlabel_set_text(self.w["i_update"], where + (f" · latest {m['latest']}" if m["latest"] else ""))
        self.show("i_update", bool(where))
        r.Rbutton_set_text(self.w["i_install"], "Update" if m["update"] else "Reinstall latest")
        self.show("i_install", bool(where))
        r.Rbutton_set_text(self.w["i_toggle"], "Disable" if m["enabled"] else "Enable")
        deps = "\n\n**Requires:** " + ", ".join(m["dependencies"]) if m["dependencies"] else ""
        r.Rlabel_set_text(self.w["i_desc"], (m["description"] or "*No description.*") + deps)

    def toggle(self):
        if m := self.sel_inst:
            mm.set_enabled(mm.MODS / m["folder"], not m["enabled"])
            self.status(f"{'Disabled' if m['enabled'] else 'Enabled'} {m['name']} (restart Balatro to apply)")
            self.rescan()
            self.fill_installed()

    def remove(self):
        m = self.sel_inst
        if not m:
            return
        if self.remove_armed != m["folder"]:  # two clicks: arm, then confirm
            self.remove_armed = m["folder"]
            r.Rbutton_set_text(self.w["i_remove"], "Click again to remove")
            return
        dest = mm.backup(mm.MODS / m["folder"])
        self.status(f"Removed {m['name']} (moved to backups\\{dest.name})")
        self.sel_inst = None
        self.rescan()
        self.fill_lists()

    def open_folder(self):
        if self.sel_inst:
            os.startfile(mm.MODS / self.sel_inst["folder"])

    @staticmethod
    def _reinstall(m, log):
        e = m["index"]
        return mm.install(url=e["downloadURL"], folder=e.get("folderName"), log=log) if e else mm.install(m["source"], log=log)

    def update_selected(self):
        if (m := self.sel_inst) and (m["index"] or m["source"]):
            self.run_install(lambda log: self._reinstall(m, log))

    def update_all(self):
        mods = [m for m in self.mods if m["update"]]
        self.run_install(lambda log: [n for m in mods for n in self._reinstall(m, log)])

    # ---------- browse tab ----------

    def select_browse(self, i):
        e = self.sel_browse = self.shown_browse[i] if 0 <= i < len(self.shown_browse) else None
        if not e:
            r.Rlabel_set_text(self.w["b_title"], "No mods found" if self.index else "Mod index not downloaded yet")
            for n in ("b_sub", "b_status", "b_desc"):
                r.Rlabel_set_text(self.w[n], "")
            self.show("b_thumb", False)
            return
        r.Rlabel_set_text(self.w["b_title"], e["title"])
        r.Rlabel_set_text(self.w["b_sub"], "   ·   ".join(filter(None, [
            f"by {e.get('author', '?')}", f"version {e.get('version', '?')}", ", ".join(e.get("categories") or []),
            time.strftime("updated %Y-%m-%d", time.localtime(e["last-updated"])) if e.get("last-updated") else None])))
        m = self.installed_keys.get(e["key"])
        needs = [n for n, k in (("Steamodded", "requires-steamodded"), ("Talisman", "requires-talisman")) if e.get(k)]
        missing = [n for n in needs if not any(x["id"] == n and x["enabled"] for x in self.mods)]
        st = (f"Installed: {m['version']}" + (" — update available" if m["update"] else "")) if m else "Not installed"
        if missing:
            st += "   ·   needs " + " and ".join(missing) + ", which you don't have enabled"
        r.Rlabel_set_text(self.w["b_status"], st)
        r.Rbutton_set_text(self.w["b_install"], ("Update" if m["update"] else "Reinstall") if m else "Install")
        r.Rwidget_set_enabled(self.w["b_repo"], bool(e.get("repo")))
        key = e["key"]
        if key in self.descs:
            r.Rlabel_set_text(self.w["b_desc"], self.descs[key])
        else:
            r.Rlabel_set_text(self.w["b_desc"], "*Loading description…*")
            def done(text, err, key=key):
                self.descs[key] = text if text is not None else "*No description.*"
                if self.sel_browse and self.sel_browse["key"] == key:
                    r.Rlabel_set_text(self.w["b_desc"], self.descs[key])
            self.bg(lambda: mm.fetch_text(key), done)
        self.show("b_thumb", False)
        if e.get("thumb"):
            dest = mm.DATA / "thumbs" / (key.replace("@", "_") + Path(e["thumb"]).suffix)
            def shown(path, err, key=key):
                if err or not self.sel_browse or self.sel_browse["key"] != key:
                    return
                tex = r.Rtexture_create_from_file(str(path))
                if self.texture:
                    r.Rtexture_destroy(self.texture)
                self.texture = tex
                r.Rimage_set_texture(self.w["b_thumb"], tex)
                self.show("b_thumb", True)
            self.bg(lambda: mm.fetch_file(e["thumb"], dest), shown)

    def install_selected(self):
        if self.sel_browse:
            self.install_entries([self.sel_browse])

    def open_repo(self):
        if self.sel_browse and self.sel_browse.get("repo"):
            os.startfile(self.sel_browse["repo"])

    # ---------- installing ----------

    def install_entries(self, entries):
        self.run_install(lambda log: [n for e in entries
                                      for n in mm.install(url=e["downloadURL"], folder=e.get("folderName"), log=log)])

    def install_url(self):
        src = (r.Rtext_input_get_text(self.w["url"]) or "").strip()
        if src:
            self.run_install(lambda log: mm.install(src, log=log))

    def run_install(self, job):
        if self.busy:
            self.status("Already installing, please wait…")
            return
        self.busy = True
        log = lambda s: (self.q.put(lambda: self.status(s)), r.Rwake_up())
        def done(names, err):
            self.busy = False
            self.rescan()
            self.fill_lists()
            self.status(f"Install failed: {err}" if err else
                        f"Installed {', '.join(names)}. Restart Balatro to load it." if names else "Nothing installed.")
        self.bg(lambda: job(log), done)

    # ---------- toolbar ----------

    def refresh(self):
        self.rescan()
        self.fill_lists()
        self.refresh_index()

    def open_mods(self):
        os.startfile(mm.MODS)

    def open_log(self):
        if log := mm.latest_log():
            os.startfile(log)
        else:
            self.status("No Lovely logs yet; start Balatro once.")


def main():
    if not r.Rinit(r.R_BACKEND_VULKAN):
        ctypes.windll.user32.MessageBoxW(None, "Raven couldn't start (Vulkan unavailable?).\n" + str(r.Rerror_get_last()),
                                         "Balatro Mod Manager", 0x10)
        return 1
    r.Rtheme_apply(r.R_THEME_GLASS_DARK)
    app = App()
    shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
    if shot and "--tab" in sys.argv:
        r.Rtab_view_set_active(app.w["tabs"], int(sys.argv[sys.argv.index("--tab") + 1]))
    t0 = time.time()
    while r.Rwait_frame(0.25):
        app.pump()
        if shot and time.time() - t0 > 6:
            px, w, h = r.Rwindow_capture(app.win)
            write_png(shot, ctypes.string_at(px, w * h * 4), w, h)
            r.Rpixels_free(px)
            break
    r.Rshutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
