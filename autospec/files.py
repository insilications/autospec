#!/bin/true
#
# files.py - part of autospec
# Copyright (C) 2015 Intel Corporation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# %files section management
#

import os
import re
import mmap
import subprocess
import util
from collections import OrderedDict
from typing import List, Tuple

from util import call, write_out, print_fatal, print_debug, print_info, scantree
import sys

class FileManager(object):
    """Class to handle spec file %files section management."""

    def __init__(self, config, package, mock_dir : str, short_circuit : str):
        """Set defaults for FileManager."""
        self.config = config
        self.package = package
        self.packages = OrderedDict()  # per sub-package file list for spec purposes
        self.subpackages = OrderedDict()  # per named sub-packaged (-n <name>)
        self.files = set()  # global file set to weed out dupes
        self.files_blacklist = set()
        self.excludes = []
        self.manual_excludes = []
        self.file_maps = {}  # Filename-to-package mapping
        self.setuid = []
        self.attrs = {}
        self.locales = []
        self.newfiles_printed = False
        # Do we need ALL include files in a dev package, even if they're not in
        # /usr/include?  Yes in the general case, but for example for R
        # packages, the answer is No.
        self.want_dev_split = True
        self.has_banned = False
        self.cargo_install_assets: list[tuple[str, str, str]] = list()
        self.builddir : str = str()
        self.chroot_buildroot : str = str()
        self.mock_dir : str = mock_dir
        self.short_circuit : str = short_circuit
        self.package_name : str = str()

    @staticmethod
    def banned_path(path):
        """Check if the path is either banned or in a banned subdirectory."""
        banned_paths = ["/etc", "/usr/local", "/usr/etc", "/usr/src", "/var"]
        for bpath in banned_paths:
            if path.startswith(bpath):
                return True
        return False

    def push_package_file(self, filename, package="main", subpackage=False):
        """Add found %file and indicate to build module that we must restart the build."""

        if subpackage is False:
            if package not in self.packages:
                self.packages[package] = set()

            if FileManager.banned_path(filename):
                util.print_warning(f"  Content {filename} found in banned path, skipping")
                self.has_banned = True
                return

            # prepend the %attr macro if file defined in 'attrs' control file
            if filename in self.attrs:
                mod = self.attrs[filename][0]
                u = self.attrs[filename][1]
                g = self.attrs[filename][2]
                filename = "%attr({0},{1},{2}) {3}".format(mod, u, g, filename)
            self.packages[package].add(filename)
            if self.package.do_file_restart:
                self.package.file_restart += 1
            else:
                self.package.must_restart += 1
            if not self.newfiles_printed:
                print("  New %files content found")
                self.newfiles_printed = True

        else:
            if package not in self.subpackages:
                self.subpackages[package] = set()

            if FileManager.banned_path(filename):
                util.print_warning(f"  Content {filename} found in banned path, skipping")
                self.has_banned = True
                return

            # prepend the %attr macro if file defined in 'attrs' control file
            if filename in self.attrs:
                mod = self.attrs[filename][0]
                u = self.attrs[filename][1]
                g = self.attrs[filename][2]
                filename = "%attr({0},{1},{2}) {3}".format(mod, u, g, filename)
            self.subpackages[package].add(filename)
            if self.package.do_file_restart:
                self.package.file_restart += 1
            else:
                self.package.must_restart += 1
            if not self.newfiles_printed:
                print("  New %files content found")
                self.newfiles_printed = True

    def only32bit_exclude(self, filename):
        """Exclude files not necessary for a 32bit only package."""
        if not self.config.config_opts.get("32bit_only"):
            return False

        patterns = [
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.so\."),
            re.compile(r"^/(?:usr/|usr.*)lib32/lib(asm|dw|elf)-[0-9.]+\.so"),
            re.compile(r"^/(?:usr/|usr.*)lib32/cmake/"),
            re.compile(r"^/(?:usr/|usr.*)lib32/qt5/mkspecs/"),
            re.compile(r"^/(?:usr/|usr.*)lib32/qt5/"),
            re.compile(r"^/(?:usr/|usr.*)lib32/libkdeinit5_[a-zA-Z0-9\.\_\+\-]*\.so$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.so$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-\/]*\.a$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/pkgconfig/[a-zA-Z0-9\.\_\+\-]*\.pc$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.la$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.prl$"),
            re.compile(r"^/(?:usr/|usr.*)lib32/.*/[a-zA-Z0-9\.\_\+\-]*\.so"),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$"),
            re.compile(r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$")]

        exclude = True
        for pat in patterns:
            if pat.search(filename):
                exclude = False
                break

        return exclude

    def compat_exclude(self, filename):
        """Exclude non-library files if the package is for compatability."""
        if not self.config.config_opts.get("compat"):
            return False

        patterns = [
            re.compile(r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\-\+]*\.so\."),
            re.compile(r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\-\+]*\.so\."),
            re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\-\+]*\.so\."),
            re.compile(r"^/(?:usr/|usr.*)lib64/lib(asm|dw|elf)-[0-9.]+\.so"),
            re.compile(r"^/(?:usr/|usr.*)lib32/lib(asm|dw|elf)-[0-9.]+\.so"),
            re.compile(r"^/(?:usr/|usr.*)lib64/haswell/[a-zA-Z0-9\.\_\-\+]*\.so\."),
            re.compile(r"^/(?:usr/|usr.*)share/package-licenses/"),
            re.compile(r"^/usr/share/locale/.*/(.*)\.mo")]

        exclude = True
        for pat in patterns:
            if pat.search(filename):
                exclude = False
                break

        if self.config.config_opts.get("keepstatic"):
            patterns_static = [
                re.compile(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-\/]*\.a$"),
                re.compile(r"^/(?:usr/|usr.*)lib32/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$"),
                re.compile(r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-\/]*\.a$"),
                re.compile(r"^/(?:usr/|usr.*)lib64/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$")]

            for pat in patterns_static:
                if pat.search(filename):
                    exclude = False
                    break

        return exclude

    def file_pat_match(self, filename, pattern, package, replacement="", prefix="", subpackage=False):
        """Search for pattern in filename.

        Attempt to find pattern in filename, if pattern matches push package file.
        If that file is also in the excludes list, don't push the file.
        Returns True if a file was pushed, False otherwise.
        """
        if not replacement:
            replacement = prefix + filename

        # compat files should always be excluded
        if self.compat_exclude(filename):
            self.excludes.append(filename)
            return True

        # non 32bit files should always be excluded when 32bit_only
        if self.only32bit_exclude(filename):
            self.excludes.append(filename)
            return True

        pat = re.compile(pattern)
        match = pat.search(filename)
        if match:
            if filename in self.excludes:
                return True

            self.push_package_file(replacement, package, subpackage)
            return True
        else:
            return False

    def file_is_locale(self, filename):
        """If a file is a locale, appends to self.locales and returns True, returns False otherwise."""
        pat = re.compile(r"^/usr/share/locale/.*/(.*)\.mo")
        match = pat.search(filename)
        if match:
            if self.config.config_opts["exclude_locales"]:
                self.excludes.append(filename)
                return True
            lang = match.group(1)
            if lang not in self.locales and filename not in self.excludes:
                self.locales.append(lang)
                print("  New locale:", lang)
                if not self.config.find_lang and not self.config.config_opts["findlang"]:
                    self.package.must_restart += 1
                if self.package_name == "gcc" or self.package_name == "glibc":
                    if "locale" not in self.packages:
                        self.packages["locale"] = set()
                else:
                    if "locales" not in self.packages:
                        self.packages["locales"] = set()
            return True
        else:
            return False

    def _clean_dirs(self, root, files):
        """Do the work to remove the directories from the files list."""
        res = set()
        removed = False

        directive_re = re.compile(r"(%\w+(\([^\)]*\))?\s+)(.*)")
        for f in files:
            # skip the files with directives at the beginning, including %doc
            # and %dir directives.
            # autospec does not currently support adding empty directories to
            # the file list by prefixing "%dir". Regardless, skip these entries
            # because if they exist at this point it is intentional (i.e.
            # support was added).
            if directive_re.match(f):
                res.add(f)
                continue

            path = os.path.join(root, f.lstrip("/"))
            if os.path.isdir(path) and not os.path.islink(path):
                util.print_warning("Removing directory {} from file list".format(f))
                self.files_blacklist.add(f)
                removed = True
            else:
                res.add(f)

        return (res, removed)

    def clean_directories(self, root):
        """Remove directories from file list."""
        removed = False
        for pkg in self.packages:
            self.packages[pkg], _rem = self._clean_dirs(root, self.packages[pkg])
            if _rem:
                removed = True

        for pkg in self.subpackages:
            self.subpackages[pkg], _rem = self._clean_dirs(root, self.subpackages[pkg])
            if _rem:
                removed = True

        return removed

    def push_file(self, filename, pkg_name):
        """Perform a number of checks against the filename and push the filename if appropriate."""
        if filename in self.files or filename in self.files_blacklist:
            return

        self.files.add(filename)
        if self.file_is_locale(filename):
            return

        # Explicit file packaging
        for k, v in self.file_maps.items():
            if filename in v['files']:
                self.push_package_file(filename, k)
                return

        if filename in self.setuid:
            if filename in self.attrs:
                mod = self.attrs[filename][0]
                u = self.attrs[filename][1]
                g = self.attrs[filename][2]
                newfn = "%attr({0},{1},{2}) {3}".format(mod, u, g, filename)
            else:
                newfn = "%attr(4755, root, root) " + filename
            self.push_package_file(newfn, "setuid")
            return

        # autostart
        part = re.compile(r"^/(?:usr/|usr.*)lib/systemd/system/.+\.target\.wants/.+")
        if part.search(filename) and 'update-triggers.target.wants' not in filename:
            if filename not in self.excludes:
                self.push_package_file(filename, "autostart")
                self.push_package_file("%exclude " + filename, "services")
                return

        if self.want_dev_split and self.file_pat_match(filename, r"^/usr/.*/include/.*\.(h|hpp)$", "dev"):
            return

        # if configured to do so, add .so files to the lib package instead of
        # the dev package. THis is useful for packages with a plugin
        # architecture like elfutils and mesa.
        so_dest = 'lib' if self.config.config_opts.get('so_to_lib') else 'dev'
        so_dest_ompi = 'openmpi' if self.config.config_opts.get('so_to_lib') else 'dev'

        patterns = [
            # Patterns for matching files, format is a tuple as follows:
            # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
            # order matters, first match wins!
            (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
            (r"^/(?:usr/|usr.*)share/package-licenses/.{1,}/.{1,}", "license"),
            (r"^/(?:usr/|usr.*)share/man/man2", "man"),
            (r"^/(?:usr/|usr.*)share/man/man3", "man"),
            (r"^/(?:usr/|usr.*)share/man/man\d", "man"),
            (r"^/(?:usr/|usr.*)share/man/", "man"),
            (r"^/(?:usr/|usr.*)share/pkgconfig/32.*\.pc$", "dev32"),
            (r"^/(?:usr/|usr.*)share/pkgconfig/", "dev"),
            (r"^/(?:usr/|usr.*)share/info/", "info"),
            (r"^/(?:usr/|usr.*)share/abi/", "abi"),
            (r"^/(?:usr/|usr.*)share/qt5/examples/", "examples"),
            (r"^/(?:usr/|usr.*)share/omf", "main", "/usr/share/omf/*"),
            (r"^/(?:usr/|usr.*)share/installed-tests/", "tests"),
            (r"^/(?:usr/|usr.*)libexec/installed-tests/", "tests"),
            (r"^/usr/share/clear/optimized-elf/bin", "bin", "/usr/share/clear/optimized-elf/bin*"),
            (r"^/usr/share/clear/optimized-elf/exec", "libexec", "/usr/share/clear/optimized-elf/exec*"),
            (r"^/usr/share/clear/optimized-elf/lib", "lib", "/usr/share/clear/optimized-elf/lib*"),
            (r"^/usr/share/clear/optimized-elf/other", "lib", "/usr/share/clear/optimized-elf/other*"),
            (r"^/usr/share/clear/optimized-elf/test", "tests", "/usr/share/clear/optimized-elf/test*"),
            (r"^/usr/share/clear/optimized-elf/", "lib"),
            (r"^/usr/share/clear/filemap/", "filemap"),
            (r"^/(?:usr/|usr.*)lib64/cmake/Qt[a-zA-Z0-9\.\_\+\-\/]*", "dev"),
            (r"^/(?:usr/|usr.*)lib64/qml/[a-zA-Z0-9\.\_\+\-\/@]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib64/qml/[a-zA-Z0-9\.\_\+\-\/@]*", "dev"),
            (r"^/(?:usr/|usr.*)lib64/plugins/[a-zA-Z0-9\.\_\+\-\/@]*", "dev"),
            (r"^/(?:usr/|usr.*)lib64/mkspecs/[a-zA-Z0-9\.\_\+\-\/@]*", "dev"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/bin/", "openmpi"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/share", "openmpi"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/include/", "dev"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/lib/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest_ompi),
            (r"^/(?:usr/|usr.*)lib64/openmpi/lib/[a-zA-Z0-9\.\_\+\-\/]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/lib/[a-zA-Z0-9\.\_\+\-]*\.so\.", "openmpi"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/lib/python3.*/", "openmpi"),
            (r"^/(?:usr/|usr.*)lib64/openmpi/lib/", "dev"),
            (r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-]*\.so\.", "plugins"),
            (r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-]*\.so\.", "lib"),
            (r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.so\.", "lib32"),
            (r"^/(?:usr/|usr.*)lib64/lib(asm|dw|elf)-[0-9.]+\.so", "lib"),
            (r"^/(?:usr/|usr.*)lib64/libkdeinit5", "lib"),
            (r"^/(?:usr/|usr.*)lib32/lib(asm|dw|elf)-[0-9.]+\.so", "lib32"),
            (r"^/(?:usr/|usr.*)lib64/haswell/[a-zA-Z0-9\.\_\+\-]*\.so\.", "lib"),
            (r"^/(?:usr/|usr.*)lib64/gobject-introspection/", "lib"),
            (r"^/(?:usr/|usr.*)libexec/", "libexec"),
            (r"^/(?:usr/|usr.*)bin/", "bin"),
            (r"^/(?:usr/|usr.*)sbin/", "bin"),
            (r"^/sbin/", "bin"),
            (r"^/bin/", "bin"),
            (r"^/(?:usr/|usr.*)lib/python3.*/", "python3", "/usr/lib/python3*/*"),
            (r"^/(?:usr/|usr.*)share/gir-[0-9\.]+/[a-zA-Z0-9\.\_\+\-]*\.gir", "data", "/usr/share/gir-1.0/*.gir"),
            (r"^/(?:usr/|usr.*)share/cmake/", "data", "/usr/share/cmake/*"),
            (r"^/(?:usr/|usr.*)share/cmake-3.1/", "data", "/usr/share/cmake-3.1/*"),
            (r"^/(?:usr/|usr.*)share/cmake-3.7/", "data", "/usr/share/cmake-3.7/*"),
            (r"^/(?:usr/|usr.*)share/cmake-3.8/", "data", "/usr/share/cmake-3.8/*"),
            (r"^/(?:usr/|usr.*)share/cmake-3.6/", "data", "/usr/share/cmake-3.6/*"),
            (r"^/(?:usr/|usr.*)share/girepository-1\.0/.*\.typelib\$", "data", "/usr/share/girepository-1.0/*.typelib"),
            (r"^/(?:usr/|usr.*)include/", "dev"),
            (r"^/(?:usr/|usr.*)lib64/girepository-1.0/", "data"),
            (r"^/(?:usr/|usr.*)share/cmake/", "dev"),
            (r"^/(?:usr/|usr.*)lib/cmake/", "dev"),
            (r"^/(?:usr/|usr.*)lib64/cmake/", "dev"),
            (r"^/(?:usr/|usr.*)lib32/cmake/", "dev32"),
            (r"^/(?:usr/|usr.*)lib/qt5/mkspecs/", "dev"),
            (r"^/(?:usr/|usr.*)lib64/qt5/mkspecs/", "dev"),
            (r"^/(?:usr/|usr.*)lib32/qt5/mkspecs/", "dev32"),
            (r"^/(?:usr/|usr.*)lib/qt5/", "lib"),
            (r"^/(?:usr/|usr.*)lib64/qt5/", "lib"),
            (r"^/(?:usr/|usr.*)lib32/qt5/", "lib32"),
            (r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib64/libkdeinit5_[a-zA-Z0-9\.\_\+\-]*\.so$", "lib"),
            (r"^/(?:usr/|usr.*)lib32/libkdeinit5_[a-zA-Z0-9\.\_\+\-]*\.so$", "lib32"),
            (r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest + '32'),
            (r"^/usr/lib64/glibc-hwcaps/x86-64-v[0-9]+/[a-zA-Z0-9._+-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib64/haswell/avx512_1/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib64/haswell/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib64/haswell/avx512_1/[a-zA-Z0-9\.\_\+\-]*\.so$", so_dest),
            (r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-\/]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-\/]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-\/]*\.a$", "staticdev32"),
            (r"^/(?:usr/|usr.*)lib/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$", "staticdev"),
            (r"^/usr/lib64/glibc-hwcaps/x86-64-v[0-9]+/[a-zA-Z0-9._+-]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib64/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$", "staticdev"),
            (r"^/usr/lib64/haswell/avx512_1/[a-zA-Z0-9._+-]*\.a$", "staticdev"),
            (r"^/(?:usr/|usr.*)lib32/haswell/[a-zA-Z0-9\.\_\+\-]*\.a$", "staticdev32"),
            (r"^/(?:usr/|usr.*)lib/pkgconfig/[a-zA-Z0-9\.\_\+\-]*\.pc$", "dev"),
            (r"^/(?:usr/|usr.*)lib64/pkgconfig/[a-zA-Z0-9\.\_\+\-]*\.pc$", "dev"),
            (r"^/(?:usr/|usr.*)lib32/pkgconfig/[a-zA-Z0-9\.\_\+\-]*\.pc$", "dev32"),
            (r"^/usr/lib64/glibc-hwcaps/x86-64-v[0-9]+/[a-zA-Z0-9._+-]*\.pc$", "dev"),
            (r"^/usr/lib64/haswell/pkgconfig/[a-zA-Z0-9._+-]*\.pc$", "dev"),
            (r"^/usr/lib64/haswell/avx512_1/pkgconfig/[a-zA-Z0-9._+-]*\.pc$", "dev"),
            (r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-]*\.la$", "dev"),
            (r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-]*\.la$", "dev"),
            (r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.la$", "dev32"),
            (r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-]*\.prl$", "dev"),
            (r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-]*\.prl$", "dev"),
            (r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-]*\.prl$", "dev32"),
            (r"^/(?:usr/|usr.*)share/aclocal/[a-zA-Z0-9\.\_\+\-]*\.ac$", "dev", "/usr/share/aclocal/*.ac"),
            (r"^/(?:usr/|usr.*)share/aclocal/[a-zA-Z0-9\.\_\+\-]*\.m4$", "dev", "/usr/share/aclocal/*.m4"),
            (r"^/(?:usr/|usr.*)share/aclocal-1.[0-9]+/[a-zA-Z0-9\.\_\+\-]*\.ac$", "dev", "/usr/share/aclocal-1.*/*.ac"),
            (r"^/(?:usr/|usr.*)share/aclocal-1.[0-9]+/[a-zA-Z0-9\.\_\+\-]*\.m4$", "dev", "/usr/share/aclocal-1.*/*.m4"),
            (r"^/(?:usr/|usr.*)share/doc/" + re.escape(pkg_name) + "/", "doc", "%doc /usr/share/doc/" + re.escape(pkg_name) + "/*"),
            (r"^/(?:usr/|usr.*)share/doc/", "doc"),
            (r"^/(?:usr/|usr.*)share/gtk-doc/html", "doc"),
            (r"^/(?:usr/|usr.*)share/help", "doc"),
            (r"^/(?:usr/|usr.*)share/info/", "doc", "%doc /usr/share/info/*"),
            # now a set of catch-all rules
            (r"^/lib/systemd/system/", "services"),
            (r"^/lib/systemd/user/", "services"),
            (r"^/(?:usr/|usr.*)lib/systemd/system/", "services"),
            (r"^/(?:usr/|usr.*)lib/systemd/user/", "services"),
            (r"^/(?:usr/|usr.*)lib/udev/rules.d", "config"),
            (r"^/(?:usr/|usr.*)lib/modules-load.d", "config"),
            (r"^/(?:usr/|usr.*)lib/tmpfiles.d", "config"),
            (r"^/(?:usr/|usr.*)lib/sysusers.d", "config"),
            (r"^/(?:usr/|usr.*)lib/sysctl.d", "config"),
            (r"^/(?:usr/|usr.*)share/", "data"),
            (r"^/(?:usr/|usr.*)lib/perl5/", "perl", "/usr/lib/perl5/*"),
            # finally move any dynamically loadable plugins (not
            # perl/python/ruby/etc.. extensions) into lib package
            (r"^/(?:usr/|usr.*)lib/.*/[a-zA-Z0-9\.\_\+\-]*\.so", so_dest),
            (r"^/(?:usr/|usr.*)lib64/.*/[a-zA-Z0-9\.\_\+\-]*\.so", so_dest),
            (r"^/(?:usr/|usr.*)lib32/.*/[a-zA-Z0-9\.\_\+\-]*\.so", so_dest + '32'),
            #(r"^/(?:usr/|usr.*)lib64/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", so_dest),
            #(r"^/(?:usr/|usr.*)lib/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", so_dest),
            #(r"^/(?:usr/|usr.*)lib32/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", so_dest + '32'),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.txt$", "dev"),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.so$", so_dest),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.c$", "dev"),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.h$", "dev"),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.cpp$", "dev"),
            (r"^/(?:usr/|usr.*)/[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*.hpp$", "dev"),
            # locale data gets picked up via file_is_locale
            (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

        if self.package_name == "gcc":
            patterns_gcc = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                # main
                (r"^/usr/bin/x86_64-pc-linux-gnu-gcc-ar$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gcc-ranlib$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gcc-nm$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gcc$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-c\+\+$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gcc-\d+$", "main"),
                (r"^/usr/bin/gcc$", "main"),
                (r"^/usr/bin/cc$", "main"),
                (r"^/usr/bin/gcc-ar$", "main"),
                (r"^/usr/bin/gcc-nm$", "main"),
                (r"^/usr/bin/gcc-ranlib$", "main"),
                (r"^/usr/bin/gcov$", "main"),
                (r"^/usr/bin/gcov-tool$", "main"),
                (r"^/usr/lib/cpp$", "main"),
                (r"^/usr/bin/cpp$", "main"),
                (r"^/usr/bin/lto-dump$", "main"),
                (r"^/usr/lib64/libcc1[a-zA-Z0-9\.\_\+\-\/]*", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/include-fixed/", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/install-tools/", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/libcaf_[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/include/", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/lto1$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/lto-wrapper$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/collect2$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/cc1plus$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/g\+\+-mapper-server$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/cc1$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/plugin/gtype\.state$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/plugin/[a-zA-Z0-9\.\_\+\-]*\.so[0-9\.]*", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/plugin/include/", "main"),
                (r"^/usr/share/gcc-\d+$", "main"),
                (r"^/usr/lib64/[a-zA-Z0-9\.\_\+\-]*\.[ao]$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtbegin\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtbeginS\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtbeginT\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtend\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtendS\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtfastmath\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtprec32\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtprec64\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/crtprec80\.o$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/libgcc\.a$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/libgcc_eh\.a$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/libgcov\.a$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gfortran$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/f951$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/finclude", "main"),
                (r"^/usr/bin/f95$", "main"),
                (r"^/usr/bin/gfortran$", "main"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-g\+\+$", "main"),
                (r"^/usr/bin/c\+\+$", "main"),
                (r"^/usr/bin/g\+\+$", "main"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/liblto_plugin.so$", "main"),
                # dev
                (r"^/usr/lib64/libgcc_s\.so$", "dev"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/include/ssp", "dev"),
                (r"^/usr/lib64/libssp[a-zA-Z0-9\.\_\+\-\/]*\.a$", "dev"),
                (r"^/usr/lib64/libgomp\.a$", "dev"),
                (r"^/usr/lib64/libgomp\.spec$", "dev"),
                (r"^/usr/lib64/libgfortran\.so$", "dev"),
                (r"^/usr/lib64/libgfortran\.spec$", "dev"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/plugin/gengtype$", "dev"),
                (r"^/usr/lib64/libstdc\+\+\.so$", "dev"),
                (r"^/usr/lib64/libstdc\+\+\.a$", "dev"),
                (r"^/usr/lib64/libsupc\+\+\.a$", "dev"),
                (r"^/usr/include/c\+\+/[a-zA-Z0-9\.\_\+\-\/]*", "dev"),
                (r"^/usr/share/gdb/auto-load/usr/lib64/libstdc\+\+\.so\.[a-zA-Z0-9\.\_\+\-\/]*", "dev"),
                (r"^/usr/lib64/libstdc\+\+fs\.a$", "dev"),
                (r"^/usr/bin/gcov-dump$", "dev"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/finclude", "dev"),
                (r"^/usr/lib64/libatomic\.so$", "dev"),
                (r"^/usr/lib64/libitm\.so$", "dev"),
                (r"^/usr/lib64/libitm\.spec$", "dev"),
                (r"^/usr/lib64/libquadmath\.so$", "dev"),
                (r"^/usr/include/libgccjit\+\+\.h$", "dev"),
                (r"^/usr/include/libgccjit\.h$", "dev"),
                (r"^/usr/lib64/libgccjit\.so$", "dev"),
                # dev32
                (r"^/usr/lib32/crtbegin\.o$", "dev32"),
                (r"^/usr/lib32/crtbeginS\.o$", "dev32"),
                (r"^/usr/lib32/crtbeginT\.o$", "dev32"),
                (r"^/usr/lib32/crtend\.o$", "dev32"),
                (r"^/usr/lib32/crtendS\.o$", "dev32"),
                (r"^/usr/lib32/crtfastmath\.o$", "dev32"),
                (r"^/usr/lib32/crtprec32\.o$", "dev32"),
                (r"^/usr/lib32/crtprec64\.o$", "dev32"),
                (r"^/usr/lib32/crtprec80\.o$", "dev32"),
                (r"^/usr/lib32/libcaf_single\.a$", "dev32"),
                (r"^/usr/lib32/libgcc\.a$", "dev32"),
                (r"^/usr/lib32/libgcc_eh\.a$", "dev32"),
                (r"^/usr/lib32/libgcov\.a$", "dev32"),
                (r"^/usr/lib32/libstdc\+\+\.a$", "dev32"),
                (r"^/usr/lib32/libstdc\+\+\.so$", "dev32"),
                (r"^/usr/lib32/libstdc\+\+fs\.a$", "dev32"),
                (r"^/usr/lib32/libsupc\+\+\.a$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtbegin\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtbeginS\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtbeginT\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtend\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtendS\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtfastmath\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtprec32\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtprec64\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/crtprec80\.o$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/finclude/ieee_arithmetic\.mod$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/finclude/ieee_exceptions\.mod$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/finclude/ieee_features\.mod$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/libcaf_single\.a$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/libgcc\.a$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/libgcc_eh\.a$", "dev32"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/32/libgcov\.a$", "dev32"),
                (r"^/usr/lib32/libasan\.a$", "dev32"),
                (r"^/usr/lib32/libasan\.so$", "dev32"),
                (r"^/usr/lib32/libatomic\.a$", "dev32"),
                (r"^/usr/lib32/libatomic\.so$", "dev32"),
                (r"^/usr/lib32/libgfortran\.a$", "dev32"),
                (r"^/usr/lib32/libgfortran\.so$", "dev32"),
                (r"^/usr/lib32/libgfortran\.spec$", "dev32"),
                (r"^/usr/lib32/libgomp\.a$", "dev32"),
                (r"^/usr/lib32/libgomp\.so$", "dev32"),
                (r"^/usr/lib32/libgomp\.spec$", "dev32"),
                (r"^/usr/lib32/libitm\.a$", "dev32"),
                (r"^/usr/lib32/libitm\.so$", "dev32"),
                (r"^/usr/lib32/libitm\.spec$", "dev32"),
                (r"^/usr/lib32/libquadmath\.a$", "dev32"),
                (r"^/usr/lib32/libquadmath\.so$", "dev32"),
                (r"^/usr/lib32/libsanitizer\.spec$", "dev32"),
                (r"^/usr/lib32/libssp\.a$", "dev32"),
                (r"^/usr/lib32/libssp\.so$", "dev32"),
                (r"^/usr/lib32/libubsan\.a$", "dev32"),
                (r"^/usr/lib32/libubsan\.so$", "dev32"),
                (r"^/usr/share/gdb/auto-load/usr/lib32/libstdc\+\+.so\.[a-zA-Z0-9\.\_\+\-\/]*", "dev32"),
                # libgcc1
                (r"^/usr/lib64/libgcc_s\.so\.1$", "libgcc1", "", "", True),
                # libs-math
                (r"^/usr/lib64/lib(?:g(?:fortran|omp)|quadmath|atomic|itm|ssp)[a-zA-Z0-9\_\+\-]*\.so[a-zA-Z0-9\.\_\+\-]*", "libs-math"),
                (r"^/usr/lib64/haswell/lib(?:g(?:fortran|omp)|quadmath|atomic|itm|ssp)[a-zA-Z0-9\_\+\-]*\.so[a-zA-Z0-9\.\_\+\-]*", "libs-math"),
                # libgcc32
                (r"^/usr/lib32/lib(?:ssp_nonshared\.a|asan_preinit\.o)$", "libgcc32"),
                (r"^/usr/lib32/libgcc_s.so[a-zA-Z0-9\.\_\+\-]*", "libgcc32"),
                (r"^/usr/lib32/lib(?:quadmath|(?:gfortr|ubs)an|a(?:tomic|san)|gomp|itm|ssp)\.so[a-zA-Z0-9\.\_\+\-]*", "libgcc32"),
                (r"^/usr/lib32/lib(?:quadmath|(?:gfortr|ubs)an|a(?:tomic|san)|gomp|itm|ssp)\.a$", "libgcc32"),
                # libstdc++
                (r"^/usr/lib64/libstdc\+\+\.so\.[a-zA-Z0-9\.\_\+\-]*", "libstdc++", "", "", True),
                (r"^/usr/lib64/haswell/libstdc\+\+\.so\.[a-zA-Z0-9\.\_\+\-]*", "libstdc++", "", "", True),
                # jit
                (r"^/usr/lib64/libgccjit.so\.[a-zA-Z0-9\.\_\+\-]*", "jit"),
                # libstdc++32
                (r"^/usr/lib32/libstdc\+\+\.so\.[a-zA-Z0-9\.\_\+\-]*", "libstdc++32"),
                # gcc-doc
                (r"^/usr/share/man/[a-zA-Z0-9\.\_\+\-\/]*", "gcc-doc", "", "", True),
                (r"^/usr/share/info[a-zA-Z0-9\.\_\+\-\/]*", "gcc-doc", "", "", True),
                # go
                (r"^/usr/bin/gccgo$", "go"),
                (r"^/usr/bin/x86_64-pc-linux-gnu-gccgo$", "go"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/buildid$", "go"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/cgo$", "go"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/go1$", "go"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/test2json$", "go"),
                (r"^/usr/lib64/gcc/x86_64-pc-linux-gnu/\d+/vet$", "go"),
                (r"^/usr/lib64/libgo\.a$", "go"),
                (r"^/usr/lib64/libgo\.so$", "go"),
                (r"^/usr/lib64/libgobegin\.a$", "go"),
                (r"^/usr/lib64/libgolibbegin\.a$", "go"),
                (r"^/usr/libexec/gccgo/bin/[a-zA-Z0-9\.\_\+\-\/]*", "go"),
                # go-lib
                (r"^/usr/lib64/libgo\.so\.[0-9\.]*", "go-lib"),
                (r"^/usr/lib64/go/\d+/x86_64-pc-linux-gnu/[a-zA-Z0-9\.\_\+\-\/]*\.gox$", "go-lib"),
                # libubsan
                (r"^/usr/lib64/lib(?:sanit|ubsan|[alt]san)[a-zA-Z0-9\.\_\+\-\/]*", "libubsan"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_gcc:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "db":
            patterns_db = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                (r"/usr/lib64/libdb_cxx(?:\-5\.(?:3\.)?|\.)so", "cxx"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_db:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "nss":
            patterns_nss = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                (r"/usr/lib64/lib(?:(?:softokn|freebl)3\.chk|(?:softokn|freebl)3\.so|nss(?:dbm3\.(?:chk|so)|(?:util)?3\.so)|s(?:mime|sl)3\.so)", "lib"),
                (r"/usr/lib32/lib(?:(?:softokn|freebl)3\.chk|(?:softokn|freebl)3\.so|nss(?:dbm3\.(?:chk|so)|(?:util)?3\.so)|s(?:mime|sl)3\.so)", "lib32"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_nss:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "ncurses":
            patterns_ncurses = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                (r"^/usr/lib64/libncurses\+\+w?\.so\.6(?:\.2)?$", "lib-plusplus"),
                (r"^/usr/lib64/lib(?:ncurses\.so\.6(?:\.2)?|(?:panel|tinfo|form|menu)\.so\.6(?:\.2)?)$", "lib-narrow"),
                (r"^/usr/share/man.*$", "docs"),
                (r"^/usr/share/terminfo/i/ibm.*$", "data-rare"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_ncurses:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "glibc":
            patterns_glibc = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                # bin
                (r"^/usr/bin/(?:catchsegv|sln)$", "bin"),
                # nscd
                (r"^/usr/bin/nscd$", "nscd"),
                # utils
                (r"^/usr/bin/(?:p(?:cprofiledump|ld{2})|iconvconfig|tzselect|getconf|sotrus{2}|locale|xtrace|ge(?:nca|ten)t|iconv|l(?:d\.so|d{2})|zdump|sprof|zic)$", "utils"),
                # bench
                (r"^/usr/bin/bench-[a-zA-Z0-9\.\_\+\-\/]*", "bench"),
                (r"^/usr/lib64/glibc/benchmarks/[a-zA-Z0-9\.\_\+\-\/]*", "bench"),
                # libc6
                (r"^/usr/share/locale[a-zA-Z0-9\@\.\_\+\-\/]*", "libc6", "", "", True),
                (r"^/usr/share/defaults/etc/rpc$", "libc6", "", "", True),
                (r"^/usr/bin/ldconfig$", "libc6", "", "", True),
                (r"^/usr/lib64/audit/sotruss-lib\.so$", "libc6", "", "", True),
                (r"^/usr/lib64/gconv[a-zA-Z0-9\.\_\+\-\/]*", "libc6", "", "", True),
                (r"^/usr/lib64/glibc/getconf[a-zA-Z0-9\.\_\+\-\/]*", "libc6", "", "", True),
                (r"^/usr/lib64/(?:haswell/)?libm\.so\.\d+$", "libc6", "", "", True),
                (r"^/usr/lib64/ld\-(?:linux-x86-64\.so\.\d+|\d+\.\d+\.so)$", "libc6", "", "", True),
                (r"^/usr/lib64/libc(?:_malloc_debug\.so(?:\.\d+)?|(?:rypt)?\.so\.\d+|\-\d+\.\d+\.so)$", "libc6", "", "", True),
                (r"^/usr/lib64/libns(?:s_(?:(?:compat|hesiod)\.so\.\d+|files\.so\.\d+|(?:compat|hesiod)\.so|dns\.so\.\d+)|l\.so\.\d+)$", "libc6", "", "", True),
                (r"^/usr/lib64/lib(?:BrokenLocale\.so\.\d+|m(?:emusage|vec)\.so|mvec\.so\.\d+|(?:an|d)l\.so\.\d+)$", "libc6", "", "", True),
                (r"^/usr/lib64/lib(?:thread_db\.so\.\d+|pcprofile\.so|(?:pthread|r(?:esolv|t)|util)\.so\.\d+)$", "libc6", "", "", True),
                # libc6-dev
                (r"^/usr/bin/mtrace$", "libc6-dev", "", "", True),
                # lib-avx2
                (r"^/usr/lib64/haswell/(?:avx512_1/libm(?:vec)?\.so\.\d+|(?:libc(?:rypt)?|libmvec)\.so\.\d+)$", "lib-avx2"),
                # locale
                (r"^/usr/bin/localedef$", "locale"),
                (r"^/usr/share/i18n[a-zA-Z0-9\@\.\_\+\-\/]*", "locale"),
                # dev
                (r"^/usr/include/[a-zA-Z0-9\.\_\+\-\/]*", "dev"),
                (r"^/usr/lib64/(?:(?:gr|[MSr])crt\d+|(?:gcrt\d+|crt(?:\d+|i|n)))\.o$", "dev"),
                (r"^/usr/lib64/lib(?:pthread(?:_nonshared)?\.a|BrokenLocale\.so|(?:c_nonshared|(?:mvec|util|rt|dl))\.a|(?:thread_db|resolv|crypt|anl)\.so|[cm]\.so)$", "dev"),
                # dev32
                (r"^/usr/lib32/[a-zA-Z0-9\.\_\+\-\/]+\.[ao]$", "dev32"),
                # libc32
                (r"^/usr/lib32/[a-zA-Z0-9\.\_\+\-]+\.so(?:\.\d+)*$", "libc32"),
                (r"^/usr/lib32/gconv[a-zA-Z0-9\.\_\+\-\/]*", "libc32"),
                (r"^/usr/lib32/glibc/getconf[a-zA-Z0-9\.\_\+\-\/]*", "libc32"),
                (r"^/usr/lib32/audit/sotruss-lib\.so$", "libc32"),
                (r"^/usr/bin/lddlibc\d+$", "libc32"),
                (r"^/usr/lib/ld-linux.so.\d+$", "libc32"),
                # staticdev
                (r"^/usr/lib64/lib(?:BrokenLocale|(?:(?:m(?:\-\d+\.\d+|check)|resolv|crypt|anl|g)|[cm]))\.a$", "staticdev"),
                # doc
                (r"^/usr/share/info/libc\.info(?:-\d+)?$", "doc"),
                # extras
                (r"^/usr/bin/makedb$", "extras"),
                (r"^/usr/lib64/libnss_db\.so(?:\.\d+)?$", "extras"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_glibc:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "gmp":
            patterns_gmp = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                (r"^/usr/lib64/haswell/libgmp\.so\.(?:[0-9\.])*$", "lib-hsw"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_gmp:
                if self.file_pat_match(filename, *pat_args):
                    return

        if self.package_name == "linux":
            patterns_linux = [
                # Patterns for matching files, format is a tuple as follows:
                # (<raw pattern>, <package>, <optional replacement>, <optional prefix>, <-n subpackage:True or False>)
                # order matters, first match wins!
                (r"^/usr/lib/rpm[a-zA-Z0-9\.\_\+\-\/]*/[a-zA-Z0-9\.\_\+\-\/]*$", "main"),
                # applications
                (r"^/usr/bin", "applications"),
                (r"^/usr/sbin", "applications"),
                (r"^/usr/share", "applications"),
                (r"^/usr/lib64", "applications"),
                (r"^/usr/include", "applications"),
                # extra
                (r"^/usr/lib/kernel/System\.map-\d+\.\d+\.\d+-\d+\.native$", "extra"),
                (r"^/usr/lib/kernel/vmlinux-\d+\.\d+\.\d+-\d+\.native$", "extra"),
                # cpio
                (r"^/usr/lib/kernel/initrd-org\.clearlinux\.native\.\d+\.\d+\.\d+-\d+$", "cpio"),
                # dev
                (r"^/usr/lib/modules/\d+\.\d+\.\d+-\d+\.native/build", "dev"),
                # main
                (r"^/usr/lib/kernel", "main"),
                (r"^/usr/lib/modules", "main"),
                # locale data gets picked up via file_is_locale
                (r"^/(?:usr/|usr.*)share/locale/", "ignore")]

            for pat_args in patterns_linux:
                if self.file_pat_match(filename, *pat_args):
                    return

        for pat_args in patterns:
            if self.file_pat_match(filename, *pat_args):
                return

        if filename in self.excludes:
            return

        self.push_package_file(filename)

    def write_cargo_find_install_assets(self, content_name: str):
        """ Find custom assets to install such as docs, shell completion, etc """
        patterns = [
            # Patterns for matching files, format is a tuple as follows:
            # (<raw pattern>, <destination>, <raw_destination>)
            (
                r"^(?!.*\.so)[a-zA-Z0-9\_\+\-]*(?:\d*)*\.(\d)$",
                "/aot/var/lib/mock/clear-ripgrep/root/builddir/build/BUILDROOT/ripgrep-13.0.0-343.x86_64/usr/share/man/man",
                "/usr/share/man/man",
            ),
            (
                r"\.bash$",
                "/aot/var/lib/mock/clear-ripgrep/root/builddir/build/BUILDROOT/ripgrep-13.0.0-343.x86_64/usr/share/bash-completion/completions/",
                "/usr/share/bash-completion/completions/",
            ),
            (
                r"^_[a-zA-Z0-9\_\-\+]*$",
                "/aot/var/lib/mock/clear-ripgrep/root/builddir/build/BUILDROOT/ripgrep-13.0.0-343.x86_64/usr/share/zsh/site-functions/",
                "/usr/share/zsh/site-functions/",
            ),
            (
                r"\.fish$",
                "/aot/var/lib/mock/clear-ripgrep/root/builddir/build/BUILDROOT/ripgrep-13.0.0-343.x86_64/usr/share/fish/completions/",
                "/usr/share/fish/completions/",
            ),
            (
                r"\.zsh$",
                "/aot/var/lib/mock/clear-ripgrep/root/builddir/build/BUILDROOT/ripgrep-13.0.0-343.x86_64/usr/share/zsh/site-functions/",
                "/usr/share/zsh/site-functions/",
            ),
        ]
        target = f"{self.mock_dir}/clear-{self.package.uniqueext}/root/builddir/build/BUILD/{self.builddir}"
        prefix_to_remove = f"{self.mock_dir}/clear-{self.package.uniqueext}/root"
        builddir_prefixed = f"{prefix_to_remove}/builddir/build/BUILDROOT/{self.chroot_buildroot}/"
        for dirpath, dirnames, filenames in os.walk(target, followlinks=True):
            for filename in filenames:
                for i, pat_args in enumerate(patterns):
                    pat = re.compile(pat_args[0])
                    match = pat.search(filename)
                    if match:
                        if i == 0:  # man
                            add = True
                            build_filename_prefix = os.path.join(dirpath, filename)
                            for install_cmd in self.cargo_install_assets:
                                if install_cmd[2] == build_filename_prefix:
                                    add = False
                            if add:
                                man_number = match.group(1)
                                filename_cleaned = f"{pat_args[2]}{man_number}/{filename}"

                                builddir_prefixed_filename_cleaned = f"{builddir_prefixed}{filename_cleaned}"
                                build_filepath_prefixed = (
                                    f"install -D -m0644 {build_filename_prefix} {builddir_prefixed_filename_cleaned}"
                                )
                                print(f"man")
                                print(f"self.push_file({filename_cleaned}, {content_name})")
                                print(f"{build_filepath_prefixed}\n")
                                try:
                                    util.call_fast(build_filepath_prefixed, cwd=target)
                                except subprocess.CalledProcessError as err:
                                    print(f"Unable to install {build_filename_prefix} to {builddir_prefixed_filename_cleaned}")
                                    print(f"Error: {err}")
                                    sys.exit(1)
                                self.cargo_install_assets.append((builddir_prefixed_filename_cleaned, filename_cleaned, build_filename_prefix))
                                self.push_file(filename_cleaned, content_name)
                        elif i == 1:  # .bash
                            with open(os.path.join(dirpath, filename), mode="r", encoding="utf-8") as file_obj:
                                with mmap.mmap(file_obj.fileno(), length=0, access=mmap.ACCESS_READ) as mmap_obj:
                                    if mmap_obj.find(b"complete ") != -1:
                                        add = True
                                        build_filename_prefix = os.path.join(dirpath, filename)
                                        for install_cmd in self.cargo_install_assets:
                                            if install_cmd[2] == build_filename_prefix:
                                                add = False
                                        if add:
                                            filename_cleaned = f"{pat_args[2]}{os.path.splitext(filename)[0]}"
                                            builddir_prefixed_filename_cleaned = f"{builddir_prefixed}{filename_cleaned}"
                                            build_filepath_prefixed = (
                                                f"install -D -m0644 {build_filename_prefix} {builddir_prefixed_filename_cleaned}"
                                            )
                                            print(f"bash")
                                            print(f"self.push_file({filename_cleaned}, {content_name})")
                                            print(f"{build_filepath_prefixed}\n")
                                            try:
                                                util.call_fast(build_filepath_prefixed, cwd=target)
                                            except subprocess.CalledProcessError as err:
                                                print(
                                                    f"Unable to install {build_filename_prefix} to {builddir_prefixed_filename_cleaned}"
                                                )
                                                print(f"Error: {err}")
                                                sys.exit(1)
                                            self.cargo_install_assets.append(
                                                (builddir_prefixed_filename_cleaned, filename_cleaned, build_filename_prefix)
                                            )
                                            self.push_file(filename_cleaned, content_name)
                        elif i == 2:  # _zsh
                            with open(os.path.join(dirpath, filename), mode="r", encoding="utf-8") as file_obj:
                                with mmap.mmap(file_obj.fileno(), length=0, access=mmap.ACCESS_READ) as mmap_obj:
                                    if mmap_obj.find(b"compdef") != -1 or mmap_obj.find(b"autoload") != -1:
                                        add = True
                                        build_filename_prefix = os.path.join(dirpath, filename)
                                        for install_cmd in self.cargo_install_assets:
                                            if install_cmd[2] == build_filename_prefix:
                                                add = False
                                        if add:
                                            filename_cleaned = f"{pat_args[2]}{filename}"
                                            builddir_prefixed_filename_cleaned = f"{builddir_prefixed}{filename_cleaned}"
                                            build_filepath_prefixed = (
                                                f"install -D -m0644 {build_filename_prefix} {builddir_prefixed_filename_cleaned}"
                                            )
                                            print(f"zsh")
                                            print(f"self.push_file({filename_cleaned}, {content_name})")
                                            print(f"{build_filepath_prefixed}\n")
                                            try:
                                                util.call_fast(build_filepath_prefixed, cwd=target)
                                            except subprocess.CalledProcessError as err:
                                                print(
                                                    f"Unable to install {build_filename_prefix} to {builddir_prefixed_filename_cleaned}"
                                                )
                                                print(f"Error: {err}")
                                                sys.exit(1)
                                            self.cargo_install_assets.append(
                                                (builddir_prefixed_filename_cleaned, filename_cleaned, build_filename_prefix)
                                            )
                                            self.push_file(filename_cleaned, content_name)
                        elif i == 3:  # .fish
                            add = True
                            build_filename_prefix = os.path.join(dirpath, filename)
                            for install_cmd in self.cargo_install_assets:
                                if install_cmd[2] == build_filename_prefix:
                                    add = False
                            if add:
                                filename_cleaned = f"{pat_args[2]}{self.package.uniqueext}.fish"
                                builddir_prefixed_filename_cleaned = f"{builddir_prefixed}{filename_cleaned}"
                                build_filepath_prefixed = (
                                    f"install -D -m0644 {build_filename_prefix} {builddir_prefixed_filename_cleaned}"
                                )
                                print(f"fish")
                                print(f"self.push_file({filename_cleaned}, {content_name})")
                                print(f"{build_filepath_prefixed}\n")
                                try:
                                    util.call_fast(build_filepath_prefixed, cwd=target)
                                except subprocess.CalledProcessError as err:
                                    print(f"Unable to install {build_filename_prefix} to {builddir_prefixed_filename_cleaned}")
                                    print(f"Error: {err}")
                                    sys.exit(1)
                                self.cargo_install_assets.append((builddir_prefixed_filename_cleaned, filename_cleaned, build_filename_prefix))
                                self.push_file(filename_cleaned, content_name)
                        elif i == 4:  # .zsh
                            with open(os.path.join(dirpath, filename), mode="r", encoding="utf-8") as file_obj:
                                with mmap.mmap(file_obj.fileno(), length=0, access=mmap.ACCESS_READ) as mmap_obj:
                                    if mmap_obj.find(b"compdef") != -1 or mmap_obj.find(b"autoload") != -1:
                                        add = True
                                        build_filename_prefix = os.path.join(dirpath, filename)
                                        for install_cmd in self.cargo_install_assets:
                                            if install_cmd[2] == build_filename_prefix:
                                                add = False
                                        if add:
                                            filename_cleaned = f"{pat_args[2]}_{self.package.uniqueext}"
                                            builddir_prefixed_filename_cleaned = f"{builddir_prefixed}{filename_cleaned}"
                                            build_filepath_prefixed = (
                                                f"install -D -m0644 {build_filename_prefix} {builddir_prefixed_filename_cleaned}"
                                            )
                                            print(f"zsh")
                                            print(f"self.push_file({filename_cleaned}, {content_name})")
                                            print(f"{build_filepath_prefixed}\n")
                                            try:
                                                util.call_fast(build_filepath_prefixed, cwd=target)
                                            except subprocess.CalledProcessError as err:
                                                print(
                                                    f"Unable to install {build_filename_prefix} to {builddir_prefixed_filename_cleaned}"
                                                )
                                                print(f"Error: {err}")
                                                sys.exit(1)
                                            self.cargo_install_assets.append(
                                                (builddir_prefixed_filename_cleaned, filename_cleaned, build_filename_prefix)
                                            )
                                            self.push_file(filename_cleaned, content_name)


    def fix_broken_pkg_config_versioning(self, content_name: str):
        """ Fix broken RPM semantic versioning in pkg-config .pc files """
        target = f"{self.mock_dir}/clear-{self.package.uniqueext}/root/builddir/build/BUILD/{self.builddir}"
        prefix_to_remove = f"{self.mock_dir}/clear-{self.package.uniqueext}/root"
        builddir_prefixed = f"{prefix_to_remove}/builddir/build/BUILDROOT/{self.chroot_buildroot}/"
        pkg_configs = [(f.name, f.path) for f in scantree(builddir_prefixed) if f.is_file() and os.path.splitext(f.name)[1].lower() == ".pc"]

        if util.debugging:
            for pcs in pkg_configs:
                print_debug(f"{pcs}")

        semantic_ver_re = re.compile(rb"(?:Version:\s)(0|[1-9]\d*)(?:\.|\_)(0|[1-9]\d*)?(?:(?:\.|\_)(0|[1-9]\d*))?(?:(?:\.|\_)(0|[1-9]\d*))?((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*)?(?:\-((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*))?([a-zA-Z0-9\_\.\-]+)?")
        for pcs in pkg_configs:
            with open(pcs[1], mode="r+", encoding="utf-8") as file_obj:
                with mmap.mmap(file_obj.fileno(), length=0, access=mmap.ACCESS_WRITE) as mmap_obj:
                    if util.debugging:
                        for v in semantic_ver_re.findall(mmap_obj):
                            print_debug(v)
                    semantic_ver_re_match = semantic_ver_re.search(mmap_obj)
                    semantic_ver_re_match_group0 = ""
                    semantic_ver_re_match_group7 = ""
                    semantic_ver_re_match_group_start = 0
                    semantic_ver_re_match_group_end = 0
                    semantic_ver_re_match_group_size = 0
                    mmap_obj_size = 0
                    mmap_obj_new_size = 0
                    if semantic_ver_re_match:
                        semantic_ver_re_match_group0 = semantic_ver_re_match.group(0)
                        semantic_ver_re_match_group7 = semantic_ver_re_match.group(7)
                        if semantic_ver_re_match_group7 and semantic_ver_re_match_group0:
                            semantic_ver_re_match_group_start = semantic_ver_re_match.start(7)
                            semantic_ver_re_match_group_end = semantic_ver_re_match.end(7)
                            semantic_ver_re_match_group_size = semantic_ver_re_match_group_end-semantic_ver_re_match_group_start
                            mmap_obj_size = mmap_obj.size()
                            mmap_obj_new_size = (mmap_obj_size-semantic_ver_re_match_group_size)
                            if util.debugging:
                                print_debug(f"[{pcs[1]}]: {semantic_ver_re_match_group0}")
                                print_debug(f"Remove: {semantic_ver_re_match_group7} Start: {semantic_ver_re_match_group_start} - End: {semantic_ver_re_match_group_end} - Group(7) Size: {semantic_ver_re_match_group_size} - File size: {mmap_obj_size} - New file size: {mmap_obj_new_size}")
                            semantic_ver_re_match_group0_info_re1 = re.compile(r"(?:Version:\s([a-zA-Z0-9\_\-\.]+))")
                            semantic_ver_re_match_group7_info_re1 = re.compile(r"(?:([a-zA-Z0-9\_\-\.]+))")
                            semantic_ver_re_match_group0_info_re1_match = semantic_ver_re_match_group0_info_re1.search(semantic_ver_re_match_group0.decode('UTF-8'))
                            semantic_ver_re_match_group7_info_re1_match = semantic_ver_re_match_group7_info_re1.search(semantic_ver_re_match_group7.decode('UTF-8'))
                            if semantic_ver_re_match_group0_info_re1_match and semantic_ver_re_match_group7_info_re1_match:
                                print_info(f"[{pcs[1]}]")
                                print_info(f"{str(semantic_ver_re_match_group0_info_re1_match.group(1))} - Remove: {str(semantic_ver_re_match_group7_info_re1_match.group(1))}")
                            mmap_obj.move(semantic_ver_re_match_group_start, semantic_ver_re_match_group_end, (mmap_obj_size-semantic_ver_re_match_group_end))
                            mmap_obj.flush()
                            mmap_obj.resize(mmap_obj_new_size)
                            mmap_obj.close()
                            file_obj.close()


    def remove_file(self, filename):
        """Remove filename from local file list."""
        hit = False

        if filename in self.files:
            self.files.remove(filename)
            print("File no longer present: {}".format(filename))
            hit = True
        for pkg in self.packages:
            if filename in self.packages[pkg]:
                self.packages[pkg].remove(filename)
                print("File no longer present in {}: {}".format(pkg, filename))
                hit = True
        for pkg in self.subpackages:
            if filename in self.subpackages[pkg]:
                self.subpackages[pkg].remove(filename)
                print("File no longer present in subpackage {}: {}".format(pkg, filename))
                hit = True
        if hit:
            self.files_blacklist.add(filename)
            self.package.must_restart += 1

    def load_specfile(self, specfile):
        """Load a specfile instance with relevant information to be written to the spec file."""
        specfile.packages = self.packages
        specfile.subpackages = self.subpackages
        specfile.excludes = self.excludes
        specfile.locales = self.locales
        specfile.file_maps = self.file_maps
        specfile.cargo_install_assets = self.cargo_install_assets
        specfile.setuid = self.setuid

    def load_specfile_information(self, specfile, content):
        """Load a specfile instance to gather build information."""
        self.builddir = specfile.build_dirs[specfile.url]
        self.chroot_buildroot = f"{content.name}-{content.version}-{content.release}.x86_64"
        self.package_name = content.name
