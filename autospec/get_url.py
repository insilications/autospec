#!/usr/bin/env python

import re
import sys
import requests
import natsort
import glob
import os
import sys
import subprocess
import re
import util
from util import call, write_out, print_fatal, print_debug, print_info
from operator import attrgetter, itemgetter
from bs4 import BeautifulSoup

clone_path = "/insilications/apps/libva/"
#clone_path = "/aot/build/clearlinux/packages/fwts/"
url = "https://github.com/intel/libva.git"
#url = "https://github.com/insilications/fwts.git"
git_tag_version_cmd1 = f"git describe --abbrev=0 --tags"
#git_tag_version_cmd2 = f"git ls-remote --tags {url} | grep -oP '(?<=refs\/tags\/).*' | grep -oP '(?:\d+)(?:[-._]+\d+)+' | sort -rV | head -1"
git_tag_version_cmd2 = f"git ls-remote --refs --tags {url}"
git_tag_version_cmd3 = f"git log -1 --date=format:%d.%m.%y --pretty=format:%cd"

if util.debugging:
    print_debug(f"git_tag_version_cmd1: {git_tag_version_cmd1}")
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

outputVersion1 = process.stdout.rstrip("\n")
git_tag_version_cmd1_re = re.compile(r"(?:\d+)(?:[-._]+\d+)+")
git_tag_version_cmd1_match = git_tag_version_cmd1_re.search(outputVersion1)
if git_tag_version_cmd1_match:
    outputVersion1 = git_tag_version_cmd1_match.group(0).replace("_", ".").replace("-", ".")
    print_info(f"outputVersion1: {outputVersion1}")
else:
    outputVersion1 = ""

if util.debugging:
    print_debug(f"git_tag_version_cmd2: {git_tag_version_cmd2}")
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

outputVersion2 = process.stdout

if outputVersion2:
    #print("\n\nOutput2 1")
    #print(outputVersion2)

    git_tag_version_cmd2_re1 = re.compile(r"(?<=refs\/tags\/).*", re.MULTILINE)
    git_tag_version_cmd2_re2 = re.compile(r"(?:\d{8,8})|(?:^[a-zA-Z]+[-_.]+[a-zA-Z]+)|(?:^ww)|(?:-video)", re.MULTILINE)
    git_tag_version_cmd2_re3 = re.compile(r"(?:\d+)(?:[-._]+\d+)+")

    git_tag_version_cmd1_re1_match_list = git_tag_version_cmd2_re1.findall(outputVersion2)
    #print("\n\nOutput2 2")
    #for matched in git_tag_version_cmd1_re1_match_list:
        #print(matched)
    git_tag_version_cmd1_re1_match_list[:] = [x for x in git_tag_version_cmd1_re1_match_list if not git_tag_version_cmd2_re2.search(x)]
    #print("\n\nOutput2 3")
    #for matched in git_tag_version_cmd1_re1_match_list:
        #print(matched)
    git_tag_version_cmd1_re3_match_list = []
    for matched in git_tag_version_cmd1_re1_match_list:
        git_tag_version_cmd2_re3_match = git_tag_version_cmd2_re3.search(matched)
        if git_tag_version_cmd2_re3_match:
            git_tag_version_cmd1_re3_match_list.append(git_tag_version_cmd2_re3_match.group(0).replace("_", ".").replace("-", "."))

    #print("\n\nOutput2 4")
    #for matched in git_tag_version_cmd1_re3_match_list:
        #print(matched)

    git_tag_version_cmd1_re3_match_list_sorted1 = natsort.natsorted(git_tag_version_cmd1_re3_match_list)
    #print("\n\nOutput2 5")
    #for matched in git_tag_version_cmd1_re3_match_list_sorted1:
        #print(matched)
    outputVersion2 = git_tag_version_cmd1_re3_match_list_sorted1[-1]
    print_info(f"outputVersion2: {outputVersion2}")

outputVersionCompare = []
outputVersionCompareSorted = []
outputVersionFinal = ""
if outputVersion1:
    outputVersionCompare.append(outputVersion1)
if outputVersion2:
    outputVersionCompare.append(outputVersion2)

if len(outputVersionCompare) > 0:
    outputVersionCompareSorted = natsort.natsorted(outputVersionCompare)
    outputVersionFinal = outputVersionCompareSorted[-1]

if not outputVersionFinal:
    if util.debugging:
        print_debug(f"git_tag_version_cmd3: {git_tag_version_cmd3}")
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

    outputVersion3 = process.stdout.rstrip("\n")
    outputVersionFinal = outputVersion3
    print_info(f"outputVersion3: {outputVersion3}")

print_info(f"outputVersionFinal: {outputVersionFinal}")

