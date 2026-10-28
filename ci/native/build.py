"""Manual native recipe. --check is static; --build-ios is an explicit future build.

No cloud workflow is invoked by this file. Native builds require the reviewed
outer CI driver to own the process group and enforce aggregate resource cleanup.
"""
import argparse
import json
from pathlib import Path
from check_static import check, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--build-ios', action='store_true')
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--parent-owned-group', action='store_true')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    repo = directory.parents[1]
    lock = check(directory, repo)
    if args.check:
        require(args.work_dir is None and args.output is None and not args.parent_owned_group,
                'static check takes no build options')
        print(json.dumps({'status':'PASS_STATIC_SOURCE_PREPARATION_ONLY','native_build_run':False},sort_keys=True))
        return
    require(args.parent_owned_group, 'native build requires the owned-group outer driver')
    require(args.work_dir is not None and args.output is not None, 'explicit work/output paths required')
    # Deliberately imported only after static mode has returned.
    from native_runtime import build_ios
    build_ios(repo, directory, lock, args.work_dir, args.output)


if __name__ == '__main__':
    main()
