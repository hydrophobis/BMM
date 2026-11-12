"""Balatro mod manager core (Steamodded / Lovely). Python stdlib only; the window is app.pyw.

CLI:  python modman.py --list      installed mods, issues, available updates (uses cached index)
      python modman.py --test      self-check
Set BALATRO_MODS_DIR to point at another Mods folder (used for testing).
"""
import json, os, re, shutil, sys, tempfile, time, urllib.error, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODS = Path(os.environ.get("BALATRO_MODS_DIR") or Path(os.environ["APPDATA"]) / "Balatro" / "Mods")
DATA = Path(os.environ["LOCALAPPDATA"]) / "BalatroModManager"
BACKUPS = DATA / "backups"          # replaced / removed mods are moved here, never deleted
INDEX_CACHE = DATA / "index.json"
SOURCES = DATA / "sources.json"    # folder -> GitHub repo it was installed from (for release update checks)
RELEASES = {}                      # folder -> latest GitHub release tag, filled by check_releases()
INDEX_REPO = "skyline69/balatro-mod-index"
INDEX_RAW = f"https://raw.githubusercontent.com/{INDEX_REPO}/HEAD/"
BUILTIN = {"Steamodded", "Lovely", "Balatro"}  # always present when the game runs modded
SMODS_REQUIRED = ("id", "name", "author", "description")


# ---------- metadata ----------

def _header_meta(lua: Path):
    """Legacy '--- STEAMODDED HEADER' lua file."""
    text = lua.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    if not text.startswith("--- STEAMODDED HEADER\n"):
        return None
    def get(key):
        m = re.search(rf"^--- {key}: (.+)$", text, re.M)
        return m.group(1).strip() if m else None
    def arr(key):
        v = get(key)
        return [s.strip() for s in v.strip("[]").split(",") if s.strip()] if v else []
    return {"id": get("MOD_ID"), "name": get("MOD_NAME"), "version": get("VERSION") or "?",
            "dependencies": arr("DEPENDENCIES"), "conflicts": arr("CONFLICTS"),
            "author": arr("MOD_AUTHOR"), "description": get("MOD_DESCRIPTION")}


def read_mod(folder: Path):
    """Metadata for one mod folder, using the sources Steamodded uses, then fallbacks."""
    mod = None
    for f in sorted(folder.rglob("*.json")):  # ponytail: rglob scans assets too; fine for mod-sized folders
        if f.name.lower() == "manifest.json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            continue
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            mod = d
            break
    if mod is None:
        for lua in sorted(folder.rglob("*.lua")):
            if (m := _header_meta(lua)) and m["id"]:
                mod = m
                break
    issues = []
    if mod is None:
        mod = {"id": None, "name": folder.name}
        man = folder / "manifest.json"
        if man.exists():  # Thunderstore manifest (e.g. Steamodded itself)
            try:
                d = json.loads(man.read_text(encoding="utf-8-sig"))
                mod.update(name=d.get("name", folder.name), version=d.get("version_number", "?"),
                           description=d.get("description"))
            except ValueError:
                pass
        if folder.name.lower().startswith("smods") or mod["name"] == "Steamodded":
            mod["id"] = "Steamodded"
            if (v := folder / "version.lua").exists():
                mod["version"] = re.sub(r'return\s*"([^"]+)".*', r"\1", v.read_text().strip())
        elif not (folder / "lovely.toml").exists() and not (folder / "lovely").is_dir():
            issues.append("no metadata found (not a mod?)")
    else:
        missing = [k for k in SMODS_REQUIRED if not mod.get(k)]
        if missing:
            issues.append("metadata missing " + ", ".join(missing) + " (Steamodded will ignore it)")
    deps, confs, author = mod.get("dependencies") or [], mod.get("conflicts") or [], mod.get("author") or []
    return {
        "folder": folder.name,
        "id": mod.get("id"),
        "name": mod.get("display_name") or mod.get("name") or folder.name,
        "version": str(mod.get("version", "?")),
        "author": ", ".join(author) if isinstance(author, list) else str(author),
        "description": mod.get("description") or "",
        "dependencies": deps if isinstance(deps, list) else [],
        "conflicts": confs if isinstance(confs, list) else [],
        "provides": mod.get("provides") or [],
        "enabled": is_enabled(folder),
        "issues": issues,
    }


# ---------- enable / disable / remove ----------

def _blacklist_file():
    return MODS / "lovely" / "blacklist.txt"


def _blacklist():
    try:
        return {l.strip() for l in _blacklist_file().read_text().splitlines() if l.strip() and not l.startswith("#")}
    except OSError:
        return set()


def is_enabled(folder: Path):
    return not (folder / ".lovelyignore").exists() and folder.name not in _blacklist()


def set_enabled(folder: Path, on: bool):
    """Steamodded + Lovely both skip a folder containing .lovelyignore."""
    flag = folder / ".lovelyignore"
    if on:
        flag.unlink(missing_ok=True)
        if folder.name in _blacklist():  # in-game toggle can also use lovely/blacklist.txt
            bl = _blacklist_file()
            bl.write_text("".join(l + "\n" for l in bl.read_text().splitlines() if l.strip() != folder.name))
    else:
        flag.touch()


def backup(folder: Path):
    """Move a mod folder out of Mods into the backups folder (undo = move it back)."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(folder), str(dest))
    return dest


# ---------- dependency / conflict checks ----------

def vtuple(v):
    m = re.match(r"\d+(?:\.\d+)*", str(v).strip().lstrip("vV"))
    return tuple(int(x) for x in m.group().split(".")) if m else ()


def _cmp(a, b):
    a, b = vtuple(a), vtuple(b)
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def parse_spec(s):
    """'Talisman (>=2.0, <<3)' -> ('Talisman', [('>=','2.0'), ('<<','3')])."""
    m = re.match(r"\s*([^(\s]+)\s*(?:\((.*)\))?", s)
    cons = []
    for part in (m.group(2) or "").split(","):
        if c := re.match(r"\s*(>=|<=|>>|<<|==|>|<|=)?\s*(\S+)", part):
            cons.append((c.group(1) or ">=", c.group(2)))
    return m.group(1), cons


def satisfies(version, cons):
    # ponytail: numeric prefix only, ignores ~BETA-xxxx suffixes; use smods' V() rules if that ever matters
    if version in (None, "?"):
        return True
    ops = {">=": lambda c: c >= 0, ">": lambda c: c > 0, ">>": lambda c: c > 0,
           "<=": lambda c: c <= 0, "<": lambda c: c < 0, "<<": lambda c: c < 0,
           "==": lambda c: c == 0, "=": lambda c: c == 0}
    return all(ops[op](_cmp(version, v)) for op, v in cons)


def check(mods):
    """Fill mod['issues'] with missing deps / active conflicts, considering only enabled mods."""
    present = {}
    for m in mods:
        if m["enabled"] and m["id"]:
            present[m["id"]] = m["version"]
            for p in m["provides"]:
                pid, pc = parse_spec(p)
                present.setdefault(pid, pc[0][1] if pc else m["version"])
    for m in mods:
        if not m["enabled"]:
            continue
        for dep in m["dependencies"]:
            alts = [parse_spec(a) for a in dep.split("|")]
            if not any(i in BUILTIN and i not in present or (i in present and satisfies(present[i], c)) for i, c in alts):
                have = [f"{i} {present[i]}" for i, _ in alts if i in present]
                m["issues"].append(f"needs {dep.strip()}" + (f" (have {', '.join(have)})" if have else " (missing/disabled)"))
        for con in m["conflicts"]:
            i, c = parse_spec(con)
            if i in present and satisfies(present[i], c):
                m["issues"].append(f"conflicts with {i} {present[i]}")
    return mods


def scan(index=None):
    mods = [read_mod(d) for d in sorted(MODS.iterdir(), key=lambda p: p.name.lower())
            if d.is_dir() and d.name != "lovely"]
    check(mods)
    match_index(mods, index or [])
    return mods


# ---------- Balatro Mod Index ----------

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "balatro-modman"})
    return urllib.request.urlopen(req, timeout=60)


def fetch_index():
    """Download every mods/*/meta.json of the index (~450 small files) and cache them."""
    tree = json.load(_get(f"https://api.github.com/repos/{INDEX_REPO}/git/trees/HEAD?recursive=1"))["tree"]
    paths = {x["path"] for x in tree}
    keys = sorted(p[5:-10] for p in paths if p.startswith("mods/") and p.endswith("/meta.json"))
    def one(key):
        try:
            m = json.load(_get(INDEX_RAW + f"mods/{key}/meta.json"))
        except Exception:
            return None
        m["key"] = key
        m["thumb"] = next((f"mods/{key}/{t}" for t in ("thumbnail.jpg", "thumbnail.png") if f"mods/{key}/{t}" in paths), None)
        return m
    with ThreadPoolExecutor(16) as ex:
        index = [m for m in ex.map(one, keys) if m and m.get("title")]
    DATA.mkdir(parents=True, exist_ok=True)
    INDEX_CACHE.write_text(json.dumps({"fetched": time.time(), "mods": index}))
    return index


def load_index():
    try:
        return json.loads(INDEX_CACHE.read_text())["mods"]
    except (OSError, ValueError, KeyError):
        return None


def index_age():
    try:
        return time.time() - json.loads(INDEX_CACHE.read_text())["fetched"]
    except (OSError, ValueError, KeyError):
        return None


def fetch_text(key):
    return _get(INDEX_RAW + f"mods/{key}/description.md").read().decode("utf-8", "replace")


def fetch_file(rel, dest: Path):
    """Download an index file (e.g. a thumbnail) once into the cache."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with _get(INDEX_RAW + rel) as r:
            dest.write_bytes(r.read())
    return dest


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def dotted(v):
    """~2/3 of index versions are commit hashes / dates; only dotted versions are comparable."""
    return "." in str(v) and vtuple(v)


def match_index(mods, index):
    """Link installed mods to index entries (folderName, then title), or to the GitHub repo they
    were installed from, and flag updates."""
    sources = load_sources()
    by = {}
    for e in index:
        for k in (e.get("folderName"), e.get("title"), e["key"].split("@")[-1]):
            if _norm(k):
                by.setdefault(_norm(k), e)
    for m in mods:
        # ponytail: name matching, can mislink two mods with the same title; index has no mod id to match on
        e = next((by[_norm(k)] for k in (m["folder"], m["id"], m["name"]) if _norm(k) in by), None)
        m["index"] = e
        m["source"] = None if e else sources.get(m["folder"])
        m["latest"] = e.get("version") if e else RELEASES.get(m["folder"])
        m["update"] = bool(dotted(m["latest"]) and dotted(m["version"]) and _cmp(m["latest"], m["version"]) > 0)
    return mods


def load_sources():
    try:
        return json.loads(SOURCES.read_text())
    except (OSError, ValueError):
        return {}


def save_source(folder, src):
    s = load_sources()
    s[folder] = src
    DATA.mkdir(parents=True, exist_ok=True)
    SOURCES.write_text(json.dumps(s, indent=1))


def check_releases(mods):
    """GitHub-releases fallback: latest release tag for mods installed from a repo the index doesn't list."""
    for m in mods:
        if m.get("source") and (gh := _gh(m["source"])):
            try:
                RELEASES[m["folder"]] = json.load(_get(f"https://api.github.com/repos/{gh[0]}/{gh[1]}/releases/latest"))["tag_name"]
            except Exception:  # no releases / rate limited: nothing to compare
                pass
    return RELEASES


# ---------- install ----------

def _gh(src):
    """'owner/repo' or a github.com repo/tree/tag URL -> (owner, repo, ref or None), else None."""
    m = re.match(r"(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(?:tree|releases/tag)/([^/?#]+))?/?$", src.strip())
    return m.groups() if m else None


def resolve_url(src):
    """'owner/repo', a github.com URL, or a direct .zip URL -> (zip url, repo name or None)."""
    src = src.strip()
    if src.lower().split("?")[0].endswith(".zip"):
        return src, None
    if not (gh := _gh(src)):
        raise ValueError(f"Not a GitHub repo or .zip URL: {src}")
    owner, repo, ref = gh
    api = f"https://api.github.com/repos/{owner}/{repo}"
    if ref:  # explicit tag/branch
        return f"{api}/zipball/{ref}", repo
    try:
        rel = json.load(_get(f"{api}/releases/latest"))
        zips = [a["browser_download_url"] for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")]
        return (zips[0], None) if zips else (rel["zipball_url"], repo)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return f"{api}/zipball", repo  # no releases: default branch


def _is_mod_dir(d: Path):
    if (d / "lovely.toml").exists() or (d / "lovely").is_dir():
        return True
    for f in d.glob("*.json"):
        try:
            if f.name.lower() != "manifest.json" and "id" in json.loads(f.read_text(encoding="utf-8-sig")):
                return True
        except (ValueError, OSError, TypeError):
            pass
    return any(_header_meta(f) for f in d.glob("*.lua"))


def find_mod_dirs(root: Path):
    """Top-most folders that look like mods (nested matches are part of their parent)."""
    found = []
    for d in [root, *sorted(p for p in root.rglob("*") if p.is_dir())]:
        if not any(f in d.parents for f in found) and _is_mod_dir(d):
            found.append(d)
    return found


def install(src="", url=None, folder=None, log=print):
    """Install from a GitHub repo/URL (src) or a direct archive url. An existing copy of the
    same mod is moved to BACKUPS and replaced, keeping its enabled/disabled state."""
    repo = None
    if url is None:
        url, repo = resolve_url(src)  # repo is set only for GitHub source zipballs ('owner-repo-sha' wrapper)
    log(f"Downloading {url}")
    with tempfile.TemporaryDirectory(prefix="balatro-modman-") as tmp:
        zpath, out = Path(tmp) / "mod.zip", Path(tmp) / "x"
        with _get(url) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        if not zipfile.is_zipfile(zpath):
            raise RuntimeError("Download is not a .zip archive; install it by hand from the mod's page.")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(out)  # zipfile strips '..' and absolute paths
        dirs = find_mod_dirs(out)
        if not dirs:
            raise RuntimeError("No mod found in the archive (no metadata JSON, STEAMODDED header, or lovely.toml).")
        installed = []
        for d in dirs:
            if folder and len(dirs) == 1:
                name = folder
            elif d == out or (repo and d.parent == out and len(dirs) == 1):
                name = repo or Path(url.split("?")[0]).stem
            else:
                name = d.name
            mid = read_mod(d)["id"]  # reinstall over the existing folder of the same mod id
            name = next((p.name for p in MODS.iterdir() if p.is_dir() and mid and read_mod(p)["id"] == mid), name)
            dest = MODS / name
            keep_disabled = dest.exists() and not is_enabled(dest)
            if dest.exists():
                log(f"Backed up old {name} to {backup(dest)}")
            shutil.copytree(d, dest)
            if keep_disabled:
                (dest / ".lovelyignore").touch()
            if src and _gh(src) and not _gh(src)[2]:  # remember the repo for release update checks
                save_source(name, src.strip())
            log(f"Installed {name}")
            installed.append(name)
        return installed


# ---------- misc ----------

def latest_log():
    logs = sorted((MODS / "lovely" / "log").glob("*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def _selftest():
    assert parse_spec("Steamodded (>=1.0.0~BETA-1814a)") == ("Steamodded", [(">=", "1.0.0~BETA-1814a")])
    assert parse_spec("Multiplayer") == ("Multiplayer", [])
    assert satisfies("26.1002.0", [(">=", "1.0.0~BETA-1814a")])
    assert not satisfies("2.7", [("<=", "2.0.2")])
    assert satisfies("1.9.5", [("<<", "1.9.6")]) and not satisfies("2.0.5", [("<<", "1.9.6")])
    mods = check([
        {"folder": "a", "id": "A", "name": "A", "version": "1.0", "dependencies": ["B (>=2)", "Lovely (>=0.9)"], "conflicts": ["C"], "provides": [], "enabled": True, "issues": []},
        {"folder": "b", "id": "B", "name": "Bee", "version": "1.5", "dependencies": [], "conflicts": [], "provides": [], "enabled": True, "issues": []},
        {"folder": "c", "id": "C", "name": "C", "version": "1", "dependencies": [], "conflicts": [], "provides": [], "enabled": False, "issues": []},
    ])
    assert mods[0]["issues"] == ["needs B (>=2) (have B 1.5)"], mods[0]["issues"]
    match_index(mods, [{"key": "x@Bee", "title": "Bee", "version": "v1.6"}, {"key": "y@C", "title": "C", "version": "1337217"}])
    assert mods[1]["update"] and not mods[2]["update"] and mods[0]["index"] is None
    assert _gh("https://github.com/o/r.git") == ("o", "r", None) and _gh("o/r/tree/dev") == ("o", "r", "dev") and not _gh("x")
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selftest()
    elif "--list" in sys.argv:
        for m in scan(load_index()):
            up = f"  -> update {m['latest']}" if m["update"] else ""
            print(f"[{'x' if m['enabled'] else ' '}] {m['name']:<22} {m['id'] or '-':<20} {m['version']:<14} {m['folder']:<26} {'; '.join(m['issues'])}{up}")
