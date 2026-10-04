import json
import os
import re
import shutil
import subprocess

import frappe

from wlh_translate.scanner import scanner
from wlh_translate.utils import progress


# ============================================================
# Upstream source patches
# ============================================================
#
# Some apps ship user facing text that can never reach the translation table:
# the string is hard coded in a frontend component - very often inside a
# shared npm package such as frappe-ui - and rendered verbatim, so no entry
# in Translation changes what the browser shows.
#
# The way out is to edit that source and rebuild the bundle. A rebuild is
# thrown away by the next `yarn install`, so both halves are kept here as
# plain, replayable files:
#
#     library/<app_name>/<patch_name>.patch
#
# A patch is an ordinary unified diff applied with GNU patch from the app
# repository root (-p1), the same convention `git diff` uses. Keeping it as
# text leaves it readable and reviewable, and needs no package manager of its
# own: `patch` is what the operating system already ships.

LIBRARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")

# Reading and applying a diff is instant; compiling a frontend is not.
PATCH_TIMEOUT = 5 * 60
BUILD_TIMEOUT = 60 * 60

# Source type recorded for the strings a patch introduces. The patch wraps
# them in __(), so they are JavaScript literals like any other frontend text.
PATCH_SOURCE_TYPE = "JS"

# One job id covers every patch action. Applying, reverting and rebuilding all
# rewrite the same tree and finish by running the same build, so letting two
# of them overlap would only ever produce a half written bundle.
PATCH_JOB = "patch_app"

# Only the added side of a diff is interesting: a line that starts with a
# single "+" is what the patch writes into the file.
_ADDED_LINE = re.compile(r"^\+(?!\+\+ )")

# The new-file side of a hunk header: "@@ -12,6 +14,9 @@".
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Reported patch states.
APPLIED = "applied"
AVAILABLE = "available"
CONFLICT = "conflict"


def app_root(app_name):
    """
    Return the repository root of an installed app.

    frappe.get_app_path() points at the python package (<root>/<app>), while
    a patch is relative to the repository that contains it.
    """
    return os.path.dirname(frappe.get_app_path(app_name))


def patch_file(app_name, patch_name):
    return os.path.join(LIBRARY_DIR, app_name, patch_name)


def list_patch_files(app_name=None):
    """Return (app_name, patch_name) for every patch in the library."""
    if not os.path.isdir(LIBRARY_DIR):
        return []

    apps = [app_name] if app_name else sorted(os.listdir(LIBRARY_DIR))

    found = []

    for app in apps:
        app_dir = os.path.join(LIBRARY_DIR, app)

        if not os.path.isdir(app_dir):
            continue

        for patch_name in sorted(os.listdir(app_dir)):
            if patch_name.endswith(".patch"):
                found.append((app, patch_name))

    return found


def patched_files(patch_path):
    """The files a patch touches, read from its "+++ b/..." headers."""
    files = []

    with open(patch_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("+++ "):
                continue

            name = line[4:].strip().split("\t")[0]
            if name.startswith("b/"):
                name = name[2:]

            files.append(name)

    return files


def _run_patch(app_name, patch_path, reverse=False, dry_run=False):
    """
    Run GNU patch and return (returncode, output).

    --forward keeps an already applied patch from being applied twice, and
    --batch keeps it from ever asking a question: a background worker has no
    terminal to answer one.
    """
    command = [
        "patch",
        "-p1",
        "--forward",
        "--batch",
        "-d",
        app_root(app_name),
        "-i",
        patch_path,
    ]

    if reverse:
        command.append("--reverse")

    if dry_run:
        command.append("--dry-run")

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PATCH_TIMEOUT,
        )
    except FileNotFoundError:
        frappe.throw("GNU patch is not installed, cannot apply upstream patches")
    except subprocess.TimeoutExpired:
        frappe.throw(f"Patching {app_name} timed out")

    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def patch_status(app_name, patch_name):
    """
    Report how a patch relates to the files currently on disk.

    applied   - the change is already in place
    available - it applies cleanly
    conflict  - neither direction applies, the file has diverged
    """
    patch_path = patch_file(app_name, patch_name)

    if not os.path.exists(patch_path):
        return "missing"

    # A diff that applies cleanly is not there yet; one that reverses cleanly
    # is already in place. The order matters because a file that was never
    # touched satisfies both, and would otherwise read as applied.
    if _run_patch(app_name, patch_path, dry_run=True)[0] == 0:
        return AVAILABLE

    if _run_patch(app_name, patch_path, reverse=True, dry_run=True)[0] == 0:
        return APPLIED

    return CONFLICT


def list_patches(app_name=None):
    """Describe every patch in the library, for the list view."""
    return [
        {
            "app_name": app,
            "patch_name": name,
            "status": patch_status(app, name),
            "files": patched_files(patch_file(app, name)),
        }
        for app, name in list_patch_files(app_name)
    ]


def iter_added_lines(patch_path):
    """
    Yield (target file, line number, line) for every line a patch adds.

    The line number is the one the string will have in the patched file, not
    the one it has in the diff. Walking the hunks is what makes it possible to
    point a translation resource at the file it actually lives in.
    """
    target = None
    number = 0

    with open(patch_path, encoding="utf-8") as handle:
        for raw in handle:
            if raw.startswith("+++ "):
                name = raw[4:].strip().split("\t")[0]
                target = name[2:] if name.startswith("b/") else name
                continue

            if raw.startswith("@@"):
                match = _HUNK_HEADER.match(raw)
                number = int(match.group(1)) if match else 0
                continue

            if target is None:
                continue

            if raw.startswith("+"):
                yield target, number, raw[1:]
                number += 1
            elif raw.startswith(("-", " ")):
                # a removed line only exists on the old side; context and
                # additions both advance the new side
                if raw.startswith(" "):
                    number += 1


def extract_strings(patch_path):
    """
    Return the msgids a patch adds, so they can be offered for translation.

    Only added lines are read, and only through the patterns the scanner
    already uses, so a patch cannot introduce a string the scanner itself
    would have refused to translate.
    """
    texts = []

    for _, _, line in iter_added_lines(patch_path):
        for pattern in scanner.TRANSLATION_PATTERNS:
            for match in pattern.finditer(line):
                text = scanner.source_key(
                    scanner.unescape_literal(match.group(1))
                )

                if text and text not in texts:
                    texts.append(text)

    return texts


def register_strings(app_name, patch_path):
    """
    Offer the strings a patch introduces for translation.

    They are inserted as ordinary Pending entries, so they show up in the
    translation app next to everything else and follow the same path to the
    site: translate, then publish. Existing entries are never overwritten -
    save_entry() only creates what is missing.
    """
    texts = []
    added = 0

    root = app_root(app_name)
    patch_name = os.path.basename(patch_path)

    for target, number, line in iter_added_lines(patch_path):
        for pattern in scanner.TRANSLATION_PATTERNS:
            for match in pattern.finditer(line):
                text = scanner.source_key(
                    scanner.unescape_literal(match.group(1))
                )

                if not text:
                    continue

                if text not in texts:
                    texts.append(text)

                # The patch file is the resource here, not the source line:
                # the string only exists in node_modules until it is applied,
                # and is thrown away again by the next install. Naming the
                # patch in the context is also what keeps two strings that
                # share one line from being folded into a single entry.
                if scanner.save_entry(
                    app=app_name,
                    source_type=PATCH_SOURCE_TYPE,
                    path=os.path.join(root, target),
                    line_number=number,
                    text=text,
                    context=scanner.make_context(f"{patch_name}: {text}"),
                ):
                    added += 1

    return {"strings": texts, "added": added}


def apply_patch(app_name, patch_name):
    """
    Apply one patch and register the strings it introduces.

    The rebuild is deliberately not part of this: it is slow, it is a
    separate concern, and it can be re-run on its own.
    """
    patch_path = patch_file(app_name, patch_name)

    if not os.path.exists(patch_path):
        frappe.throw(f"Patch not found: {app_name}/{patch_name}")

    status = patch_status(app_name, patch_name)

    if status == CONFLICT:
        frappe.throw(
            f"Patch {patch_name} does not fit {app_name} any more. "
            "The file has changed since the patch was written."
        )

    if status != APPLIED:
        code, output = _run_patch(app_name, patch_path)

        if code != 0:
            frappe.throw(f"Patching {app_name} failed:\n{output.strip()}")

    registered = register_strings(app_name, patch_path)

    return {
        "app_name": app_name,
        "patch_name": patch_name,
        "applied": True,
        **registered,
    }


def revert_patch(app_name, patch_name):
    """Take a patch back out, restoring the file the package shipped."""
    patch_path = patch_file(app_name, patch_name)

    if not os.path.exists(patch_path):
        frappe.throw(f"Patch not found: {app_name}/{patch_name}")

    if patch_status(app_name, patch_name) != APPLIED:
        return {"app_name": app_name, "patch_name": patch_name, "reverted": False}

    code, output = _run_patch(app_name, patch_path, reverse=True)

    if code != 0:
        frappe.throw(f"Reverting {app_name} failed:\n{output.strip()}")

    return {"app_name": app_name, "patch_name": patch_name, "reverted": True}


# ============================================================
# Rebuild
# ============================================================
#
# Editing node_modules only matters once the bundle is compiled again, so a
# patch always ends with a build of the app it belongs to.

def build_command(app_name):
    """Return the command that rebuilds an app's frontend bundle."""
    root = app_root(app_name)
    package_json = os.path.join(root, "package.json")

    if not os.path.exists(package_json):
        frappe.throw(f"{app_name} has no package.json to build from")

    with open(package_json, encoding="utf-8") as handle:
        package = json.load(handle)

    if "build" not in package.get("scripts", {}):
        frappe.throw(f"{app_name} has no build script to run")

    # Whichever manager installed the dependencies is the one that knows where
    # the toolchain is; the lock file is the reliable clue.
    if os.path.exists(os.path.join(root, "yarn.lock")):
        manager = "yarn"
        command = [manager, "build"]
    else:
        manager = "npm"
        command = [manager, "run", "build"]

    if not shutil.which(manager):
        frappe.throw(f"{manager} is not installed, cannot rebuild {app_name}")

    return command


def rebuild(app_name, done=0, total=0):
    """
    Compile an app's frontend bundle. Slow, so it runs on the long queue.

    A build on its own has no natural counter, so "total" stays 0 and the
    list view shows only the app name. When it is the last step of a patch
    action the caller passes that action's numbers instead.
    """
    command = build_command(app_name)

    progress.report(PATCH_JOB, done, total, app_name=app_name)

    try:
        proc = subprocess.run(
            command,
            cwd=app_root(app_name),
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        frappe.throw(f"Rebuilding {app_name} timed out")

    output = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode != 0:
        # The reason is at the end of a very long log; the job's error message
        # only shows its last line, so the tail is what is worth keeping.
        tail = "\n".join(output.strip().splitlines()[-15:])
        frappe.throw(f"Rebuilding {app_name} failed:\n{tail}")

    # Vite still exits 0 when the frappe-ui build config fails to copy the
    # built index.html to the app's www route. The bundle lands but the route
    # answers 404, so this is worth an error rather than a silent success.
    if "Error copying index.html" in output:
        tail = "\n".join(output.strip().splitlines()[-15:])
        frappe.throw(f"Rebuilding {app_name} could not write the page entry:\n{tail}")

    return {"app_name": app_name, "built": True}


def patch_job(app_name, action="apply", patch_name=None):
    """
    The background entry point for every patch action.

    "apply" and "revert" both change the tree and then rebuild, because the
    bundle in public/ is what the browser loads and it only follows the source
    once it has been compiled again. "rebuild" on its own is the way out when
    a build was interrupted, or was run before something else changed.

    Progress is reported in three steps so the status pill next to the list
    can show the run moving from patching to compiling.
    """
    if action == "rebuild":
        return rebuild(app_name)

    steps = 3

    progress.report(PATCH_JOB, 0, steps, app_name=app_name)

    if action == "apply":
        result = apply_patch(app_name, patch_name)
    elif action == "revert":
        result = revert_patch(app_name, patch_name)
    else:
        frappe.throw(f"Unknown patch action: {action}")

    progress.report(PATCH_JOB, 1, steps, app_name=app_name)

    rebuild(app_name, done=2, total=steps)

    return result