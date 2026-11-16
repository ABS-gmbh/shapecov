#!/usr/bin/env python3
"""Docker images by digest, from security/images.lock.json.

  python3 security/images.py pull [TAG ...]   pull each image by its pinned digest and tag it locally
  python3 security/images.py verify [TAG ...] check that each local tag is the pinned content
  python3 security/images.py drift            report tags whose upstream digest moved (registry, read only)

The code names images by tag (`golang:1.26`). `pull` fetches `golang@sha256:…` and tags it
`golang:1.26`, so every later `docker run golang:1.26` uses the pinned content, whatever the tag
points to upstream. `verify` exits 1 if a local tag is not the pinned digest; a tag not present
locally is reported and skipped. `drift` makes one anonymous request per image to Docker Hub and
exits 0 either way: a moved tag is a reason to review and update the lock, not a failure. With no
TAG, every image in the lock. Standard library plus the docker CLI.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

LOCK = Path(__file__).resolve().parent / "images.lock.json"
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                    "application/vnd.oci.image.manifest.v1+json"])


def lock(tags):
    images = json.loads(LOCK.read_text())["images"]
    unknown = [t for t in tags if t not in images]
    if unknown:
        sys.exit("not in security/images.lock.json: %s" % ", ".join(unknown))
    return {t: images[t] for t in (tags or images)}


def repo(tag):
    return tag.rsplit(":", 1)[0]


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def pull(images):
    for tag, e in images.items():
        pinned = "%s@%s" % (repo(tag), e["digest"])
        plat = ["--platform", e["platform"]] if e.get("platform") else []
        p = docker("pull", "-q", *plat, pinned)
        if p.returncode != 0:
            sys.exit("pull %s failed: %s" % (pinned, p.stderr.strip()))
        docker("tag", pinned, tag)
        print("pulled %s as %s" % (pinned, tag))
    return 0


def verify(images):
    bad = 0
    for tag, e in images.items():
        p = docker("image", "inspect", tag, "--format", "{{json .RepoDigests}}")
        if p.returncode != 0:
            print("absent   %s" % tag)
            continue
        digests = json.loads(p.stdout or "[]")
        want = "%s@%s" % (repo(tag), e["digest"])
        if want in digests:
            print("pinned   %s" % tag)
        else:
            bad += 1
            print("DIFFERS  %s: local %s, pinned %s" % (tag, ", ".join(digests) or "no registry digest", e["digest"]))
    print("%d local tag(s) differ from the lock" % bad)
    return 1 if bad else 0


def registry_digest(tag):
    name, ref = tag.rsplit(":", 1)
    path = name if "/" in name else "library/" + name
    tok = json.load(urllib.request.urlopen(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull" % path, timeout=30))["token"]
    req = urllib.request.Request("https://registry-1.docker.io/v2/%s/manifests/%s" % (path, ref), method="HEAD",
                                 headers={"Authorization": "Bearer " + tok, "Accept": ACCEPT})
    return urllib.request.urlopen(req, timeout=30).headers["Docker-Content-Digest"]


def drift(images):
    moved = 0
    for tag, e in images.items():
        try:
            now = registry_digest(tag)
        except Exception as ex:  # report and go on: drift is informational
            print("unknown  %s: %s" % (tag, ex))
            continue
        if now == e["digest"]:
            print("current  %s" % tag)
        else:
            moved += 1
            print("MOVED    %s: upstream %s, pinned %s" % (tag, now, e["digest"]))
    print("%d tag(s) moved upstream since they were pinned" % moved)
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("pull", "verify", "drift"):
        print(__doc__.strip())
        return 2
    images = lock(sys.argv[2:])
    return {"pull": pull, "verify": verify, "drift": drift}[sys.argv[1]](images)


if __name__ == "__main__":
    sys.exit(main())
