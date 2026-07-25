#!/usr/bin/env bash
# List Hetzner server types AVAILABLE in a given location — run this BEFORE
# `tofu apply` so you pick a type that actually exists there. Server types vary by
# location AND stock: e.g. `cpx41` is not sold and the current AMD line is the
# `cpx*2` series (cpx12/22/32/42/52/62); the Intel `cx*`/`ccx*` availability
# differs too. Provisioning with an unavailable type fails mid-apply.
#
# Usage:  ./hetzner-server-types.sh [location]        # default: nbg1
#         HCLOUD_TOKEN=... ./hetzner-server-types.sh fsn1
# Token:  reads HCLOUD_TOKEN or TF_VAR_hcloud_token from the environment.
set -euo pipefail
loc="${1:-nbg1}"
tok="${HCLOUD_TOKEN:-${TF_VAR_hcloud_token:-}}"
[ -n "$tok" ] || { echo "set HCLOUD_TOKEN or TF_VAR_hcloud_token" >&2; exit 1; }

dc=$(curl -fsS -H "Authorization: Bearer $tok" "https://api.hetzner.cloud/v1/datacenters?per_page=50")
st=$(curl -fsS -H "Authorization: Bearer $tok" "https://api.hetzner.cloud/v1/server_types?per_page=100")

LOC="$loc" python3 - "$dc" "$st" <<'PY'
import json, os, sys
dc = json.loads(sys.argv[1]); st = json.loads(sys.argv[2])
loc = os.environ["LOC"]
byid = {s["id"]: s for s in st["server_types"]}
avail = set()
dcs = [d for d in dc["datacenters"] if d.get("location", {}).get("name") == loc]
if not dcs:
    print("no datacenter for location %r; try one of: %s" %
          (loc, ", ".join(sorted({d["location"]["name"] for d in dc["datacenters"]}))))
    sys.exit(1)
for d in dcs:
    avail |= set(d["server_types"]["available"])
rows = []
for sid in avail:
    s = byid.get(sid)
    if not s:
        continue
    rows.append((s["memory"], s["cores"], s["name"], s["architecture"], s["cpu_type"]))
print("Available in %s (%s):" % (loc, ", ".join(d["name"] for d in dcs)))
print("  %-8s %-6s %-8s %-6s %s" % ("TYPE", "vCPU", "RAM(GB)", "ARCH", "CPU"))
for mem, cores, name, arch, cput in sorted(rows):
    print("  %-8s %-6s %-8s %-6s %s" % (name, cores, int(mem), arch, cput))
PY
