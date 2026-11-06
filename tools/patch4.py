"""One-time patch: adds the 'inbounds / profiles' button to the panel card and the 'test target' button to the
free-test menu. Safe to run twice. Makes a .bak copy of every file it changes."""
import shutil
import sys


def patch(path, edits):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    text = "\n".join(lines)
    changed = False
    for marker, anchor, mode, new in edits:
        if marker in text:
            print("skip   (already patched):", path, "-", marker)
            continue
        hits = [i for i, ln in enumerate(lines) if anchor in ln]
        if len(hits) != 1:
            print("FAIL   anchor found %d times in %s: %s" % (len(hits), path, anchor))
            return False
        i = hits[0]
        indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        if mode == "before":
            lines.insert(i, indent + new)
        elif mode == "after":
            lines.insert(i + 1, indent + new)
        else:
            lines[i] = indent + new
        text = "\n".join(lines)
        changed = True
        print("patched", path, "-", marker)
    if changed:
        shutil.copy(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return True


ok = True
ok &= patch("bot/handlers/admin_panels.py", [
    ("adm:pf:{p.id}", 'f"adm:pd:{p.id}")],', "before",
     '[("\\U0001f4e1 \u0627\u06cc\u0646\u0628\u0627\u0646\u062f\u0647\u0627 / \u067e\u0631\u0648\u0641\u0627\u06cc\u0644\u200c\u0647\u0627", f"adm:pf:{p.id}")],'),
    ("\u0627\u0632 \u062f\u06a9\u0645\u0647", "Inbound\u0647\u0627 \u0628\u0639\u062f \u0627\u0632 \u0622\u0645\u0627\u062f\u0647", "replace",
     '"\\u2139\\ufe0f \u067e\u0631\u0648\u0641\u0627\u06cc\u0644\u200c\u0647\u0627 \u0648 \u0627\u06cc\u0646\u0628\u0627\u0646\u062f\u0647\u0627 \u0627\u0632 \u062f\u06a9\u0645\u0647 \u00ab\u0627\u06cc\u0646\u0628\u0627\u0646\u062f\u0647\u0627 / \u067e\u0631\u0648\u0641\u0627\u06cc\u0644\u200c\u0647\u0627\u00bb \u0645\u062f\u06cc\u0631\u06cc\u062a \u0645\u06cc\u200c\u0634\u0648\u0646\u062f."'),
])
ok &= patch("bot/handlers/admin_settings.py", [
    ('"adm:tp"', '"adm:sk:test_max_per_user")],', "after",
     '[("\\U0001f3af \u067e\u0646\u0644 \u0648 \u067e\u0631\u0648\u0641\u0627\u06cc\u0644 \u062a\u0633\u062a", "adm:tp")],'),
    ("\u0631\u0627 \u0627\u0632 \u062f\u06a9\u0645\u0647 \u067e\u0627\u06cc\u06cc\u0646", "\u0627\u0646\u062a\u062e\u0627\u0628 \u067e\u0646\u0644 \u0648 \u067e\u0631\u0648\u0641\u0627\u06cc\u0644 \u062a\u0633\u062a \u0648 \u0633\u0627\u062e\u062a \u0648\u0627\u0642\u0639\u06cc", "replace",
     '"\\u2139\\ufe0f \u067e\u0646\u0644 \u0648 \u067e\u0631\u0648\u0641\u0627\u06cc\u0644 \u062a\u0633\u062a \u0631\u0627 \u0627\u0632 \u062f\u06a9\u0645\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f. "'),
])
sys.exit(0 if ok else 1)
