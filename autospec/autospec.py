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
from util import binary_in_path, print_fatal, write_out

sys.path.append(os.path.dirname(__file__))


def check_requirements(use_git):
    """Ensure all requirements are satisfied before continuing."""
    required_bins = ["mock", "rpm2cpio", "nm", "objdump", "cpio", "readelf", "zip"]

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
    if not os.path.exists(os.path.join(os.getcwd(), 'options.conf')):
        return None, None, None, None, None, [], []

    config_f = configparser.ConfigParser(interpolation=None)
    config_f.read('options.conf')
    if "package" not in config_f.sections():
        return None, None, None, None, None, [], []

    archives = config_f["package"].get("archives")
    archives = archives.split() if archives else []
    print("ARCHIVES {}".format(archives))
    archives_from_git = config_f["package"].get("archives_from_git")
    archives_from_git = archives_from_git.split() if archives_from_git else []
    print("ARCHIVES_GIT 1: {}".format(archives_from_git))

    return (config_f["package"].get("name"),
            config_f["package"].get("url"),
            config_f["package"].get("download_from_git"),
            config_f["package"].get("branch"),
            config_f["package"].get("force_module"),
            archives,
            archives_from_git)


def save_mock_logs(path, iteration):
    """Save Mock build logs to <path>/results/round<iteration>-*.log."""
    basedir = os.path.join(path, "results")
    loglist = ["build", "root", "srpm-build", "srpm-root", "mock_srpm", "mock_build"]
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
    parser.add_argument("-g", "--skip-git",
                        action="store_false", dest="git", default=True,
                        help="Don't commit result to git")
    parser.add_argument("-n", "--name", action="store", dest="name", default="",
                        help="Override the package name")
    parser.add_argument("-v", "--version", action="store", dest="version", default="",
                        help="Override the package version")
    parser.add_argument("url", default="", nargs="?",
                        help="tarball URL (e.g."
                             " http://example.com/downloads/mytar.tar.gz)")
    parser.add_argument('-a', "--archives", action="store",
                        dest="archives", default=[], nargs='*',
                        help="tarball URLs for additional source archives and"
                        " a location for the sources to be extacted to (e.g."
                        " http://example.com/downloads/dependency.tar.gz"
                        " /directory/relative/to/extract/root )")
    parser.add_argument("-l", "--license-only",
                        action="store_true", dest="license_only",
                        default=False, help="Only scan for license files")
    parser.add_argument("-b", "--skip-bump", dest="bump",
                        action="store_false", default=True,
                        help="Don't bump release number")
    parser.add_argument("-c", "--config", dest="config", action="store",
                        default="/usr/share/defaults/autospec/autospec.conf",
                        help="Set configuration file to use")
    parser.add_argument("-t", "--target", dest="target", action="store",
                        required=True,
                        help="Target location to create or reuse")
    parser.add_argument("-i", "--integrity", action="store_true",
                        default=False,
                        help="Search for package signature from source URL and "
                             "attempt to verify package")
    parser.add_argument("-p", "--prep-only", action="store_true",
                        default=False,
                        help="Only perform preparatory work on package")
    parser.add_argument("--non_interactive", action="store_true",
                        default=False,
                        help="Disable interactive mode for package verification")
    parser.add_argument("-C", "--cleanup", dest="cleanup", action="store_true",
                        default=False,
                        help="Clean up mock chroot after building the package")
    parser.add_argument("-m", "--mock-config", action="store", default="clear",
                        help="Value to pass with Mock's -r option. Defaults to "
                             "\"clear\", meaning that Mock will use "
                             "/etc/mock/clear.cfg.")
    parser.add_argument("-o", "--mock-opts", action="store", default="",
                        help="Arbitrary options to pass down to mock when "
                        "building a package.")
    parser.add_argument("-dg", "--download_from_git", action="store_true", dest="download_from_git", default=False,
                        help="Download source from git")
    parser.add_argument("-rdg", "--redownload_from_git", action="store_true", dest="redownload_from_git", default=False,
                        help="Redownload source from git")
    parser.add_argument("-fb", "--from_branch", action="store", dest="branch", default="master",
                        help="Define the git branch to download the source from")
    parser.add_argument('-ag', "--archives_from_git", action="store",
                        dest="archives_from_git", default=[], nargs='*',
                        help="git URL for additional archives, the location for"
                        " the sources to be extacted to and the branch to download"
                        " from, with master as the default (e.g."
                        " http://example.com/downloads/dependency.tar.gz"
                        " /directory/relative/to/extract/root master )")
    parser.add_argument("-rag", "--redownload_archive", action="store_true", dest="redownload_archive", default=False,
                        help="Redownload archives")
    parser.add_argument("-dsub", "--disable_submodule", action="store_true", dest="force_module", default=False,
                        help="Disable download submodules from git")

    args = parser.parse_args()

    name, url, download_from_git, branch, force_module, archives, archives_from_git = read_old_metadata()
    name = args.name or name
    url = args.url or url
    force_module = force_module or args.force_module
    archives = args.archives or archives
    archives_from_git = args.archives_from_git or archives_from_git

    redownload_from_git = args.redownload_from_git
    redownload_archive = args.redownload_archive

    if args.download_from_git:
        download_from_git = True
        if not args.branch:
            branch = "master"
        else:
            branch = args.branch

    print('Teste args.download_from_git: {}'.format(args.download_from_git))
    print('Teste download_from_git: {}'.format(download_from_git))
    print('Teste args.branch: {}'.format(args.branch))
    print('Teste branch: {}'.format(branch))
    print('Teste args.url: {}'.format(args.url))
    print('Teste url: {}'.format(url))
    print('Teste force_module: {}'.format(force_module))
    print('Teste args.force_module: {}'.format(args.force_module))
    print('Teste redownload_from_git: {}'.format(redownload_from_git))
    print('Teste args.archives: {}'.format(args.archives))
    print('Teste archives: {}'.format(archives))
    print('Teste args.archives_from_git: {}'.format(args.archives_from_git))
    print('Teste archives_from_git: {}'.format(archives_from_git))
    print('Teste redownload_archive: {}'.format(redownload_archive))


    if not args.target:
        parser.error(argparse.ArgumentTypeError(
            "The target option is not valid"))
    else:
        # target path must exist or be created
        os.makedirs(args.target, exist_ok=True)

    if not url:
        parser.error(argparse.ArgumentTypeError(
            "the url argument or options.conf['package']['url'] is required"))

    if len(archives) % 2 != 0:
        parser.error(argparse.ArgumentTypeError(
            "-a/--archives or options.conf['package']['archives'] requires an "
            "even number of arguments"))

    if len(archives_from_git) % 3 != 0:
        parser.error(argparse.ArgumentTypeError(
            "-ag/--archives_from_git or options.conf['package']['archives_from_git'] requires an "
            "uneven number of arguments"))

    print('Teste url 0: ' + url)

    if args.prep_only:
        os.makedirs("workingdir", exists_ok=True)
        package(args, url, name, archives, archives_from_git, "./workingdir", download_from_git, branch, redownload_from_git, redownload_archive, force_module)
    else:
        with tempfile.TemporaryDirectory() as workingdir:
            package(args, url, name, archives, archives_from_git, workingdir, download_from_git, branch, redownload_from_git, redownload_archive)


def package(args, url, name, archives, archives_from_git, workingdir, download_from_git=False, branch="", redownload_from_git=False, redownload_archive=False, force_module=False):
    """Entry point for building a package with autospec."""
    print('Teste url 1: ' + url)
    new_archives_from_git = []
    # Download the source from git if necessary
    if download_from_git:
        giturl = url
        found_file = False
        fileslist = None
        download_file_full_path = ""
        print('Teste url 2: ' + url)
        print('Teste BRANCH 2: ' + branch)
        filename_re = "^{}{}".format(name, r'(-|-.)(\d+)(\.\d+)+\.zip')
        if (os.path.basename(os.getcwd()) == name):
            package_path = './'
            print('Teste package_path 11: ' + package_path)
            fileslist = os.listdir(package_path)
            fileslist.sort(key=os.path.getmtime)
            for filename in fileslist:
                if re.search(filename_re, filename):
                    found_file = True
                    download_file_full_path = "file://{}".format(os.path.abspath(f'{package_path}{filename}'))
                    print('Teste found old package_path 21: ' + download_file_full_path)
            if not found_file or redownload_from_git:
                download_file_full_path = git.clone_and_git_archive_all(package_path, name, url, branch, force_module)
            print('Teste download_file_full_path 11: ' + download_file_full_path)
            url = download_file_full_path
            print('Teste giturl 11: ' + giturl)
        else:
            package_path = f'packages/{name}'
            print('Teste package_path 12: ' + package_path)
            fileslist = os.listdir(package_path)
            fileslist.sort(key=os.path.getmtime)
            for filename in fileslist:
                if re.search(filename_re, filename):
                    found_file = True
                    download_file_full_path = "file://{}".format(os.path.abspath(f'{package_path}{filename}'))
                    print('Teste found old package_path 22: ' + download_file_full_path)
            if not found_file or redownload_from_git:
                download_file_full_path = git.clone_and_git_archive_all(package_path, name, url, branch, force_module)
            print('Teste download_file_full_path 12: ' + download_file_full_path)
            url = download_file_full_path
            print('Teste giturl 12: ' + giturl)
    else:
        giturl = ""

    if archives_from_git:
        arch_url = []
        arch_destination = []
        arch_branch = []
        print("\n\nARCHIVES_GIT 2: {}\n".format(archives_from_git))
        print("archives in options.conf: {}".format(archives))
        archives_re = r"^file:\/\/"
        for index, url_entry in enumerate(archives):
            if re.search(archives_re, url_entry):
                print("removing {}:{} {}:{}".format(index, archives[index], index + 1, archives[index + 1]))
                del archives[index:index + 2]
        print("archives in options.conf: {}".format(archives))
        for aurl, dest, br in zip(archives_from_git[::3], archives_from_git[1::3], archives_from_git[2::3]):
            arch_url.append(aurl)
            arch_destination.append(dest)
            arch_branch.append(br)
            print("\nFOR ZIP {} - {} - {}".format(arch_url[-1], arch_destination[-1], arch_branch[-1]))
        for index, new_arch_url in enumerate(arch_url, start=0):
            found_file = False
            fileslist = None
            download_file_full_path = ""
            arch_name = os.path.splitext(os.path.basename(new_arch_url))[0]
            filename_re = "^{}{}".format(arch_name, r'(-|-.)(\d+)(\.\d+)+\.zip')
            print("\n\narch_name: {}".format(arch_name))
            if (os.path.basename(os.getcwd()) == name):
                package_path = './'
                print('Teste archive package_path 1: ' + package_path)
                fileslist = os.listdir(package_path)
                fileslist.sort(key=os.path.getmtime)
                for filename in fileslist:
                    if re.search(filename_re, filename):
                        found_file = True
                        download_file_full_path = "file://{}".format(os.path.abspath(f'{package_path}{filename}'))
                        print("Index: {}".format(index))
                        print("Destination: {} - Branch: {}".format(arch_destination[index], arch_branch[index]))
                        print("Teste archive found 1: {} - {}".format(arch_name, download_file_full_path))
                if not found_file or redownload_from_git:
                    print("Index: {}".format(index))
                    print("Destination: {} - Branch: {}".format(arch_destination[index], arch_branch[index]))
                    print("Fazer download archive 1: {} - {}".format(arch_name, new_arch_url))
                    download_file_full_path = git.clone_and_git_archive_all(package_path, arch_name, new_arch_url, arch_branch[index], force_module)
                print('Teste archive download_file_full_path 1: ' + download_file_full_path)
                if download_file_full_path in archives or arch_destination[index] in archives:
                    print("\nalready in archives: {}".format(archives))
                else:
                    archives.append(download_file_full_path)
                    archives.append(arch_destination[index])
                    print("\nadding to archives: {}".format(archives))
                new_archives_from_git.append(arch_url[index])
                new_archives_from_git.append(arch_destination[index])
                new_archives_from_git.append(arch_branch[index])
            else:
                package_path = f'packages/{name}'
                print('Teste archive package_path 2: ' + package_path)
                fileslist = os.listdir(package_path)
                fileslist.sort(key=os.path.getmtime)
                for filename in fileslist:
                    if re.search(filename_re, filename):
                        found_file = True
                        download_file_full_path = "file://{}".format(os.path.abspath(f'{package_path}{filename}'))
                        print("Index: {}".format(index))
                        print("Destination: {} - Branch: {}".format(arch_destination[index], arch_branch[index]))
                        print("Teste archive found 2: {} - {}".format(arch_name, download_file_full_path))
                if not found_file or redownload_from_git:
                    print("Index: {}".format(index))
                    print("Destination: {} - Branch: {}".format(arch_destination[index], arch_branch[index]))
                    print("Fazer download archive 2: {} - {}".format(arch_name, new_arch_url))
                    download_file_full_path = git.clone_and_git_archive_all(package_path, arch_name, new_arch_url, arch_branch[index], force_module)
                print('Teste archive download_file_full_path 2: ' + download_file_full_path)
                if download_file_full_path in archives or arch_destination[index] in archives:
                    print("\nalready in archives: {}".format(archives))
                else:
                    archives.append(download_file_full_path)
                    archives.append(arch_destination[index])
                    print("\nadding to archives: {}".format(archives))
                new_archives_from_git.append(arch_url[index])
                new_archives_from_git.append(arch_destination[index])
                new_archives_from_git.append(arch_branch[index])
        print("new_archives_from_git: {}\n".format(new_archives_from_git))

    conf = config.Config(args.target)
    check_requirements(args.git)
    conf.detect_build_from_url(url)
    package = build.Build()

    #
    # First, download the tarball, extract it and then do a set
    # of static analysis on the content of the tarball.
    #
    filemanager = files.FileManager(conf, package)
    print('Teste url 4: ' + url)
    content = tarball.Content(url, name, args.version, archives, conf, workingdir, giturl, download_from_git, branch, new_archives_from_git, force_module)
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
            with open(os.path.join(conf.download_path,
                                   content.name + ".license"), "r") as dotlic:
                for word in dotlic.read().split():
                    if ":" not in word:
                        license.add_license(word)
        except Exception:
            pass
        # Start one directory higher so we scan *all* versions for licenses
        license.scan_for_licenses(os.path.dirname(_dir), conf, name)
        exit(0)

    requirements.scan_for_configure(_dir, content.name, conf)
    specdescription.scan_for_description(content.name, _dir, conf.license_translations, conf.license_blacklist)
    # Start one directory higher so we scan *all* versions for licenses
    license.scan_for_licenses(os.path.dirname(_dir), conf, content.name)
    commitmessage.scan_for_changes(conf.download_path, _dir, conf.transforms)
    conf.add_sources(archives, content)
    check.scan_for_tests(_dir, conf, requirements, content)

    #
    # Now, we have enough to write out a specfile, and try to build it.
    # We will then analyze the build result and learn information until the
    # package builds
    #
    specfile = specfiles.Specfile(content.url,
                                  content.version,
                                  content.name,
                                  content.release,
                                  conf,
                                  requirements,
                                  content)
    filemanager.load_specfile(specfile)
    load_specfile(conf, specfile)

    print("\n")

    if args.integrity:
        interactive_mode = not args.non_interactive
        pkg_integrity.check(url, conf, interactive=interactive_mode)
        pkg_integrity.load_specfile(specfile)

    specfile.write_spec()
    while 1:
        package.package(filemanager, args.mock_config, args.mock_opts, conf, requirements, content, args.cleanup)
        filemanager.load_specfile(specfile)
        specfile.write_spec()
        filemanager.newfiles_printed = 0
        mock_chroot = "/var/lib/mock/clear-{}/root/builddir/build/BUILDROOT/" \
                      "{}-{}-{}.x86_64".format(package.uniqueext,
                                               content.name,
                                               content.version,
                                               content.release)
        if filemanager.clean_directories(mock_chroot):
            # directories added to the blacklist, need to re-run
            package.must_restart += 1

        if package.round > 20 or package.must_restart == 0:
            break

        save_mock_logs(conf.download_path, package.round)

    check.check_regression(conf.download_path, conf.config_opts['skip_tests'])

    if package.success == 0:
        conf.create_buildreq_cache(content.version, requirements.buildreqs_cache)
        print_fatal("Build failed, aborting")
        sys.exit(1)
    elif os.path.isfile("README.clear"):
        try:
            print("\nREADME.clear CONTENTS")
            print("*********************")
            with open("README.clear", "r") as readme_f:
                print(readme_f.read())

            print("*********************\n")
        except Exception:
            pass

    examine_abi(conf.download_path, content.name)
    if os.path.exists("/var/lib/rpm"):
        pkg_scan.get_whatrequires(content.name, conf.yum_conf)

    write_out(conf.download_path + "/release", content.release + "\n")

    # record logcheck output
    logcheck(conf.download_path)

    commitmessage.guess_commit_message(pkg_integrity.IMPORTED, conf, content)
    conf.create_buildreq_cache(content.version, requirements.buildreqs_cache)

    if args.git:
        git.commit_to_git(conf, content.name, package.success)
    else:
        print("To commit your changes, git add the relevant files and "
              "run 'git commit -F commitmsg'")


if __name__ == '__main__':
    main()
