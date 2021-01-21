#!/bin/true
#
# git.py - part of autospec
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
# Commit to git
#

import glob
import os
import sys
import subprocess
import re

from util import call, write_out, print_fatal


def remove_clone_archive(path, clone_path, is_fatal):
    """Remove temporary clone_archive git folder."""
    try:
        call(f"rm -rf {clone_path}", cwd=path)
    except subprocess.CalledProcessError as err:
        if is_fatal:
            print_fatal("Unable to remove {}: {}".format(clone_path, err))


def clone_and_git_archive_all(path, name, url, branch, force_module, force_fullclone, is_fatal=True):
    """Clone package directly from a git repository."""
    cmd_args = f"{branch} {url} {name}"
    clone_path = f"{path}{name}"
    print("Teste: cwd=path " + path + "\n")
    print("Teste: force_module " + str(force_module) + "\n")
    print("Teste: force_fullclone " + str(force_fullclone) + "\n")

    try:
        if force_module is True:
            if force_fullclone is True:
                print("Teste: git clone -j8 --branch={}".format(cmd_args))
                call(f"git clone -j8 --branch={cmd_args}", cwd=path)
            else:
                print("Teste: git clone --depth 1 -j8 --branch={}".format(cmd_args))
                call(f"git clone --depth 1 -j8 --branch={cmd_args}", cwd=path)
        else:
            if force_fullclone is True:
                print("Teste: git clone --recurse-submodules -j8 --branch={}".format(cmd_args))
                call(f"git clone --recurse-submodules -j8 --branch={cmd_args}", cwd=path)
            else:
                print("Teste: git clone --depth 1 --shallow-submodules --recurse-submodules -j8 --branch={}".format(cmd_args))
                call(f"git clone --depth 1 --shallow-submodules --recurse-submodules -j8 --branch={cmd_args}", cwd=path)
    except subprocess.CalledProcessError as err:
        if is_fatal:
            remove_clone_archive(path, clone_path, is_fatal)
            print_fatal("Unable to clone {} in {}: {}".format(url, clone_path, err))
            sys.exit(1)

    try:
        git_tag_version_cmd = ""
        if force_fullclone is True:
            git_tag_version_cmd = "git describe --abbrev=0 --tags || git log -1 --date=format:%y.%m.%d --pretty=format:%cd"
        else:
            git_tag_version_cmd = f"git ls-remote --tags {url} | grep -oP '((?<=refs\/tags\/).*|(?<=refs\/tags\/))(v((\d+)(\.\d+))*)$|((\d+)(\.\d+)*)$' | sort -rV | head -1 || git log -1 --date=format:%y.%m.%d --pretty=format:%cd"
            # print("Teste: git_tag_version_cmd {}".format(git_tag_version_cmd))
        process = subprocess.run(
            git_tag_version_cmd,
            check=True,
            shell=True,
            stdout=subprocess.PIPE,
            text=True,
            universal_newlines=True,
            cwd=clone_path,
        )
    except subprocess.CalledProcessError as err:
        if is_fatal:
            remove_clone_archive(path, clone_path, is_fatal)
            print_fatal("Unable to get version from git describe in {} from {}: {}".format(clone_path, url, err))
            sys.exit(1)

    outputVersion = process.stdout.rstrip("\n")
    clone_file = f"{name}-{outputVersion}.tar.gz"
    clone_file_abs = f"{name}-{outputVersion}.tar.gz"
    print("Teste clone_path: " + clone_path + "\n")

    if os.path.isfile(f"{clone_path}/update_version"):
        print("Running update_version bash script")
        # call('./update_version', cwd=clone_path)
        write_out(
            os.path.join(clone_path, "package_version"),
            'AUTO_UPDATE=yes\nPACKAGE_VERSION="{}"'.format(re.search(r"(\d+)(\.\d+)+", outputVersion).group(0)),
        )
        try:
            call(f"tar --create --gzip --file={clone_file} {clone_path}/", cwd=path)
        except subprocess.CalledProcessError as err:
            if is_fatal:
                remove_clone_archive(path, clone_path, is_fatal)
                print_fatal("Unable to archive {} in {} from {}: {}".format(clone_path, clone_file, url, err))
                sys.exit(1)
    elif os.path.isfile(f"{clone_path}/version.sh"):
        print("Running version.sh bash script")
        try:
            process = subprocess.run(
                "./version.sh", check=True, shell=True, stdout=subprocess.PIPE, text=True, universal_newlines=True, cwd=clone_path
            )
        except subprocess.CalledProcessError as err:
            if is_fatal:
                remove_clone_archive(path, clone_path, is_fatal)
                print_fatal("Unable to run version.sh bash script in {} from {} {}: {}".format(clone_path, clone_file, url, err))
                sys.exit(1)
        outputVersion = process.stdout.rstrip("\n")
        foundVersion = re.search(r"(?<=#define\sX264_POINTVER\s\")(\d+)(\.\d+)+|(\d+)(\.\d+)+", outputVersion).group(0)
        clone_file = f"{name}-{foundVersion}.tar.gz"
        clone_file_abs = f"{name}-{foundVersion}.tar.gz"
        try:
            call(f"tar --create --gzip --file={clone_file} {clone_path}/", cwd=path)
        except subprocess.CalledProcessError as err:
            if is_fatal:
                remove_clone_archive(path, clone_path, is_fatal)
                print_fatal("Unable to archive {} in {} from {}: {}".format(clone_path, clone_file, url, err))
                sys.exit(1)
    else:
        try:
            call(f"tar --create --gzip --file={clone_file} {clone_path}/", cwd=path)
        except subprocess.CalledProcessError as err:
            if is_fatal:
                remove_clone_archive(path, clone_path, is_fatal)
                print_fatal("Unable to archive {} in {} from {}: {}".format(clone_path, clone_file, url, err))
                sys.exit(1)

    remove_clone_archive(path, clone_path, is_fatal)
    print("Teste clone_file: " + clone_file + "\n")
    print("Teste clone_file_abs: " + clone_file_abs + "\n")
    absolute_file_path = os.path.abspath(clone_file_abs)
    print("absolute_file_path: " + absolute_file_path + "\n")
    absolute_url_file = f"file://{absolute_file_path}"
    print("absolute_url_file: " + absolute_url_file + "\n")
    return absolute_url_file


def commit_to_git(config, name, success):
    """Update package's git tree for autospec managed changes."""
    path = config.download_path
    call("git init", stdout=subprocess.DEVNULL, cwd=path)

    # This config is used for setting the remote URI, so it is optional.
    if config.git_uri:
        try:
            call("git config --get remote.origin.url", cwd=path)
        except subprocess.CalledProcessError:
            upstream_uri = config.git_uri % {"NAME": name}
            call("git remote add origin %s" % upstream_uri, cwd=path)

    for config_file in config.config_files:
        call("git add %s" % config_file, cwd=path, check=False)
    for unit in config.sources["unit"]:
        call("git add %s" % unit, cwd=path)
    call("git add Makefile", cwd=path)
    call("git add upstream", cwd=path)
    call("bash -c 'shopt -s failglob; git add *.spec'", cwd=path)
    call("git add %s.tmpfiles" % name, check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add %s.sysusers" % name, check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add prep_prepend", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add pypi.json", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add build_prepend", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add build_prepend32", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add make_prepend", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add install_prepend", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add install_append", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add series", check=False, stderr=subprocess.DEVNULL, cwd=path)
    # Add/remove version specific patch lists
    for filename in glob.glob("series.*"):
        base, version = filename.split(".", 1)
        if version in config.versions:
            call("git add {}".format(filename), check=False, stderr=subprocess.DEVNULL, cwd=path)
        else:
            call("git rm {}".format(filename), check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add -f *.asc'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add -f *.sig'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add -f *.sha256'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add -f *.sign'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add -f *.pkey'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure32", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure64", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure_avx2", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure_avx512", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add make_check_command", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add *.patch'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("bash -c 'shopt -s failglob; git add *.nopatch'", check=False, stderr=subprocess.DEVNULL, cwd=path)
    for item in config.transforms.values():
        call("git add {}".format(item), check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add release", cwd=path)
    call("git add symbols", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add symbols32", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add used_libs", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add used_libs32", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add testresults", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add profile_payload", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add options.conf", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add configure_misses", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add whatrequires", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add description", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add attrs", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add altflags1", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add altflags_pgo", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add altflags1_32", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git add altflags_pgo_32", check=False, stderr=subprocess.DEVNULL, cwd=path)

    # remove deprecated config files
    call("git rm make_install_append", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm prep_append", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm use_clang", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm use_lto", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm use_avx2", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm fast-math", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm broken_c++", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm skip_test_suite", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm optimize_size", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm asneeded", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm broken_parallel_build", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm pgo", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm unit_tests_must_pass", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm funroll-loops", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm keepstatic", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm allow_test_failures", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm no_autostart", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm insecure_build", check=False, stderr=subprocess.DEVNULL, cwd=path)
    call("git rm conservative_flags", check=False, stderr=subprocess.DEVNULL, cwd=path)

    # add a gitignore
    ignorelist = [
        ".*~",
        "*~",
        "*.info",
        "*.mod",
        "*.swp",
        ".repo-index",
        "*.log",
        "build.log.round*",
        "*.tar.*",
        "*.tgz",
        "!*.tar.*.*",
        "*.zip",
        "*.jar",
        "*.pom",
        "*.xml",
        "commitmsg",
        "results/",
        "rpms/",
        "for-review.txt",
        "*.tar",
        "*.gem",
        "",
    ]
    write_out(os.path.join(path, ".gitignore"), "\n".join(ignorelist))
    call("git add .gitignore", check=False, stderr=subprocess.DEVNULL, cwd=path)

    if success == 0:
        return

    call("git commit -a -F commitmsg ", cwd=path)
    call("rm commitmsg", cwd=path)
