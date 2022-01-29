#!/usr/bin/env python
from __future__ import absolute_import, annotations, unicode_literals

import argparse
import concurrent.futures
import re
import subprocess
from typing import Any, TextIO, Union

import dnf  # type: ignore
import hawkey  # type: ignore


def subprocess_run(cmd: str) -> str:
    process = subprocess.run(
        cmd,
        check=False,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
    )
    return process.stdout


def sort_it(key) -> str:
    if key[1] is None:
        return f"{key[0]}{key[2]}"
    else:
        return f"{key[0]}|{key[1]}{key[2]}"


def _get_recursive_providers_query(query_in, providers, base, done=None) -> Any:
    done = done if done else base.sack.query().filterm(empty=True)
    t = base.sack.query().filterm(empty=True)
    for pkg in providers.run():
        t = t.union(query_in.filter(provides=pkg.requires))
    query_select = t.difference(done)
    if query_select:
        done = _get_recursive_providers_query(query_in, query_select, base, done=t.union(done))
    return t.union(done)


def main() -> None:
    cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final: list[tuple[str, str, str]] = []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--pkg_name",
        action="store",
        dest="pkg_name",
        default="",
        help="Package name",
    )
    parser.add_argument(
        "-s",
        "--specfile",
        action="store",
        dest="specfile",
        default="",
        help="Specfile",
    )
    parser.add_argument(
        "-c",
        "--pm_conf_local",
        action="store",
        dest="pm_conf_local",
        default="",
        help="PM_CONF_LOCAL",
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="Enable debugging",
    )
    args = parser.parse_args()

    base = dnf.Base()
    base.conf.read(filename="/aot/build/clearlinux/repo/dnf.conf")
    base.conf.releasever = "clear"
    base.read_all_repos()
    base.fill_sack(load_system_repo=False, load_available_repos=True)
    if args.debug:
        print(f"{args.pkg_name=}")
        print(f"{args.specfile=}")
        print(f"{args.pm_conf_local=}")

    cmd_pkg_nvr_whatrequires_NO_PKG_NAME = f"{args.pkg_name}-"
    cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1 = re.compile(cmd_pkg_nvr_whatrequires_NO_PKG_NAME, re.MULTILINE)

    cmd_pkg_nvr = f"rpmspec --define='_vendor clr' --srpm --query --queryformat='%{{NVR}}' {args.specfile}"
    cmd_pkg_vr_cmd = f"rpmspec --define='_vendor clr' --srpm --query --queryformat='%{{VERSION}}-%{{RELEASE}}' {args.specfile}"
    cmd_pkg_nvr_provides_result_re1 = re.compile(r"(^[a-zA-Z0-9_\-\.\(\)\+]+)", re.MULTILINE)

    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        cmd_pkg_nvr_exe = pool.submit(subprocess_run, cmd_pkg_nvr)
        cmd_pkg_vr_exe = pool.submit(subprocess_run, cmd_pkg_vr_cmd)
        cmd_pkg_nvr_result = cmd_pkg_nvr_exe.result()
        cmd_pkg_vr_result = cmd_pkg_vr_exe.result()

    if args.debug:
        print(f"package: {cmd_pkg_nvr_result}")
        print(f"Custom regex: {cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1.pattern}\n")

    # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --nvr --provides 'pipewire-0.3.48-681'"
    query_pkg_nvr_provides = dnf.subject.Subject(cmd_pkg_nvr_result, ignore_case=True).get_best_query(  # type: ignore
        base.sack, with_nevra=True, with_provides=False, with_filenames=False, forms=hawkey.FORM_NEVR
    )
    cmd_pkg_nvr_provides_result_tmp: list[str] = []
    pkgs: set[str] = set()
    rels = set()
    for pkg in query_pkg_nvr_provides:
        rels.update(getattr(pkg, "provides"))
    pkgs.update(match.group(1) for rel in rels if (match := cmd_pkg_nvr_provides_result_re1.search(str(rel))))
    cmd_pkg_nvr_provides_result_tmp = sorted(pkgs)
    # print(f"\ncmd_pkg_nvr_provides_result_tmp:")
    # for p in cmd_pkg_nvr_provides_result_tmp:
    # print(f"cmd_pkg_nvr_provides_result_tmp: {p}")

    cmd_pkg_nvr_whatrequires1_tmp: list[tuple[str, str, str]] = []
    cmd_pkg_nvr_whatrequires1_unique: list[tuple[str, str, str]] = []
    for item in cmd_pkg_nvr_provides_result_tmp:
        # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='{cmd_pkg_nvr_result} <- %{{NAME}}-%{{VERSION}}-%{{RELEASE}} (x86_64)' --arch=x86_64 --srpm --whatrequires '{item}'"
        query_x86_64 = base.sack.query().filterm(arch="x86_64")  # type: ignore
        resolved_nevras_query_x86_64 = base.sack.query().filterm(empty=True)  # type: ignore
        resolved_nevras_query_x86_64 = resolved_nevras_query_x86_64.union(
            query_x86_64.intersection(
                dnf.subject.Subject(item).get_best_query(base.sack, with_provides=False, with_filenames=False)  # type: ignore
            )
        )
        depquery_x86_64 = query_x86_64.filter(requires__glob=item)
        depquery_x86_64 = depquery_x86_64.union(query_x86_64.filter(requires=resolved_nevras_query_x86_64))
        pkg_list = []
        for pkg in depquery_x86_64:
            srcname = pkg.source_name
            # print(f"pkg: {pkg} - srcname: {srcname}")
            if srcname is not None:
                tmp_query = base.sack.query().filterm(name=srcname, evr=pkg.evr, arch="src")  # type: ignore
                pkg_list += tmp_query.run()

        pkg_list_unique = list(dict.fromkeys(pkg_list))
        q = base.sack.query().filterm(pkg=pkg_list_unique)  # type: ignore
        for pkg in q:
            # print(f"{pkg.name}-{pkg.evr}")
            m3 = f"{pkg.name}-{pkg.evr}"
            if not cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1.search(m3):
                cmd_pkg_nvr_whatrequires1_tmp.append((cmd_pkg_nvr_result, m3, "(x86_64)"))

        # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='{cmd_pkg_nvr_result} <- %{{NAME}}-%{{VERSION}}-%{{RELEASE}} (src)' --arch=src --whatrequires '{item}'"
        query_src = base.sack.query().filterm(arch="src")  # type: ignore
        resolved_nevras_query_src = base.sack.query().filterm(empty=True)  # type: ignore
        resolved_nevras_query_src = resolved_nevras_query_src.union(
            query_src.intersection(dnf.subject.Subject(item).get_best_query(base.sack, with_provides=False, with_filenames=False))  # type: ignore
        )
        depquery_src = query_src.filter(requires__glob=item)
        depquery_src = depquery_src.union(query_src.filter(requires=resolved_nevras_query_src))
        for pkg in depquery_src:
            # print(f"{pkg.name}-{pkg.evr}")
            m3 = f"{pkg.name}-{pkg.evr}"
            if not cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1.search(m3):
                cmd_pkg_nvr_whatrequires1_tmp.append((cmd_pkg_nvr_result, m3, "(src)"))

    cmd_pkg_nvr_whatrequires1_unique = list(dict.fromkeys(cmd_pkg_nvr_whatrequires1_tmp))
    # print(f"\ncmd_pkg_nvr_whatrequires1_unique:")
    # for i in cmd_pkg_nvr_whatrequires1_unique:
    # print(f"{i[0]} <- {i[1]} {i[2]}")
    # print(f"len(cmd_pkg_nvr_whatrequires1_unique): {len(cmd_pkg_nvr_whatrequires1_unique)}")

    cmd_pkg_nvr_whatrequires1_src_x86_64_to_check = {}  # type: ignore
    for item in cmd_pkg_nvr_whatrequires1_unique:  # type: ignore
        if item[1] not in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check.keys():
            # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='%{{NAME}}-%{{VERSION}}-%{{RELEASE}}' --resolve --recursive --requires '{i[1]}'"
            cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[item[1]] = set()
            query_resolve_recursive_requires = dnf.subject.Subject(item[1], ignore_case=True).get_best_query(  # type: ignore
                base.sack, with_nevra=True, with_provides=False, with_filenames=False, forms=hawkey.FORM_NEVR
            )
            rels = set()
            for pkg in query_resolve_recursive_requires:
                rels.update(getattr(pkg, "requires"))

            query_available = base.sack.query().available()  # type: ignore
            providers = query_available.filter(provides=rels)
            providers = providers.union(_get_recursive_providers_query(query_in=query_available, providers=providers, base=base))
            pkgs = set()
            for i in providers.latest().run():
                pkgs.add(i)

            pkgs_list = sorted(pkgs)
            for p in pkgs_list:
                # print(f"{p.name}-{p.evr}")
                cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[item[1]].add(f"{p.name}-{p.evr}")  # type: ignore

    # print(f"\n cmd_pkg_nvr_whatrequires1_src_x86_64_to_check")
    # for k in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check.keys():
    # print(f"\n{k}: {len(cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[k])}")
    # print(sorted(cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[k]))

    for item in cmd_pkg_nvr_whatrequires1_unique:  # type: ignore
        # print(f"1 src item[1]: {item[1]} - item[0]: {item[0]}")
        if item[1] in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check.keys():
            # print(f"2 src item[1]: {item[1]} - item[0]: {item[0]}")
            if item[0] in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[item[1]]:
                # print(f"AAA src item[1]: {item[1]} - item[0]: {item[0]}")
                cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final.append((item[0], item[1], item[2]))

    cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final.sort(key=lambda item: item[1])

    for item in cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final:  # type: ignore
        print(f"{item[0]} <- {item[1]} {item[2]}")

    ### subpackages
    subpkg_list_provides_result_re1 = re.compile(r"(^[a-zA-Z0-9_\-\.\(\)\+]+)", re.MULTILINE)
    get_subpackages_list = []
    get_subpackages_re1 = re.compile(r"(?:^%package\s)(.+)", re.MULTILINE)
    get_subpackages_file: TextIO
    with open(args.specfile, mode="r", encoding="utf-8") as get_subpackages_file:
        _s: str
        for _s in get_subpackages_file:
            if _s.startswith("#"):
                continue
            if get_subpackages_match := get_subpackages_re1.search(_s):
                get_subpackages_list.append(get_subpackages_match.group(1))

    # get_subpackages_list.append("-n porra-kk")
    get_subpackages_list.sort()
    subpackages_re1 = re.compile(r"(?:^\-n\s)(.+)", re.MULTILINE)
    subpkg_list_tuples: list[tuple[str, str]] = []
    subpkg_list_provides_results_dict = {}  # type: ignore
    for subpkg in get_subpackages_list:
        if subpackages_match := subpackages_re1.search(subpkg):
            subpkg_list_tuples.append((f"{subpackages_match.group(1)}-{cmd_pkg_vr_result}", f"{subpackages_match.group(1)}"))
        else:
            subpkg_list_tuples.append((f"{args.pkg_name}-{subpkg}-{cmd_pkg_vr_result}", f"{args.pkg_name}-{subpkg}"))

    for subpkg_full in subpkg_list_tuples:
        # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --nvr --provides '{subpkg_full[0]}'"
        subpkg_list_provides_results_dict[subpkg_full[0]] = set()
        query_subpkg_provides = dnf.subject.Subject(subpkg_full[0], ignore_case=True).get_best_query(  # type: ignore
            base.sack, with_nevra=True, with_provides=False, with_filenames=False, forms=hawkey.FORM_NEVR
        )
        pkgs_list_subpkg_provides: list[str] = []
        pkgs_subpkg_provides: set[str] = set()
        rels_subpkg_provides: set[str] = set()
        for pkg in query_subpkg_provides:
            rels_subpkg_provides.update(getattr(pkg, "provides"))
        pkgs_subpkg_provides.update(
            match.group(1) for rel in rels_subpkg_provides if (match := subpkg_list_provides_result_re1.search(str(rel)))
        )
        pkgs_list_subpkg_provides = sorted(pkgs_subpkg_provides)
        for p in pkgs_list_subpkg_provides:
            subpkg_list_provides_results_dict[subpkg_full[0]].add(p)

    # print(f"\n subpkg_list_provides_results_dict")
    # for k in subpkg_list_provides_results_dict.keys():
    # print(f"{k}:")
    # print(f"{subpkg_list_provides_results_dict[k]}")

    subpkg_list_final = []
    subpkg_list_final_unique = []
    subpkg_list_provides_whatrequires_src_x86_64_tmp: list[tuple[str, str, str, str]] = []
    for k in subpkg_list_provides_results_dict.keys():
        for provide in subpkg_list_provides_results_dict[k]:
            # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='{k}|{provide} <- %{{NAME}}-%{{VERSION}}-%{{RELEASE}} (x86_64)' --arch=x86_64 --srpm --whatrequires '{provide}'"
            query_x86_64 = base.sack.query().filterm(arch="x86_64")  # type: ignore
            resolved_nevras_query_x86_64 = base.sack.query().filterm(empty=True)  # type: ignore
            resolved_nevras_query_x86_64 = resolved_nevras_query_x86_64.union(
                query_x86_64.intersection(
                    dnf.subject.Subject(provide).get_best_query(base.sack, with_provides=False, with_filenames=False)  # type: ignore
                )
            )
            depquery_x86_64 = query_x86_64.filter(requires__glob=provide)
            depquery_x86_64 = depquery_x86_64.union(query_x86_64.filter(requires=resolved_nevras_query_x86_64))
            pkg_list = []
            for pkg in depquery_x86_64:
                srcname = pkg.source_name
                # print(f"pkg: {pkg} - srcname: {srcname}")
                if srcname is not None:
                    tmp_query = base.sack.query().filterm(name=srcname, evr=pkg.evr, arch="src")  # type: ignore
                    pkg_list += tmp_query.run()

            pkg_list_unique = list(dict.fromkeys(pkg_list))
            q = base.sack.query().filterm(pkg=pkg_list_unique)  # type: ignore
            for pkg in q:
                # print(f"{pkg.name}-{pkg.evr}")
                m3 = f"{pkg.name}-{pkg.evr}"
                if not cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1.search(m3):
                    subpkg_list_provides_whatrequires_src_x86_64_tmp.append((k, provide, m3, "(x86_64)"))

            # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='{k}|{provide} <- %{{NAME}}-%{{VERSION}}-%{{RELEASE}} (src)' --arch=src --whatrequires '{provide}'"
            query_src = base.sack.query().filterm(arch="src")  # type: ignore
            resolved_nevras_query_src = base.sack.query().filterm(empty=True)  # type: ignore
            resolved_nevras_query_src = resolved_nevras_query_src.union(
                query_src.intersection(
                    dnf.subject.Subject(provide).get_best_query(base.sack, with_provides=False, with_filenames=False)  # type: ignore
                )
            )
            depquery_src = query_src.filter(requires__glob=provide)
            depquery_src = depquery_src.union(query_src.filter(requires=resolved_nevras_query_src))
            for pkg in depquery_src:
                # print(f"{pkg.name}-{pkg.evr}")
                m3 = f"{pkg.name}-{pkg.evr}"
                if not cmd_pkg_nvr_whatrequires_NO_PKG_NAME_result_re1.search(m3):
                    subpkg_list_provides_whatrequires_src_x86_64_tmp.append((k, provide, m3, "(src)"))

    # print(f"\subpkg_list_provides_whatrequires_src_x86_64_tmp:")
    # for i in subpkg_list_provides_whatrequires_src_x86_64_tmp:
    # print(f"{i[0]}|{i[1]} <- {i[2]} {i[3]}")
    # print(f"len(subpkg_list_provides_whatrequires_src_x86_64_tmp): {len(subpkg_list_provides_whatrequires_src_x86_64_tmp)}")

    for item in subpkg_list_provides_whatrequires_src_x86_64_tmp:  # type: ignore
        if item[2] not in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check.keys():
            # "dnf --config=/aot/build/clearlinux/repo/dnf.conf repoquery --quiet --releasever=clear --qf='%{{NAME}}-%{{VERSION}}-%{{RELEASE}}' --resolve --recursive --requires '{i[2]}'"
            cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[item[2]] = set()
            query_resolve_recursive_requires = dnf.subject.Subject(item[2], ignore_case=True).get_best_query(  # type: ignore
                base.sack, with_nevra=True, with_provides=False, with_filenames=False, forms=hawkey.FORM_NEVR
            )
            rels = set()
            for pkg in query_resolve_recursive_requires:
                rels.update(getattr(pkg, "requires"))

            query_available = base.sack.query().available()  # type: ignore
            providers = query_available.filter(provides=rels)
            providers = providers.union(_get_recursive_providers_query(query_in=query_available, providers=providers, base=base))
            pkgs = set()
            for i in providers.latest().run():
                pkgs.add(i)

            pkgs_list = sorted(pkgs)
            for p in pkgs_list:
                cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[item[2]].add(f"{p.name}-{p.evr}")  # type: ignore

    for m in subpkg_list_provides_whatrequires_src_x86_64_tmp:
        if m[2] in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check.keys():
            if m[0] in cmd_pkg_nvr_whatrequires1_src_x86_64_to_check[m[2]]:
                if m[1] in m[0]:
                    subpkg_list_final.append((m[0], None, m[2], m[3]))
                else:
                    subpkg_list_final.append((m[0], m[1], m[2], m[3]))  # type: ignore

    subpkg_list_final_unique = list(dict.fromkeys(subpkg_list_final))
    subpkg_list_final_unique.sort(key=sort_it)
    for p in subpkg_list_final_unique:  # type: ignore
        if p[1] is None:
            print(f"{p[0]} <- {p[2]} {p[3]}")
        else:
            print(f"{p[0]}|{p[1]} <- {p[2]} {p[3]}")

    if args.debug:
        print(f"\nlen(subpkg_list_final): {len(subpkg_list_final)}")
        print(f"len(subpkg_list_final_unique): {len(subpkg_list_final_unique)}")
        print(f"len(cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final): {len(cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final)}")
        print(f"total: {len(subpkg_list_final_unique)+len(cmd_pkg_nvr_whatrequires1_tmp_unique_tuples_final)}")

    base.close()


if __name__ == "__main__":
    main()
