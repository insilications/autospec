#!/usr/bin/env python

import re
import sys
import os
import requests
import natsort
import subprocess

from operator import attrgetter, itemgetter
from bs4 import BeautifulSoup

def write_out(filename, content, mode="w"):
    """File.write convenience wrapper."""
    with open_auto(filename, mode) as require_f:
        require_f.write(content)

def open_auto(*args, **kwargs):
    """Open a file with UTF-8 encoding.

    Open file with UTF-8 encoding and "surrogate" escape characters that are
    not valid UTF-8 to avoid data corruption.
    """
    # 'encoding' and 'errors' are fourth and fifth positional arguments, so
    # restrict the args tuple to (file, mode, buffering) at most
    assert len(args) <= 3
    assert "encoding" not in kwargs
    assert "errors" not in kwargs
    return open(*args, encoding="utf-8", errors="surrogateescape", **kwargs)

def main():
    cwd = os.getcwd()
    filename = ""
    filename = [f.path for f in os.scandir(cwd) if f.is_file() and "insync-v" in f.name]

    if not filename:
        soup = BeautifulSoup(requests.get("https://forums.insynchq.com/c/releases/15").text, "html5lib")
        thread_list = soup.find_all("tr", attrs={"class": "topic-list-item"})

        thread_version_re = re.compile(r"(?:Insync version:\s|Insync version\s)((?:\d+)(?:[-._]*\d+)*)")
        thread_version_sort = []
        for thread in thread_list:
            thread_title = thread.find("a", attrs={"class": "title"})
            thread_version_match = thread_version_re.search(thread_title.text)
            if thread_version_match:
                thread_version_sort.append(list([f"{thread_version_match.group(1)}", f"{thread_title.get('href')}"]))

        if not thread_version_sort:
            print("Cant find thread")
            sys.exit(1)

        thread_version_sort = natsort.natsorted(thread_version_sort, key=itemgetter(0))

        #for thread in thread_version_sort:
            #print(thread)
        #print(f"Last: {thread_version_sort[-1][0]} - {thread_version_sort[-1][1]}")

        thread_version_html = BeautifulSoup(requests.get(thread_version_sort[-1][1]).text, "html5lib")
        thread_version_top_post = thread_version_html.find("div", attrs={"class": "topic-body"})
        thread_version_top_post_links = thread_version_top_post.find_all("a")

        get_url_fc_rpm_re = re.compile(r".*(?:-fc3\d{1}.x86_64.rpm)")
        get_urlfc_rpm_replace_re = re.compile(r"fc3\d")
        found_url = ""
        for link in thread_version_top_post_links:
            get_url_fc_rpm_match = get_url_fc_rpm_re.search(link.get('href'))
            if get_url_fc_rpm_match:
                #print(get_url_fc_rpm_match.group(0))
                found_url = re.sub(get_urlfc_rpm_replace_re, "fc33", get_url_fc_rpm_match.group(0))

        file_version = ""
        filename = ""
        if found_url:
            filename = f"{cwd}/{os.path.basename(found_url)}"
            file_version = thread_version_sort[-1][0]
        else:
            print("Cant find download link in thread")
            sys.exit(1)

        if not os.path.exists(filename):
            #print(f"{found_url} {thread_version_sort[-1][0]}")
            curl_result = ""
            curl_cmd = f"curl -L -O {found_url}"
            #print(f"curl_cmd: {curl_cmd}")
            try:
                process = subprocess.run(
                    curl_cmd,
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=cwd,
                )
            except subprocess.CalledProcessError as err:
                print(f"Unable to download {found_url} in {cwd}: {err}")
                sys.exit(1)

            curl_result = process.stdout
            #print(f"curl_result: {curl_result}")

        if os.path.isfile(filename):
            rpm_extract_cmd = f'rpm2cpio {filename} | cpio -ivdm --directory="{cwd}"'
            #print(f"{rpm_extract_cmd}")
            try:
                process = subprocess.run(
                    rpm_extract_cmd,
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=cwd,
                )
            except subprocess.CalledProcessError as err:
                print(f"Unable to extract {filename} in {cwd}: {err}")
                sys.exit(1)

            fix_insync_cmd1 = f'rm libX11* && rm libxkbcommon.so* && rm libtinfo.so* && rm libpng16.so* && rm lib{{drm,GLX,GLdispatch}}.so* && rm libgdk_pixbuf-2.0.so* && rm libxkbcommon.so* && rm libxcb*'
            fix_insync_cwd1 = f"{cwd}/usr/lib/insync/"
            #print(f"{fix_insync_cmd1}")
            #print(f"{fix_insync_cwd1}")
            process = subprocess.run(
                fix_insync_cmd1,
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                cwd=fix_insync_cwd1,
            )

            fix_insync_cwd2 = f"{cwd}/usr/bin/"
            fix_insync_cmd2 = f"sd '/usr/lib/insync/insync' '/usr/lib64/insync/insync' 'insync'"
            #print(f"{fix_insync_cmd2}")
            #print(f"{fix_insync_cwd2}")
            process = subprocess.run(
                fix_insync_cmd2,
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                cwd=fix_insync_cwd2,
            )
            fix_insync_cmd3 = f"sd '\"\$@\"' '\"$@\" --ca-path /var/cache/ca-certs/anchors/ --qt-qpa-platform xcb' 'insync'"
            #print(f"{fix_insync_cmd3}")
            #print(f"{fix_insync_cwd2}")
            process = subprocess.run(
                fix_insync_cmd3,
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                cwd=fix_insync_cwd2,
            )
            fix_insync_cmd4 = f"sd 'LC_TIME=C' 'LC_TIME=C QT_QPA_PLATFORM=xcb' 'insync'"
            #print(f"{fix_insync_cmd4}")
            #print(f"{fix_insync_cwd2}")
            process = subprocess.run(
                fix_insync_cmd4,
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                cwd=fix_insync_cwd2,
            )

        filename_cmake = f"{cwd}/CMakeLists.txt"
        if not os.path.exists(filename_cmake):
            cmake_cmd = f"curl --location https://raw.githubusercontent.com/insilications/insync-clr/master/CMakeLists.txt -o CMakeLists.txt"
            #print(f"cmake_cmd: {cmake_cmd}")
            try:
                process = subprocess.run(
                    cmake_cmd,
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=cwd,
                )
            except subprocess.CalledProcessError as err:
                print(f"Unable to download {filename_cmake} in {cwd}: {err}")
                sys.exit(1)

        filename_tar = f"{cwd}/insync-v{file_version}.tar.gz"
        if not os.path.exists(filename_tar):
            tar_cmd = f"tar --create --add-file=CMakeLists.txt --file=- usr/ | pigz -9 -p 16 > {filename_tar}"
            #print(f"tar_cmd: {tar_cmd}")
            try:
                process = subprocess.run(
                    tar_cmd,
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=cwd,
                )
            except subprocess.CalledProcessError as err:
                print(f"Unable to tar {filename_tar} in {cwd}: {err}")
                sys.exit(1)

        filename_uri = f"file://{filename_tar}"
        print(filename_uri)
    else:
        filename_uri = f"file://{filename[0]}"
        print(filename_uri)

if __name__ == "__main__":
    main()
