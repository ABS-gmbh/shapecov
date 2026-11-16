#!/usr/bin/env python3
"""Test that third-party code run by the kit cannot reach the internet. Needs Docker.

  python3 security/isolation.py [--control]

The kit runs indexers, SDKs and stellar-core either with `--network none` or on a Docker network
created with `--internal` (the replay harness's shapecov-replay-net). This creates a network the
same way, starts the pinned python image on it and, separately, with `--network none`, and from
inside each tries to:
- resolve github.com;
- open TCP connections to 1.1.1.1:443 and 8.8.8.8:53, by address, so DNS cannot be the only barrier.
Every attempt must fail. `--control` also runs the same probe on Docker's default bridge network,
where it must succeed, to show the probe can tell the difference (needs internet on the host).

Exit 1 if any isolated attempt succeeds, or the control fails. The image is the one pinned in
security/images.lock.json; `security/images.py pull python:3.14-slim` fetches it.
"""
import subprocess
import sys

IMAGE = "python:3.14-slim"
NET = "shapecov-isolation-test"
PROBE = r'''
import socket, sys
out = []
try:
    socket.getaddrinfo("github.com", 443)
    out.append("dns:reached")
except OSError:
    out.append("dns:blocked")
for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
    s = socket.socket(); s.settimeout(5)
    try:
        s.connect((host, port)); out.append("%s:%d:reached" % (host, port))
    except OSError:
        out.append("%s:%d:blocked" % (host, port))
    finally:
        s.close()
print(" ".join(out))
'''


def docker(*args, check=False):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def probe(network):
    p = docker("run", "--rm", "--network", network, IMAGE, "python3", "-c", PROBE)
    if p.returncode != 0:
        sys.exit("probe on %s did not run: %s" % (network, p.stderr.strip()))
    return p.stdout.split()


def main():
    control = "--control" in sys.argv[1:]
    docker("network", "rm", NET)
    docker("network", "create", "--internal", NET, check=True)
    bad = 0
    try:
        for network, label in ((NET, "--internal network (as the replay harness)"), ("none", "--network none")):
            results = probe(network)
            reached = [r for r in results if r.endswith(":reached")]
            bad += bool(reached)
            print("%-45s %s" % (label, "ISOLATION FAILED: " + " ".join(reached) if reached else "no route: " + " ".join(results)))
        if control:
            results = probe("bridge")
            ok = all(r.endswith(":reached") for r in results)
            bad += not ok
            print("%-45s %s" % ("control: default bridge network", ("reached, as expected: " if ok else "CONTROL FAILED: ")
                                + " ".join(results)))
    finally:
        docker("network", "rm", NET)
    print("ISOLATION OK" if not bad else "%d problem(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
