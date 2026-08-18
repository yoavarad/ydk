#!/usr/bin/env python3
"""Generate .ydk/contracts/ snapshot from YDK contract components for enforcement."""

import json
import os
from pathlib import Path

import yaml


def main():
    uc_path = os.environ.get("YDK_COMPONENTS_CONTRACT", "")
    if not uc_path or not Path(uc_path).exists():
        print("[]")
        return

    raw = yaml.safe_load(Path(uc_path).read_text(encoding="utf-8")) or {}
    contracts = raw if isinstance(raw, list) else []

    # Extract ports from all contracts
    ports_snapshot = {}
    for contract in contracts:
        for port in contract.get("ports", []):
            pname = port["name"]
            methods_raw = port.get("methods", {})
            methods = {}
            if isinstance(methods_raw, dict):
                for method_name, method_def in methods_raw.items():
                    mdef = method_def if isinstance(method_def, dict) else {}
                    params = mdef.get("params", {})
                    if isinstance(params, dict):
                        args = []
                        for k, v in params.items():
                            ptype = v.get("type", "str") if isinstance(v, dict) else str(v)
                            args.append({"name": k, "type": ptype})
                    else:
                        args = []
                    ret = mdef.get("returns", "None")
                    ret_type = ret.get("type", "None") if isinstance(ret, dict) else str(ret)
                    methods[method_name] = {"args": args, "returns": ret_type}
            elif isinstance(methods_raw, list):
                for m in methods_raw:
                    raw_args = m.get("args", [])
                    if not raw_args and isinstance(m.get("input"), dict):
                        raw_args = [{"name": k, "type": str(v)} for k, v in m["input"].items()]
                    args = [{"name": a["name"], "type": a.get("type", "str")} for a in raw_args]
                    methods[m["name"]] = {
                        "args": args,
                        "returns": m.get("returns", m.get("output", "None")),
                    }
            ports_snapshot[pname] = {"methods": methods}

    output = []
    if ports_snapshot:
        content = yaml.dump({"ports": ports_snapshot}, default_flow_style=False)
        output.append({"path": "ports.yaml", "content": content})

    # Service snapshot
    uc_snapshot = {}
    for uc in contracts:
        uc_snapshot[uc["name"]] = {
            "ports": [p["name"] if isinstance(p, dict) else p for p in uc.get("ports", [])],
            "methods": uc.get("methods", {}),
        }
    if uc_snapshot:
        uc_content = yaml.dump({"services": uc_snapshot}, default_flow_style=False)
        output.append({"path": "services.yaml", "content": uc_content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()
