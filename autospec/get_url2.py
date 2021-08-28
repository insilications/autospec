#!/usr/bin/env python

import re
import sys
import requests
import natsort

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

soup = BeautifulSoup(requests.get("http://dist.schmorp.de/libev/").text, "html5lib")
libev_re = re.compile(r"^libev-(?:\d+)(?:\.\d+)\.tar.gz$")
link_list = soup.find_all("a", string=libev_re)

#link_list = ["libev-4.33.tar.gz", "libev-4.33.2.tar.gz", "libev-4.43.tar.gz"]
link_version_sort = []
for link in link_list:
    #print(link.text)
    link_version_sort.append(link.text)

if not link_version_sort:
    print("")

link_version_sort_final = natsort.natsorted(link_version_sort, key=lambda x: x.replace('.', '~')+'z')

#for link in link_version_sort:
    #print(link)

if link_version_sort_final:
    print(f"{link_version_sort_final[-1]}")
else:
    print("")
