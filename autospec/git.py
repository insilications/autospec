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
import util
import download
import natsort
import fastnumbers
import validators
from util import call, write_out, print_fatal, print_debug, print_info
from lastversion import latest as latest_pypi

def read_file(path):
    """Read full file at path."""
    try:
        with open(path, "r") as f:
            return f.readlines()
    except EnvironmentError:
        return []


def read_script_file(path):
    """Read RPM script snippet file at path.

    Returns verbatim, except for possibly the first line.

    If the config file does not exist (or is not expected to exist)
    in the package git repo, specify 'track=False'.
    """
    lines = read_file(path)
    if len(lines) > 0 and (lines[0].startswith("#!") or lines[0].startswith("# -*- ")):
        lines = lines[1:]
    # Remove any trailing whitespace and newlines. The newlines are later
    # restored by writer functions.
    return [line.rstrip() for line in lines]


def get_git_remote_url(target, clone_path):
    """Get the remote url for a targeted git repository."""
    git_config_get = f"git config --get remote.{target}.url"
    process = subprocess.run(
        git_config_get,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )
    remote_url = process.stdout.rstrip("\n")
    return remote_url


def git_describe_custom_re(clone_path, conf):
    outputVersion1 = ""
    git_describe_cmd1 = f"git describe --abbrev=0 --tags"
    git_describe_cmd1_result = ""
    process = subprocess.run(
        git_describe_cmd1,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )
    git_describe_cmd1_result = process.stdout

    if git_describe_cmd1_result:
        if util.debugging:
            print_debug(f"conf.custom_git_re2: {conf.custom_git_re2}")
        git_describe_cmd2_re1_pre = r"{0}".format(conf.custom_git_re2)
        git_describe_cmd2_re1 = re.Pattern
        try:
            git_describe_cmd2_re1 = re.compile(git_describe_cmd2_re1_pre, re.MULTILINE)
        except re.error as err:
                print_fatal(f"Custom git regex: {git_describe_cmd2_re1.pattern}")
                print_fatal(f"Unable to create custom git regex: {err}")
        print_info(f"Custom git regex 2: {git_describe_cmd2_re1.pattern}")
        git_describe_cmd2_re1_result = git_describe_cmd2_re1.search(git_describe_cmd1_result)
        if git_describe_cmd2_re1_result:
            if util.debugging:
                print_debug(f"{git_describe_cmd2_re1_result.group(1)}.{git_describe_cmd2_re1_result.group(2)}.{git_describe_cmd2_re1_result.group(3)}.{git_describe_cmd2_re1_result.group(4)}.{git_describe_cmd2_re1_result.group(5)}.{git_describe_cmd2_re1_result.group(6)}.{git_describe_cmd2_re1_result.group(7)}")
            if git_describe_cmd2_re1_result.group(1):
                outputVersion1 = f"{git_describe_cmd2_re1_result.group(1)}"
            if git_describe_cmd2_re1_result.group(2):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(2)}"
            if git_describe_cmd2_re1_result.group(3):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(3)}"
            if git_describe_cmd2_re1_result.group(4):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(4)}"
            if git_describe_cmd2_re1_result.group(5):
                outputVersion1 = f"{outputVersion1}{git_describe_cmd2_re1_result.group(5)}"
            return outputVersion1


def git_describe(clone_path):
    outputVersion1 = ""
    git_describe_cmd1 = f"git describe --abbrev=0 --tags"
    git_describe_cmd1_result = ""
    process = subprocess.run(
        git_describe_cmd1,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )
    git_describe_cmd1_result = process.stdout

    if git_describe_cmd1_result:
        git_describe_cmd2_re1 = re.compile(r"(?:^(?:[a-zA-Z]+[0-9]?[a-zA-Z0-9]*[\-]+)?|^(?:[vV]+)?)(0|[1-9]\d*)(?:\.|\_)(0|[1-9]\d*)?(?:(?:\.|\_)(0|[1-9]\d*))?(?:(?:\.|\_)(0|[1-9]\d*))?((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*)?(?:\-((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*))?([a-zA-Z0-9\_\.\-]+)?", re.MULTILINE)
        git_describe_cmd2_re1_result = git_describe_cmd2_re1.search(git_describe_cmd1_result)
        if git_describe_cmd2_re1_result:
            if util.debugging:
                print_debug(f"{git_describe_cmd2_re1_result.group(1)}.{git_describe_cmd2_re1_result.group(2)}.{git_describe_cmd2_re1_result.group(3)}.{git_describe_cmd2_re1_result.group(4)}.{git_describe_cmd2_re1_result.group(5)}.{git_describe_cmd2_re1_result.group(6)}.{git_describe_cmd2_re1_result.group(7)}")
            if git_describe_cmd2_re1_result.group(1):
                outputVersion1 = f"{git_describe_cmd2_re1_result.group(1)}"
            if git_describe_cmd2_re1_result.group(2):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(2)}"
            if git_describe_cmd2_re1_result.group(3):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(3)}"
            if git_describe_cmd2_re1_result.group(4):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(4)}"
            if git_describe_cmd2_re1_result.group(5):
                outputVersion1 = f"{outputVersion1}{git_describe_cmd2_re1_result.group(5)}"
            if git_describe_cmd2_re1_result.group(7):
                outputVersion1 = f"{outputVersion1}.{git_describe_cmd2_re1_result.group(7)}"
            return outputVersion1


def git_ls_remote_custom_re(remote_url_cmd, clone_path, path, conf):
    git_ls_remote_cmd1_result = ""
    git_ls_remote_cmd1_re1_result_pre_sort = []
    git_ls_remote_cmd1_re1_result_sorted = []

    process = subprocess.run(
        remote_url_cmd,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )
    git_ls_remote_cmd1_result = process.stdout

    git_ls_remote_cmd1_re1_result = []
    if git_ls_remote_cmd1_result:
        git_ls_remote_cmd1_re1 = re.compile(r"(?<=refs\/tags\/).*", re.MULTILINE)
        git_ls_remote_cmd1_re1_result = git_ls_remote_cmd1_re1.findall(git_ls_remote_cmd1_result)
        if util.debugging:
            if git_ls_remote_cmd1_re1_result:
                for r in git_ls_remote_cmd1_re1_result:
                    print_debug(r)

        if git_ls_remote_cmd1_re1_result:
            if util.debugging:
                    print_debug(f"conf.custom_git_re: {conf.custom_git_re2}")
            git_ls_remote_cmd1_re4_pre = r"{0}".format(conf.custom_git_re2)
            git_ls_remote_cmd1_re4 = re.Pattern
            try:
                git_ls_remote_cmd1_re4 = re.compile(git_ls_remote_cmd1_re4_pre, re.MULTILINE)
            except re.error as err:
                    print_fatal(f"Custom git regex: {git_ls_remote_cmd1_re4.pattern}")
                    print_fatal(f"Unable to create custom git regex: {err}")
            for r in git_ls_remote_cmd1_re1_result:
                git_ls_remote_cmd1_re4_result = git_ls_remote_cmd1_re4.search(r)
                if git_ls_remote_cmd1_re4_result:
                    if util.debugging:
                        print_debug(f"{git_ls_remote_cmd1_re4_result.group(1)}.{git_ls_remote_cmd1_re4_result.group(2)}.{git_ls_remote_cmd1_re4_result.group(3)}.{git_ls_remote_cmd1_re4_result.group(4)}.{git_ls_remote_cmd1_re4_result.group(5)}.{git_ls_remote_cmd1_re4_result.group(6)}.{git_ls_remote_cmd1_re4_result.group(7)}")
                    if git_ls_remote_cmd1_re4_result.group(1):
                        outputVersionPre = f"{git_ls_remote_cmd1_re4_result.group(1)}"
                    if git_ls_remote_cmd1_re4_result.group(2):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(2)}"
                    if git_ls_remote_cmd1_re4_result.group(3):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(3)}"
                    if git_ls_remote_cmd1_re4_result.group(4):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(4)}"
                    if git_ls_remote_cmd1_re4_result.group(5):
                        outputVersionPre = f"{outputVersionPre}{git_ls_remote_cmd1_re4_result.group(5)}"
                    if util.debugging:
                        print_debug(f"outputVersionPre: {outputVersionPre}")
                    git_ls_remote_cmd1_re1_result_pre_sort.append(outputVersionPre)
            if git_ls_remote_cmd1_re1_result_pre_sort:
                git_ls_remote_cmd1_re1_result_sorted = natsort.natsorted(git_ls_remote_cmd1_re1_result_pre_sort, key=lambda x: x.replace('.', '~')+'z')
    if git_ls_remote_cmd1_re1_result_sorted:
        return git_ls_remote_cmd1_re1_result_sorted[-1]
    else:
        return ""


def git_ls_remote(remote_url_cmd, clone_path, path, conf):
    git_ls_remote_cmd1_result = ""
    git_ls_remote_cmd1_re1_result_pre_sort = []
    git_ls_remote_cmd1_re1_result_sorted = []

    process = subprocess.run(
        remote_url_cmd,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        cwd=clone_path,
    )
    git_ls_remote_cmd1_result = process.stdout

    git_ls_remote_cmd1_re1_result = []
    if git_ls_remote_cmd1_result:
        git_ls_remote_cmd1_re1 = re.compile(r"(?<=refs\/tags\/).*", re.MULTILINE)
        git_ls_remote_cmd1_re1_result = git_ls_remote_cmd1_re1.findall(git_ls_remote_cmd1_result)
        if util.debugging:
            if git_ls_remote_cmd1_re1_result:
                for r in git_ls_remote_cmd1_re1_result:
                    print_debug(r)

        if git_ls_remote_cmd1_re1_result:
            git_ls_remote_cmd1_re2_result_delete = []
            default_re = r"(?:^\d{8,8})|(?:^[a-zA-Z]+[-_.]+[a-zA-Z]+)"
            if conf.custom_git_re:
                if util.debugging:
                    print_debug(f"conf.custom_git_re: {conf.custom_git_re}")
                git_ls_remote_cmd1_re2_pre = r"{default_re}|{custom_re}".format(default_re=default_re, custom_re=conf.custom_git_re)
                git_ls_remote_cmd1_re2 = re.Pattern
                try:
                    git_ls_remote_cmd1_re2 = re.compile(git_ls_remote_cmd1_re2_pre, re.MULTILINE)
                except re.error as err:
                        print_fatal(f"Custom git regex: {git_ls_remote_cmd1_re2.pattern}")
                        print_fatal(f"Unable to create custom git regex: {err}")
                print_info(f"Custom git regex: {git_ls_remote_cmd1_re2.pattern}")
            else:
                git_ls_remote_cmd1_re2 = re.compile(default_re, re.MULTILINE)
            if util.debugging:
                print_debug("Reverse: '{git_ls_remote_cmd1_re2}':")
            for i, r in enumerate(git_ls_remote_cmd1_re1_result):
                git_ls_remote_cmd1_re2_result = git_ls_remote_cmd1_re2.search(r)
                if git_ls_remote_cmd1_re2_result:
                    if util.debugging:
                        print_debug(f"Delete: {i} - {r}")
                    git_ls_remote_cmd1_re2_result_delete.append(i)
            for d in sorted(git_ls_remote_cmd1_re2_result_delete, reverse=True):
                del git_ls_remote_cmd1_re1_result[d]
            if util.debugging:
                for r in git_ls_remote_cmd1_re1_result:
                    print_debug(r)

        if git_ls_remote_cmd1_re1_result:
            git_ls_remote_cmd1_re3_result_delete = []
            git_ls_remote_cmd1_re3 = re.compile(r"(?:^(?:[a-zA-Z]+[0-9]?[a-zA-Z0-9]*[\-]+)?|^(?:[vV]+)?)(0|[1-9]\d*)(?:\.|\_)(0|[1-9]\d*)?(?:(?:\.|\_)(0|[1-9]\d*))?(?:(?:\.|\_)(0|[1-9]\d*))?((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*)?(?:\-((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*))?([a-zA-Z0-9\_\.\-]+)?", re.MULTILINE)
            if util.debugging:
                print_debug("'(?:^(?:[a-zA-Z]+[0-9]?[a-zA-Z0-9]*[\-]+)?|^(?:[vV]+)?)(0|[1-9]\d*)(?:\.|\_)(0|[1-9]\d*)?(?:(?:\.|\_)(0|[1-9]\d*))?(?:(?:\.|\_)(0|[1-9]\d*))?((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*)?(?:\-((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*))?([a-zA-Z0-9\_\.\-]+)?':")
            for i, r in enumerate(git_ls_remote_cmd1_re1_result):
                git_ls_remote_cmd1_re3_result = git_ls_remote_cmd1_re3.search(r)
                if not git_ls_remote_cmd1_re3_result:
                    if util.debugging:
                        print_debug(f"Delete: {i} - {r}")
                    git_ls_remote_cmd1_re3_result_delete.append(i)
            for d in sorted(git_ls_remote_cmd1_re3_result_delete, reverse=True):
                del git_ls_remote_cmd1_re1_result[d]
            if util.debugging:
                for r in git_ls_remote_cmd1_re1_result:
                    print_debug(r)

        if git_ls_remote_cmd1_re1_result:
            git_ls_remote_cmd1_re4 = re.compile(r"(?:^(?:[a-zA-Z]+[0-9]?[a-zA-Z0-9]*[\-]+)?|^(?:[vV]+)?)(0|[1-9]\d*)(?:\.|\_)(0|[1-9]\d*)?(?:(?:\.|\_)(0|[1-9]\d*))?(?:(?:\.|\_)(0|[1-9]\d*))?((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*)?(?:\-((?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z][0-9a-zA-Z]*))*))?([a-zA-Z0-9\_\.\-]+)?", re.MULTILINE)
            for r in git_ls_remote_cmd1_re1_result:
                git_ls_remote_cmd1_re4_result = git_ls_remote_cmd1_re4.search(r)
                if git_ls_remote_cmd1_re4_result:
                    if util.debugging:
                        print_debug(f"{git_ls_remote_cmd1_re4_result.group(1)}.{git_ls_remote_cmd1_re4_result.group(2)}.{git_ls_remote_cmd1_re4_result.group(3)}.{git_ls_remote_cmd1_re4_result.group(4)}.{git_ls_remote_cmd1_re4_result.group(5)}.{git_ls_remote_cmd1_re4_result.group(6)}.{git_ls_remote_cmd1_re4_result.group(7)}")
                    if git_ls_remote_cmd1_re4_result.group(1):
                        outputVersionPre = f"{git_ls_remote_cmd1_re4_result.group(1)}"
                    if git_ls_remote_cmd1_re4_result.group(2):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(2)}"
                    if git_ls_remote_cmd1_re4_result.group(3):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(3)}"
                    if git_ls_remote_cmd1_re4_result.group(4):
                        outputVersionPre = f"{outputVersionPre}.{git_ls_remote_cmd1_re4_result.group(4)}"
                    if git_ls_remote_cmd1_re4_result.group(5):
                        outputVersionPre = f"{outputVersionPre}{git_ls_remote_cmd1_re4_result.group(5)}"
                    if util.debugging:
                        print_debug(f"outputVersionPre: {outputVersionPre}")
                    git_ls_remote_cmd1_re1_result_pre_sort.append(outputVersionPre)
            if git_ls_remote_cmd1_re1_result_pre_sort:
                git_ls_remote_cmd1_re1_result_sorted = natsort.natsorted(git_ls_remote_cmd1_re1_result_pre_sort, key=lambda x: x.replace('.', '~')+'z')
    if git_ls_remote_cmd1_re1_result_sorted:
        return git_ls_remote_cmd1_re1_result_sorted[-1]
    else:
        return ""


def find_version_git(url, clone_path, path, conf):
    """Get the highest semantic versioning avaiable for a package from git repositories."""
    add_versions = []
    add_versions_file = f"{path}add_versions"
    add_versions_check = False
    if os.path.isfile(add_versions_file):
        add_versions = read_script_file(add_versions_file)
        if len(add_versions) > 0:
            add_versions_check = True

    remote_url_origin = ""
    remote_url_insilications = ""
    remote_url_origin = get_git_remote_url(target="origin", clone_path=clone_path)
    remote_url_insilications = get_git_remote_url(target="insilications", clone_path=clone_path)

    git_tag_version_cmd2 = f"git ls-remote --refs --tags {remote_url_origin}"
    git_tag_version_cmd3 = f"git ls-remote --refs --tags {remote_url_insilications}"
    git_tag_version_cmd4 = f"git log -1 --date=format:%-d.%-m.%Y --pretty=format:%cd"
    outputVersion1 = ""
    outputVersion2 = ""
    outputVersion3 = ""
    outputDateVersion = ""
    outputVersionFinal = ""

    if conf.custom_git_re2:
        outputVersion1 = git_describe_custom_re(clone_path=clone_path, conf=conf)
    else:
        outputVersion1 = git_describe(clone_path=clone_path)
    if remote_url_origin:
        if conf.custom_git_re2:
            outputVersion2 = git_ls_remote_custom_re(remote_url_cmd=git_tag_version_cmd2, clone_path=clone_path, path=path, conf=conf)
        else:
            outputVersion2 = git_ls_remote(remote_url_cmd=git_tag_version_cmd2, clone_path=clone_path, path=path, conf=conf)
    if remote_url_insilications:
        if conf.custom_git_re2:
            outputVersion3 = git_ls_remote_custom_re(remote_url_cmd=git_tag_version_cmd3, clone_path=clone_path, path=path, conf=conf)
        else:
            outputVersion3 = git_ls_remote(remote_url_cmd=git_tag_version_cmd3, clone_path=clone_path, path=path, conf=conf)

    outputVersionCompare = []
    outputVersionCompareSorted = []
    if outputVersion1:
        print_info(f"git describe --abbrev=0 --tags")
        print_info(f"outputVersion1: {outputVersion1}")
        outputVersionCompare.append(outputVersion1)
    if outputVersion2:
        print_info(f"{git_tag_version_cmd2}")
        print_info(f"outputVersion2: {outputVersion2}")
        outputVersionCompare.append(outputVersion2)
    if outputVersion3:
        print_info(f"{git_tag_version_cmd3}")
        print_info(f"outputVersion3: {outputVersion3}")
        outputVersionCompare.append(outputVersion3)
    if add_versions_check:
        for line in add_versions:
            print_info(f"add_versions: {line}")
            outputVersionCompare.append(line)

    if len(outputVersionCompare) > 0:
        outputVersionCompareSorted = natsort.natsorted(outputVersionCompare, key=lambda x: x.replace('.', '~')+'z')
        outputVersionFinal = outputVersionCompareSorted[-1]

    if not outputVersionFinal:
        print_info("Need to use date")
        if util.debugging:
            print_debug(f"git_tag_version_cmd4: {git_tag_version_cmd4}")
        process = subprocess.run(
            git_tag_version_cmd4,
            check=False,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            cwd=clone_path,
        )

        outputDateVersion = process.stdout.rstrip("\n")
        outputVersionFinal = outputDateVersion
        print_info(f"outputDateVersion: {outputDateVersion}")

    print_info(f"outputVersionFinal winner: {outputVersionFinal}")
    return outputVersionFinal


def remove_clone_archive(path, clone_path, is_fatal):
    """Remove temporary clone_archive git folder."""
    try:
        call(f"rm -rf {clone_path}", cwd=path)
    except subprocess.CalledProcessError as err:
        if is_fatal:
            print_fatal("Unable to remove {}: {}".format(clone_path, err))


def git_clone(url, path, cmd_args, clone_path, force_module, force_fullclone, is_fatal=True):
    try:
        if force_module is True:
            if force_fullclone is True:
                print_info(f"git clone -j8 --branch={cmd_args}")
                call(f"git clone -j8 --branch={cmd_args}", cwd=path)
            else:
                print_info(f"git clone --single-branch -j8 --branch={cmd_args}")
                call(f"git clone --single-branch -j8 --branch={cmd_args}", cwd=path)
        else:
            if force_fullclone is True:
                print_info(f"git clone --recurse-submodules -j8 --branch={cmd_args}")
                call(f"git clone --recurse-submodules -j8 --branch={cmd_args}", cwd=path)
            else:
                print_info(f"git clone --single-branch --shallow-submodules --recurse-submodules -j8 --branch={cmd_args}")
                call(f"git clone --single-branch --shallow-submodules --recurse-submodules -j8 --branch={cmd_args}", cwd=path)
    except subprocess.CalledProcessError as err:
        if is_fatal:
            remove_clone_archive(path, clone_path, is_fatal)
            print_fatal(f"Unable to clone {url} in {clone_path}: {err}")
            sys.exit(1)


def git_archive_all(path, name, url, branch, force_module, force_fullclone, conf, is_fatal=True):
    """Clone package directly from a git repository."""
    cmd_args = f"{branch} {url} {name}"
    clone_path = f"{path}{name}"
    if util.debugging:
        print_debug(f"path: {path}")
        print_debug(f"force_module {str(force_module)}")
        print_debug(f"force_fullclone {str(force_fullclone)}")

    is_url = validators.url(url)
    if is_url is True:
        if "pypi.org/project/" in url:
            latest_pypi_source = latest_pypi(url, output_format="source", pre_ok=True)
            print_info(f"pypi.org/project/: {latest_pypi_source}")
            latest_pypi_source_basename=os.path.basename(latest_pypi_source)
            download.do_curl(latest_pypi_source, dest=f"./{latest_pypi_source_basename}", is_fatal=True)
            absolute_url_file=f"file://{os.path.abspath(latest_pypi_source_basename)}"
            return absolute_url_file
        else:
            git_clone(url=url, path=path, cmd_args=cmd_args, clone_path=clone_path, force_module=force_module, force_fullclone=force_fullclone, is_fatal=is_fatal)
            try:
                outputVersion = find_version_git(url=url, clone_path=clone_path, path=path, conf=conf)
            except:
                if is_fatal:
                    remove_clone_archive(path, clone_path, is_fatal)
                    print_fatal(f"Unexpected error: {sys.exc_info()[0]}")
                    sys.exit(1)

            if not outputVersion.startswith("v") and not outputVersion.startswith("V"):
                outputVersion = f"v{outputVersion}"

            clone_file = f"{name}-{outputVersion}.tar.gz"
            absolute_file_path = os.path.abspath(clone_file)
            absolute_url_file = f"file://{absolute_file_path}"
            if util.debugging:
                print_debug(f"{clone_file}")
                print_debug(f"clone_path: {clone_path}")
                print_debug(f"absolute_file_path: {absolute_file_path}")
                print_debug(f"absolute_url_file: {absolute_url_file}")
            try:
                process = subprocess.run(
                    f"tar --create --file=- {clone_path}/ | pigz -9 -p 16 > {clone_file}",
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=path,
                )
            except subprocess.CalledProcessError as err:
                remove_clone_archive(path, clone_path, is_fatal)
                print_fatal(f"Unable to archive {clone_path} in {clone_file} from {url}: {err}")
                sys.exit(1)

            remove_clone_archive(path, clone_path, is_fatal)
            return absolute_url_file
    else:
        if os.path.isdir(url):
            clone_path = url
            outputVersion = find_version_git(url=url, clone_path=clone_path, path=path, conf=conf)

            if not outputVersion.startswith("v") and not outputVersion.startswith("V"):
                outputVersion = f"v{outputVersion}"

            clone_file = f"{name}-{outputVersion}.tar.gz"
            clone_path_norm = os.path.normpath(clone_path)
            absolute_file_path = os.path.abspath(clone_file)
            absolute_url_file = f"file://{absolute_file_path}"
            if util.debugging:
                print_debug(f"{clone_file}")
                print_debug(f"clone_path: {clone_path}")
                print_debug(f"absolute_file_path: {absolute_file_path}")
                print_debug(f"absolute_url_file: {absolute_url_file}")
            try:
                process = subprocess.run(
                    f"tar --create --file=- {os.path.basename(clone_path_norm)}/ | pigz -9 -p 16 > {absolute_file_path}",
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=os.path.dirname(clone_path_norm),
                )
            except subprocess.CalledProcessError as err:
                if is_fatal:
                    remove_clone_archive(path, clone_path, is_fatal)
                    print_fatal(f"Unable to archive {clone_path} in {clone_file} from {url}: {err}")
                    sys.exit(1)
            return absolute_url_file
        else:
            print_fatal(f"Unable to archive {clone_path} in {clone_file} from {url}")
            sys.exit(1)


def commit_to_git(config, name, success):
    """Update package's git tree for autospec managed changes."""
    path = config.download_path
    call("git init -b main", stdout=subprocess.DEVNULL, cwd=path)

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
    call("git add configure64_pgo", check=False, stderr=subprocess.DEVNULL, cwd=path)
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
