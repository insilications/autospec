#!/usr/bin/python3

import mmap
import os
import re
import time
import types
import glob
import sys
import subprocess

from util import call, write_out, print_fatal
from collections import OrderedDict

url = "https://github.com/insilications/libx264.git"
clone_path = "/insilications/build/git-clr/x264-clr"
name = "arquivo"
git_tag_version_cmd1 = f"git describe --abbrev=0 --tags"
git_tag_version_cmd2 = f"git ls-remote --tags {url} | grep -oP '(\d+)(\.\d+)+' | sort -rV | head -1"
git_tag_version_cmd3 = f"git log -1 --date=format:%y.%m.%d --pretty=format:%cd"

try:
    process = subprocess.run(
        git_tag_version_cmd1,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )

except subprocess.CalledProcessError as err:
    print_fatal(f"cmd: {err}")
    print_fatal("Unable to get version {} from {}".format(clone_path, url))

outputVersion = process.stdout.rstrip("\n")
print(f"outputVersion: {outputVersion}")

if "No names found, cannot describe anything" in outputVersion:
    try:
        process = subprocess.run(
            git_tag_version_cmd2,
            check=False,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            cwd=clone_path,
        )

    except subprocess.CalledProcessError as err:
        print_fatal(f"cmd: {err}")
        print_fatal("Unable to get version {} from {}".format(clone_path, url))

    outputVersion = process.stdout.rstrip("\n")
    print(f"outputVersion2: {outputVersion}")

if outputVersion == "":
    try:
        process = subprocess.run(
            git_tag_version_cmd3,
            check=False,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            cwd=clone_path,
        )

    except subprocess.CalledProcessError as err:
            print_fatal(f"cmd: {err}")
            print_fatal("Unable to get version {} from {}".format(clone_path, url))

    outputVersion = process.stdout.rstrip("\n")
    print(f"outputVersion3: {outputVersion}")

if not outputVersion.startswith("v"):
    outputVersion = "v" + outputVersion
clone_file = f"{name}-{outputVersion}.tar.gz"
clone_file_abs = f"{name}-{outputVersion}.tar.gz"
print(f"{clone_file}")
print(f"{clone_file_abs}")
