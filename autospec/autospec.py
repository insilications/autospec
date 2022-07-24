#!/usr/bin/python3
#
# autospec.py - part of autospec
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

import argparse
import configparser
import os
import re
import sys
import tempfile

from abireport import examine_abi
import build
import buildreq
import check
import commitmessage
import config
import files
import git
import license
from logcheck import logcheck
import pkg_integrity
import pkg_scan
import specdescription
import specfiles
import tarball
import util
import shutil
import subprocess
import download
from util import binary_in_path, print_fatal, write_out, print_debug, print_warning, print_info

sys.path.append(os.path.dirname(__file__))

def link_new_rpms_here():
    make_cmd = f"make link-new-rpms-here"
    try:
        process = subprocess.run(
            make_cmd,
            check=True,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as err:
        print_fatal(f"Error: {make_cmd}: {err}")
        sys.exit(1)


def str_to_bool(s):
    """Create helper function to convert srt to true Bool."""
    if s == "True" or s == "true" or s == 1 or s == "1":
        return True
    elif s == "False" or s == "false" or s == 0 or s == "0":
        return False
    elif s == "":
        return None
    elif s is None:
        return None
    else:
        raise ValueError


def check_requirements(use_git):
    """Ensure all requirements are satisfied before continuing."""
    required_bins = [
        "mock",
        "rpm2cpio",
        "nm",
        "objdump",
        "cpio",
        "readelf",
        "zip",
    ]

    if use_git:
        required_bins.append("git")

    missing = [x for x in required_bins if not binary_in_path(x)]

    if missing:
        print_fatal("Required programs are not installed: {}".format(", ".join(missing)))
        sys.exit(1)


def load_specfile(conf, specfile):
    """Gather all information from static analysis into Specfile instance."""
    specdescription.load_specfile(specfile, conf.custom_desc, conf.custom_summ)
    license.load_specfile(specfile)
    check.load_specfile(specfile)


def read_old_metadata():
    """Handle options.conf providing package, url and archives."""
    if not os.path.exists(os.path.join(os.getcwd(), "options.conf")):
        return None, None, None, None, None, [], []

    config_f = configparser.ConfigParser(interpolation=None)
    config_f.read("options.conf")
    if "package" not in config_f.sections():
        return None, None, None, None, None, [], []

    archives = config_f["package"].get("archives")
    archives = archives.split() if archives else []

    archives_from_git = config_f["package"].get("archives_from_git")
    archives_from_git = archives_from_git.split() if archives_from_git else []
    if util.debugging:
        print_debug(f"\nARCHIVES {archives}")
        print_debug(f"ARCHIVES_GIT 1: {archives_from_git}")

    return (
        config_f["package"].get("name"),
        config_f["package"].get("url"),
        config_f["package"].get("download_from_git"),
        config_f["package"].get("branch"),
        config_f["package"].get("force_module"),
        config_f["package"].get("force_fullclone"),
        archives,
        archives_from_git,
    )


def save_mock_logs(path, iteration):
    """Save Mock build logs to <path>/results/round<iteration>-*.log."""
    basedir = os.path.join(path, "results")
    loglist = [
        "build",
        "root",
        "srpm-build",
        "srpm-root",
        "mock_srpm",
        "mock_build",
    ]
    for log in loglist:
        src = "{}/{}.log".format(basedir, log)
        dest = "{}/round{}-{}.log".format(basedir, iteration, log)
        os.rename(src, dest)


def write_prep(conf, workingdir, content):
    """Write metadata to the local workingdir when --prep-only is used."""
    if conf.urlban:
        used_url = re.sub(conf.urlban, "localhost", content.url)
    else:
        used_url = content.url

    print()
    print("Exiting after prep due to --prep-only flag")
    print()
    print("Results under ./workingdir")
    print("Source  (./workingdir/{})".format(content.tarball_prefix))
    print("Name    (./workingdir/name)    :", content.name)
    print("Version (./workingdir/version) :", content.version)
    print("URL     (./workingdir/source0) :", used_url)
    write_out(os.path.join(workingdir, "name"), content.name)
    write_out(os.path.join(workingdir, "version"), content.version)
    write_out(os.path.join(workingdir, "source0"), used_url)


def main():
    """Entry point for autospec."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-g", "--skip-git", action="store_false", dest="git", default=True, help="Don't commit result to git",
    )
    parser.add_argument(
        "-n", "--name", action="store", dest="name", default="", help="Override the package name",
    )
    parser.add_argument(
        "-v", "--version", action="store", dest="version", default="", help="Override the package version",
    )
    parser.add_argument(
        "url", default="", nargs="?", help="tarball URL (e.g." " http://example.com/downloads/mytar.tar.gz)",
    )
    parser.add_argument(
        "-a",
        "--archives",
        action="store",
        dest="archives",
        default=[],
        nargs="*",
        help="tarball URLs for additional source archives and "
        " a location for the sources to be extacted to (e.g. "
        " http://example.com/downloads/dependency.tar.gz "
        " /directory/relative/to/extract/root )",
    )
    parser.add_argument(
        "-l", "--license-only", action="store_true", dest="license_only", default=False, help="Only scan for license files",
    )
    parser.add_argument(
        "-b", "--skip-bump", dest="bump", action="store_false", default=True, help="Don't bump release number",
    )
    parser.add_argument(
        "-c", "--config", dest="config", action="store", default="/usr/share/defaults/autospec/autospec.conf", help="Set configuration file to use",
    )
    parser.add_argument(
        "-t", "--target", dest="target", action="store", required=True, help="Target location to create or reuse",
    )
    parser.add_argument(
        "-i", "--integrity", action="store_true", default=False, help="Search for package signature from source URL and " "attempt to verify package",
    )
    parser.add_argument(
        "-p", "--prep-only", action="store_true", default=False, help="Only perform preparatory work on package",
    )
    parser.add_argument(
        "--non_interactive", action="store_true", default=False, help="Disable interactive mode for package verification",
    )
    parser.add_argument(
        "-C", "--cleanup", dest="cleanup", action="store_true", default=False, help="Clean up mock chroot after building the package",
    )
    parser.add_argument(
        "-m", "--mock-config", action="store", default="clear", help="Value to pass with Mock's -r option. Defaults to " '"clear", meaning that Mock will use ' "/etc/mock/clear.cfg.",
    )
    parser.add_argument(
        "-o", "--mock-opts", action="store", default="", help="Arbitrary options to pass down to mock when " "building a package.",
    )
    parser.add_argument(
        "-dg", "--download_from_git", action="store", dest="download_from_git", default=None, help="Download source from git",
    )
    parser.add_argument(
        "-rdg", "--redownload_from_git", action="store_true", dest="redownload_from_git", default=False, help="Redownload source from git",
    )
    parser.add_argument(
        "-fb", "--from_branch", action="store", dest="branch", default=None, help="Define the git branch to download the source from",
    )
    parser.add_argument(
        "-ag",
        "--archives_from_git",
        action="store",
        dest="archives_from_git",
        default=[],
        nargs="*",
        help="git URL for additional archives, the location for"
        " the sources to be extracted to and the branch to download"
        " from, with master as the default (e.g."
        " http://example.com/downloads/dependency.tar.gz"
        " /directory/relative/to/extract/root master "
        " Disable download submodule from git [BOOLEAN] "
        " Force full clone from git [BOOLEAN] )",
    )
    parser.add_argument(
        "-rag", "--redownload_archive", action="store_true", dest="redownload_archive", default=False, help="Redownload archives",
    )
    parser.add_argument(
        "-dsub", "--disable_submodule", action="store", dest="force_module", default=None, help="Disable download submodules from git",
    )
    parser.add_argument(
        "-ffc", "--force_fullclone", action="store", dest="force_fullclone", default=None, help="Force full clone from git",
    )
    parser.add_argument(
        "-dfr", "--do_file_restart", action="store_false", dest="do_file_restart", default=True, help="Disable file_restart mechanism",
    )
    parser.add_argument(
        "-dbg", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging",
    )

    args = parser.parse_args()

    a_name, a_url, a_download_from_git, a_branch, a_force_module, a_force_fullclone, a_archives, a_archives_from_git = read_old_metadata()
    name = args.name or a_name
    url = args.url or a_url
    archives = args.archives or a_archives
    archives_from_git = args.archives_from_git or a_archives_from_git
    util.debugging = args.debug
    args.integrity = False
    if os.path.exists(f"{name}.license") == False:
        write_out(f"{name}.license", "GPL-2.0\n")
        print(f"Created default mock license file")

    mock_dir_pattern = re.compile(r"(?:\-\-config-opts=basedir=)([a-zA-Z0-9\.\_\+\-\/]*)")
    short_circuit_pattern = re.compile(r"(?:\-\-short-circuit=)([a-zA-Z-]+)")
    if util.debugging:
        print_debug(f"args.mock_config: {args.mock_config}")
        print_debug(f"args.mock_opts: {args.mock_opts}")
    mock_dir = ""
    short_circuit = ""
    mock_dir_match = mock_dir_pattern.search(args.mock_opts)
    if (mock_dir_match):
        mock_dir = mock_dir_match.group(1)
        if util.debugging:
            print_debug(f"mock_dir: {mock_dir}")
    else:
        mock_dir = "/var/lib/mock"
        if util.debugging:
            print_debug(f"mock_dir: {mock_dir}")
    short_circuit_match = short_circuit_pattern.search(args.mock_opts)
    if (short_circuit_match):
        short_circuit = short_circuit_match.group(1)
        print_info(f"short_circuit: {short_circuit}")
    else:
        short_circuit = None

    if short_circuit == "prep" or short_circuit is None:
        args.bump = True
    else:
        args.bump = False

    if util.debugging:
        print_debug("a_download_from_git: {}".format(str(str_to_bool(a_download_from_git))))
    if args.download_from_git is not None:
        download_from_git = str_to_bool(args.download_from_git)
        if util.debugging:
            print_debug("args.download_from_git: {}".format(str(str_to_bool(args.download_from_git))))
            print_debug("download_from_git: {}".format(str(download_from_git)))
    else:
        download_from_git = str_to_bool(a_download_from_git)
        if util.debugging:
            print_debug("args.download_from_git: {}".format(str(str_to_bool(args.download_from_git))))
            print_debug("download_from_git: {}".format(str(download_from_git)))

    if util.debugging:
        print_debug("a_force_module: {}".format(str(str_to_bool(a_force_module))))
    if args.force_module is not None:
        force_module = str_to_bool(args.force_module)
        if util.debugging:
            print_debug("args.force_module: {}".format(str(str_to_bool(args.force_module))))
            print_debug("force_module: {}".format(str(force_module)))
    else:
        force_module = str_to_bool(a_force_module)
        if util.debugging:
            print_debug("args.force_module: {}".format(str(str_to_bool(args.force_module))))
            print_debug("force_module: {}".format(str(force_module)))

    if util.debugging:
        print_debug("a_force_fullclone: {}".format(str(str_to_bool(a_force_fullclone))))
    if args.force_fullclone is not None:
        force_fullclone = str_to_bool(args.force_fullclone)
        if util.debugging:
            print_debug("args.force_fullclone: {}".format(str(str_to_bool(args.force_fullclone))))
            print_debug("force_fullclone: {}".format(str(force_fullclone)))
    else:
        force_fullclone = str_to_bool(a_force_fullclone)
        if util.debugging:
            print_debug("args.force_fullclone: {}".format(str(str_to_bool(args.force_fullclone))))
            print_debug("force_fullclone: {}".format(str(force_fullclone)))

    do_file_restart = args.do_file_restart

    redownload_from_git = args.redownload_from_git
    redownload_archive = args.redownload_archive

    if download_from_git:
        if util.debugging:
            print_debug("a_branch: {}".format(str(a_branch)))
        if args.branch is None and a_branch:
            branch = str(a_branch)
            if util.debugging:
                print_debug("args.branch: {}".format(str(args.branch)))
                print_debug("branch: {}".format(str(branch)))
        elif args.branch is None and not a_branch:
            branch = str("master")
            if util.debugging:
                print_debug("args.branch: {}".format(str(args.branch)))
                print_debug("branch: {}".format(str(branch)))
        elif args.branch is not None:
            branch = str(args.branch)
            if util.debugging:
                print_debug("args.branch: {}".format(str(args.branch)))
                print_debug("branch: {}".format(str(branch)))
    else:
        branch = None

    if util.debugging:
        print_debug("args.url: {}".format(args.url))
        print_debug("url: {}".format(url))
        print_debug("redownload_from_git: {}".format(str(redownload_from_git)))
        print_debug("redownload_archive: {}".format(str(redownload_archive)))

    if archives:
        if util.debugging:
            print_debug("a_archives: {}".format(list(a_archives)))
        if args.archives is None and a_archives:
            archives = list(a_archives)
            if util.debugging:
                print_debug("args.archives 1: {}".format(list(args.archives)))
                print_debug("archives 1: {}".format(list(archives)))
        elif args.archives is None and not a_archives:
            archives = None
            if util.debugging:
                print_debug("args.archives 2: {}".format(list(args.archives)))
                print_debug("archives 2: {}".format(list(archives)))
        elif args.archives is not None:
            archives = list(args.archives)
            if util.debugging:
                print_debug("args.archives 3: {}".format(str(args.archives)))
                print_debug("archives 3: {}".format(str(archives)))
    else:
        archives = []

    if archives_from_git:
        if util.debugging:
            print_debug("a_archives_from_git: {}".format(list(a_archives_from_git)))
        if args.archives_from_git is None and a_archives_from_git:
            archives_from_git = list(a_archives_from_git)
            if util.debugging:
                print_debug("args.archives_from_git 1: {}".format(list(args.archives_from_git)))
                print_debug("archives_from_git 1: {}".format(list(archives_from_git)))
        elif args.archives_from_git is None and not a_archives_from_git:
            archives_from_git = None
            if util.debugging:
                print_debug("args.archives_from_git 2: {}".format(list(args.archives_from_git)))
                print_debug("archives_from_git 2: {}".format(list(archives_from_git)))
        elif args.archives_from_git is not None:
            archives_from_git = list(args.archives_from_git)
            if util.debugging:
                print_debug("args.archives_from_git 3: {}".format(str(args.archives_from_git)))
                print_debug("archives_from_git 3: {}".format(str(archives_from_git)))
    else:
        archives_from_git = []

    if not args.target:
        parser.error(argparse.ArgumentTypeError("The target option is not valid"))
    else:
        # target path must exist or be created
        os.makedirs(args.target, exist_ok=True)

    if not url:
        parser.error(argparse.ArgumentTypeError("the url argument or options.conf['package']['url'] is required"))

    if archives:
        if len(archives) % 2 != 0:
            parser.error(argparse.ArgumentTypeError("-a/--archives or options.conf['package']['archives'] requires an " "even number of arguments"))

    if archives_from_git:
        if len(archives_from_git) % 3 != 0 and len(archives_from_git) % 5 != 0:
            parser.error(argparse.ArgumentTypeError("-ag/--archives_from_git or options.conf['package']['archives_from_git'] requires " "3 or 5 arguments"))

    if args.prep_only:
        os.makedirs("workingdir", exists_ok=True)
        package(
            args, url, name, archives, archives_from_git, "./workingdir", download_from_git, branch, redownload_from_git, redownload_archive, force_module, force_fullclone, mock_dir, short_circuit, do_file_restart,
        )
    else:
        with tempfile.TemporaryDirectory() as workingdir:
            package(
                args, url, name, archives, archives_from_git, workingdir, download_from_git, branch, redownload_from_git, redownload_archive, force_module, force_fullclone, mock_dir, short_circuit, do_file_restart,
            )


def package(
    args, url, name, archives, archives_from_git, workingdir, download_from_git, branch, redownload_from_git, redownload_archive, force_module, force_fullclone, mock_dir, short_circuit, do_file_restart,
):
    """Entry point for building a package with autospec."""
    conf = config.Config(args.target)
    conf.parse_config_files_early()

    if util.debugging:
        print_debug(f"url 1: {url}")
    new_archives_from_git = []
    name_re_escaped = re.escape(name)
    # Download the source from git if necessary
    if download_from_git:
        giturl = url
        found_file = False
        fileslist = None
        download_file_full_path = ""
        if util.debugging:
            print_debug(f"url 2: {url}")
            print_debug(f"BRANCH 2: {branch}")
        # filename_re = re.compile(r"^{}{}".format(name, r"(-|-.)(\d+)(\.\d+)+\.tar\.gz"))
        filename_re = re.compile(r"^{}{}".format(name_re_escaped, r"-.*\.tar\.gz"))
        if os.path.basename(os.getcwd()) == name:
            package_path = "./"
            if util.debugging:
                print_debug(f"package_path 11: {package_path}")
            fileslist = os.listdir(package_path)
            fileslist.sort(key=os.path.getmtime)
            for filename in fileslist:
                if re.search(filename_re, filename):
                    found_file = True
                    download_file_full_path = "file://{}".format(os.path.abspath(f"{package_path}{filename}"))
                    if util.debugging:
                        print_debug(f"found old package_path 21: {download_file_full_path}")
                    break
            if not found_file or redownload_from_git is True:
                download_file_full_path = git.git_archive_all(path=package_path, name=name, url=url, branch=branch, force_module=force_module, force_fullclone=force_fullclone, conf=conf)
            url = download_file_full_path
            if util.debugging:
                print_debug(f"download_file_full_path 11: {download_file_full_path}")
                print_debug(f"giturl 11: {giturl}")
        else:
            package_path = f"packages/{name}"
            if util.debugging:
                print_debug(f"package_path 12: {package_path}")
            fileslist = os.listdir(package_path)
            fileslist.sort(key=os.path.getmtime)
            for filename in fileslist:
                if re.search(filename_re, filename):
                    found_file = True
                    download_file_full_path = "file://{}".format(os.path.abspath(f"{package_path}{filename}"))
                    if util.debugging:
                        print_debug(f"found old package_path 22: {download_file_full_path}")
                    break
            if not found_file or redownload_from_git is True:
                download_file_full_path = git.git_archive_all(path=package_path, name=name, url=url, branch=branch, force_module=force_module, force_fullclone=force_fullclone, conf=conf)
            url = download_file_full_path
            if util.debugging:
                print_debug(f"download_file_full_path 12: {download_file_full_path}")
                print_debug(f"giturl 12: {giturl}")
    else:
        giturl = ""
        url = download.do_curl_get_effective_url(url)

    if archives_from_git:
        arch_url = []
        arch_destination = []
        arch_branch = []
        arch_submodule = []
        arch_forcefullclone = []
        if util.debugging:
            print_debug(f"ARCHIVES_GIT 2: {archives_from_git}")
            print_debug(f"archives in options.conf: {archives}\n\n")
        archives_re = re.compile(r"^file:\/\/")
        index_f = []

        for index, url_entry in enumerate(archives):
            if archives_re.search(url_entry):
                index_f.append(index)
        if util.debugging:
            for x in range(len(index_f) - 1, -1, -1):
                print_debug(f"rm {index_f[x]}:{archives[index_f[x]]} {index_f[x] + 1}:{archives[index_f[x] + 1]}")
        for x in sorted(range(len(index_f) - 1, -1, -1), reverse=True):
            del archives[index_f[x] : index_f[x] + 2]

        if util.debugging:
            print_debug(f"archives in options.conf: {archives}")

        for aurl, dest, br, sm, ffc in zip(archives_from_git[::5], archives_from_git[1::5], archives_from_git[2::5], archives_from_git[3::5], archives_from_git[4::5]):
            arch_url.append(aurl)
            arch_destination.append(dest)
            arch_branch.append(br)
            arch_submodule.append(sm)
            arch_forcefullclone.append(ffc)
            if util.debugging:
                print_debug(f"FOR ZIP {arch_url[-1]} - {arch_destination[-1]} - {arch_branch[-1]} - {arch_submodule[-1]} - {arch_forcefullclone[-1]}")
        for index, new_arch_url in enumerate(arch_url, start=0):
            found_file = False
            fileslist = []
            download_file_full_path = ""
            arch_name = os.path.splitext(os.path.basename(new_arch_url))[0]
            arch_name_re_escaped = re.escape(arch_name)
            filename_re = re.compile(r"^{}{}".format(arch_name_re_escaped, r"-.*\.tar\.gz"))
            if util.debugging:
                print_debug(f"arch_name: {arch_name}")
            if os.path.basename(os.getcwd()) == name:
                package_path = "./"
                if util.debugging:
                    print_debug(f"archive package_path 1: {package_path}")
                for filename in os.scandir(package_path):
                    if filename.is_file():
                        if filename_re.search(filename.name):
                            found_file = True
                            download_file_full_path = "file://{}".format(os.path.abspath(f"{package_path}{filename.name}"))
                            if util.debugging:
                                print_debug(f"filename: {filename.name}")
                                print_debug(f"Index: {index}")
                                print_debug(f"Destination: {arch_destination[index]} - Branch: {arch_branch[index]}")
                                print_debug(f"archive found 1: {arch_name} - {download_file_full_path}")
                            break
                if not found_file or redownload_archive is True:
                    if util.debugging:
                        print_debug(f"Index: {index}")
                        print_debug(f"Destination: {arch_destination[index]} - Branch: {arch_branch[index]}")
                        print_debug(f"Fazer download archive 1: {arch_name} - {new_arch_url}")
                    download_file_full_path = git.git_archive_all(path=package_path, name=arch_name, url=new_arch_url, branch=arch_branch[index], force_module=str_to_bool(arch_submodule[index]), force_fullclone=str_to_bool(arch_forcefullclone[index]), conf=conf)
                if util.debugging:
                    print_debug(f"archive download_file_full_path 1: {download_file_full_path}")
                if download_file_full_path in archives or arch_destination[index] in archives:
                    print_info(f"\nAlready in archives: {archives}")
                else:
                    archives.append(download_file_full_path)
                    archives.append(arch_destination[index])
                    print_info(f"\nAdding to archives: {archives}")
                new_archives_from_git.append(arch_url[index])
                new_archives_from_git.append(arch_destination[index])
                new_archives_from_git.append(arch_branch[index])
                new_archives_from_git.append(arch_submodule[index])
                new_archives_from_git.append(arch_forcefullclone[index])
            else:
                package_path = f"packages/{name}"
                if util.debugging:
                    print_debug(f"archive package_path 2: {package_path}")
                for filename in os.scandir(package_path):
                    if filename.is_file():
                        if filename_re.search(filename.name):
                            found_file = True
                            download_file_full_path = "file://{}".format(os.path.abspath(f"{package_path}{filename.name}"))
                            if util.debugging:
                                print_debug(f"Index: {index}")
                                print_debug(f"Destination: {arch_destination[index]} - Branch: {arch_branch[index]}")
                                print_debug(f"archive found 2: {arch_name} - {download_file_full_path}")
                            break
                if not found_file or redownload_archive is True:
                    if util.debugging:
                        print_debug(f"Index: {index}")
                        print_debug(f"Destination: {arch_destination[index]} - Branch: {arch_branch[index]}")
                        print_debug(f"Fazer download archive 2: {arch_name} - {new_arch_url}")
                    download_file_full_path = git.git_archive_all(path=package_path, name=arch_name, url=new_arch_url, branch=arch_branch[index], force_module=str_to_bool(arch_submodule[index]), force_fullclone=str_to_bool(arch_forcefullclone[index]), conf=conf)
                if util.debugging:
                    print_debug(f"archive download_file_full_path 2: {download_file_full_path}")
                if download_file_full_path in archives or arch_destination[index] in archives:
                    print_info(f"\nAlready in archives: {archives}")
                else:
                    archives.append(download_file_full_path)
                    archives.append(arch_destination[index])
                    print_info(f"\nAdding to archives: {archives}")
                new_archives_from_git.append(arch_url[index])
                new_archives_from_git.append(arch_destination[index])
                new_archives_from_git.append(arch_branch[index])
                new_archives_from_git.append(arch_submodule[index])
                new_archives_from_git.append(arch_forcefullclone[index])
        if util.debugging:
            print_debug(f"new_archives_from_git: {new_archives_from_git}\n")

    #check_requirements(args.git)
    conf.detect_build_from_url(url)
    package = build.Build()

    #
    # First, download the tarball, extract it and then do a set
    # of static analysis on the content of the tarball.
    #
    filemanager = files.FileManager(conf, package, mock_dir, short_circuit)
    if util.debugging:
        print_debug(f"url 4: {url}")
        print_debug(f"archives 4: {archives}")
        print_debug(f"new_archives_from_git 4: {new_archives_from_git}")
    content = tarball.Content(url, name, args.version, archives, conf, workingdir, giturl, download_from_git, branch, new_archives_from_git, force_module, force_fullclone)
    content.process(filemanager)
    conf.create_versions(content.multi_version)
    conf.content = content  # hack to avoid recursive dependency on init
    # Search up one level from here to capture multiple versions
    _dir = content.path

    conf.setup_patterns()
    conf.config_file = args.config
    requirements = buildreq.Requirements(content.url)
    requirements.set_build_req(conf)
    conf.parse_config_files(args.bump, filemanager, content.version, requirements)
    conf.setup_patterns(conf.failed_pattern_dir)
    conf.parse_existing_spec(content.name)

    if args.prep_only:
        write_prep(conf, workingdir, content)
        exit(0)

    if args.license_only:
        try:
            with open(os.path.join(conf.download_path, content.name + ".license"), "r",) as dotlic:
                for word in dotlic.read().split():
                    if ":" not in word:
                        license.add_license(word)
        except Exception:
            pass
        # Start one directory higher so we scan *all* versions for licenses
        license.scan_for_licenses(os.path.dirname(_dir), conf, name)
        exit(0)

    if short_circuit == "prep" or short_circuit is None:
        requirements.scan_for_configure(_dir, content.name, conf)
        #specdescription.scan_for_description(content.name, _dir, conf.license_translations, conf.license_blacklist)
        # Start one directory higher so we scan *all* versions for licenses
        license.scan_for_licenses(os.path.dirname(_dir), conf, content.name)
        #commitmessage.scan_for_changes(conf.download_path, _dir, conf.transforms)
        conf.add_sources(archives, content)
        #check.scan_for_tests(_dir, conf, requirements, content)

    #
    # Now, we have enough to write out a specfile, and try to build it.
    # We will then analyze the build result and learn information until the
    # package builds
    #
    specfile = specfiles.Specfile(content.url, content.version, content.name, content.release, conf, requirements, content, mock_dir, short_circuit)
    filemanager.load_specfile(specfile)
    load_specfile(conf, specfile)

    if args.integrity:
        interactive_mode = not args.non_interactive
        pkg_integrity.check(url, conf, interactive=interactive_mode)
        pkg_integrity.load_specfile(specfile)

    specfile.write_spec()
    filemanager.load_specfile_information(specfile, content)
    if short_circuit == "prep":
        util.call(f"sudo rm -rf {mock_dir}/clear-{content.name}/root/builddir/build/SRPMS/")
        util.call(f"sudo rm -rf {mock_dir}/clear-{content.name}/root/builddir/build/BUILD/")
    if short_circuit == "install":
        util.call(f"sudo rm -rf {mock_dir}/clear-{content.name}/root/builddir/build/RPMS/")
    while 1:
        package.package(
            filemanager, args.mock_config, args.mock_opts, conf, requirements, content,mock_dir, short_circuit, do_file_restart, args.cleanup,
        )
        if (short_circuit != package.short_circuit):
            print_info(f"short_circuit: {short_circuit}")
            print_info(f"package.short_circuit: {package.short_circuit}")
            short_circuit = package.short_circuit
            print_info(f"new short_circuit: {short_circuit}")

        filemanager.load_specfile_information(specfile, content)
        filemanager.load_specfile(specfile)
        specfile.write_spec()
        filemanager.newfiles_printed = 0

        mock_chroot = f"{mock_dir}/clear-{package.uniqueext}/root/builddir/build/BUILDROOT/{content.name}-{content.version}-{content.release}.x86_64"
        if filemanager.clean_directories(mock_chroot):
            # directories added to the blacklist, need to re-run
            package.must_restart += 1
            print_info(f"filemanager.clean_directories({mock_chroot})")

        if do_file_restart:
            if package.round > 20 or (package.must_restart == 0 and package.file_restart == 0):
                if (short_circuit == "install"):
                    print_info(f"short_circuit: {short_circuit}")
                    print_info(f"package.short_circuit: {package.short_circuit}")
                    short_circuit = "binary"
                    print_info(f"new short_circuit: {short_circuit}")
                    continue
                else:
                    break
        else:
            if (package.round > 20 or package.must_restart == 0):
                break

        save_mock_logs(conf.download_path, package.round)

    #if short_circuit is None or short_circuit == "install":
        #check.check_regression(conf.download_path, conf.config_opts["skip_tests"])

    if package.success == 0:
        conf.create_buildreq_cache(content.version, requirements.buildreqs_cache)
        #conf.create_reqs_cache(content.version, requirements.reqs_cache)
        print_fatal("Build failed, aborting")
        sys.exit(1)
    elif (package.success == 1):
        if os.path.isfile("README.clear"):
            try:
                print("\nREADME.clear CONTENTS")
                print("*********************")
                with open("README.clear", "r") as readme_f:
                    print(readme_f.read())

                print("*********************\n")
            except Exception:
                pass

        if (short_circuit is None):
            examine_abi(conf.download_path, content.name)
            #if os.path.exists("/var/lib/rpm"):
                #print("\nGenerating whatrequires\n")
                #pkg_scan.get_whatrequires(content.name, conf.yum_conf)

            write_out(conf.download_path + "/release", content.release + "\n")

            # record logcheck output
            #logcheck(conf.download_path)

            #if args.git:
                #print("\nTrying to guess the commit message\n")
                #commitmessage.guess_commit_message(pkg_integrity.IMPORTED, conf, content)
                #git.commit_to_git(conf, content.name, package.success)

            conf.create_buildreq_cache(content.version, requirements.buildreqs_cache)
            #conf.create_reqs_cache(content.version, requirements.reqs_cache)

        elif (short_circuit == "prep"):
            write_out(conf.download_path + "/release", content.release + "\n")

        #elif (short_circuit == "build"):
            # record logcheck output
            #logcheck(conf.download_path)

        #elif (short_circuit == "install"):
            ## record logcheck output
            #logcheck(conf.download_path)

        elif (short_circuit == "binary"):
            examine_abi(conf.download_path, content.name)
            #if os.path.exists("/var/lib/rpm"):
                #print("\nGenerating whatrequires\n")
                #pkg_scan.get_whatrequires(content.name, conf.yum_conf)

            #write_out(conf.download_path + "/release", content.release + "\n")

            #if args.git:
                #print("\nTrying to guess the commit message\n")
                #commitmessage.guess_commit_message(pkg_integrity.IMPORTED, conf, content)
                #git.commit_to_git(conf, content.name, package.success)
            #else:
                #print("To commit your changes, git add the relevant files and run 'git commit -F commitmsg'")

            conf.create_buildreq_cache(content.version, requirements.buildreqs_cache)
            #conf.create_reqs_cache(content.version, requirements.reqs_cache)

            link_new_rpms_here()


if __name__ == "__main__":
    main()
